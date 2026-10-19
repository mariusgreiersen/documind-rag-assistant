"""LLM provider adapters.

The rest of the application depends only on the ``LLMProvider`` protocol, which
exposes two narrow operations: produce a structured grounded answer, and rewrite
a follow-up question into a standalone search query. Providers receive no tools
and cannot take actions, so instructions hidden in documents have nothing to
trigger beyond the text of the answer itself.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from documind.core.config import Settings
from documind.core.errors import LLMNotConfigured, LLMProviderError
from documind.core.logging import log_event, timed
from documind.generation.citation_validator import RawAnswer
from documind.generation.prompts import (
    ANSWER_SCHEMA,
    ANSWER_SYSTEM_PROMPT,
    REWRITE_SCHEMA,
    REWRITE_SYSTEM_PROMPT,
    HistoryTurn,
    SourcePassage,
    build_answer_message,
    build_rewrite_message,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class LLMResult:
    answer: RawAnswer
    model: str
    usage: Usage = field(default_factory=Usage)


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_answer(self, question: str, sources: Sequence[SourcePassage], history: Sequence[HistoryTurn]) -> LLMResult: ...

    def rewrite_query(self, question: str, history: Sequence[HistoryTurn]) -> str: ...


def _parse_answer(payload: dict[str, Any]) -> RawAnswer:
    return RawAnswer(
        status=str(payload.get("status", "")),
        answer=str(payload.get("answer", "")),
        cited_source_ids=[str(x) for x in payload.get("cited_source_ids", []) if isinstance(x, str)],
        unsupported_aspects=[str(x) for x in payload.get("unsupported_aspects", []) if isinstance(x, str)],
    )


class AnthropicProvider:
    """Claude via the official Anthropic SDK, using structured outputs (JSON schema)."""

    name = "anthropic"

    def __init__(self, settings: Settings, api_key: str) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=settings.llm_timeout_seconds, max_retries=2)
        self.model = settings.llm_model
        self._effort = settings.llm_effort
        self._max_tokens = settings.llm_max_tokens
        self._fallback = settings.llm_refusal_fallback

    def _call(self, *, system: str, user: str, schema: dict[str, Any], purpose: str) -> tuple[dict[str, Any], str, Usage]:
        a = self._anthropic
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": self._effort, "format": {"type": "json_schema", "schema": schema}},
        }
        try:
            with timed() as t:
                if self._fallback:
                    # On a safety-classifier decline, the API re-runs the request on the
                    # recommended fallback model inside the same call.
                    response = self._client.beta.messages.create(**kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                else:
                    response = self._client.messages.create(**kwargs)
        except a.APITimeoutError as exc:
            log_event(logger, "llm_timeout", logging.WARNING, purpose=purpose)
            raise LLMProviderError("The AI provider took too long to respond. You can still search your documents.") from exc
        except a.AuthenticationError as exc:
            log_event(logger, "llm_auth_failed", logging.ERROR, purpose=purpose)
            raise LLMProviderError("The AI provider rejected the configured API key. You can still search your documents.") from exc
        except a.RateLimitError as exc:
            log_event(logger, "llm_rate_limited", logging.WARNING, purpose=purpose)
            raise LLMProviderError("The AI provider is rate-limiting requests. Try again shortly.") from exc
        except a.APIStatusError as exc:
            log_event(
                logger, "llm_api_error", logging.ERROR, purpose=purpose, status=exc.status_code, request_id=getattr(exc, "request_id", None)
            )
            raise LLMProviderError() from exc
        except a.APIConnectionError as exc:
            log_event(logger, "llm_connection_error", logging.ERROR, purpose=purpose)
            raise LLMProviderError() from exc

        usage = Usage(getattr(response.usage, "input_tokens", None), getattr(response.usage, "output_tokens", None))
        log_event(
            logger,
            "llm_call_completed",
            purpose=purpose,
            model=response.model,
            stop_reason=response.stop_reason,
            ms=t["ms"],
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        if response.stop_reason == "refusal":
            raise LLMProviderError("The AI provider declined to answer this request.")
        if response.stop_reason == "max_tokens":
            raise LLMProviderError("The AI provider's response was cut off before it finished.")
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise LLMProviderError("The AI provider returned no answer.")
        try:
            return json.loads(text), response.model, usage
        except json.JSONDecodeError as exc:
            raise LLMProviderError("The AI provider returned a malformed answer.") from exc

    def generate_answer(self, question: str, sources: Sequence[SourcePassage], history: Sequence[HistoryTurn]) -> LLMResult:
        payload, model, usage = self._call(
            system=ANSWER_SYSTEM_PROMPT, user=build_answer_message(question, sources, history), schema=ANSWER_SCHEMA, purpose="answer"
        )
        return LLMResult(answer=_parse_answer(payload), model=model, usage=usage)

    def rewrite_query(self, question: str, history: Sequence[HistoryTurn]) -> str:
        payload, _, _ = self._call(
            system=REWRITE_SYSTEM_PROMPT, user=build_rewrite_message(question, history), schema=REWRITE_SCHEMA, purpose="rewrite"
        )
        rewritten = " ".join(str(payload.get("standalone_question", "")).split())
        return rewritten or question


AnswerFn = Callable[[str, Sequence[SourcePassage], Sequence[HistoryTurn]], dict[str, Any]]


class MockLLMProvider:
    """Deterministic provider for tests and offline development.

    By default it cites the first passage verbatim, or reports insufficient
    evidence when no passages were supplied. Tests can pass ``answer_fn`` to
    script any structured response, including malformed citations. It records
    every prompt it receives so tests can inspect what would be sent to an LLM.
    """

    name = "mock"

    def __init__(self, answer_fn: AnswerFn | None = None, model: str = "mock-llm") -> None:
        self.model = model
        self._answer_fn = answer_fn
        self.calls: list[dict[str, Any]] = []

    def generate_answer(self, question: str, sources: Sequence[SourcePassage], history: Sequence[HistoryTurn]) -> LLMResult:
        self.calls.append(
            {
                "type": "answer",
                "question": question,
                "sources": list(sources),
                "history": list(history),
                "prompt": build_answer_message(question, sources, history),
            }
        )
        if self._answer_fn is not None:
            payload = self._answer_fn(question, sources, history)
        elif sources:
            first = sources[0]
            sentence = first.chunk.text.split(". ")[0].rstrip(".")
            payload = {
                "status": "answered",
                "answer": f"{sentence}. [{first.ref_id}]",
                "cited_source_ids": [first.ref_id],
                "unsupported_aspects": [],
            }
        else:
            payload = {"status": "insufficient_evidence", "answer": "", "cited_source_ids": [], "unsupported_aspects": []}
        return LLMResult(answer=_parse_answer(payload), model=self.model)

    def rewrite_query(self, question: str, history: Sequence[HistoryTurn]) -> str:
        self.calls.append({"type": "rewrite", "question": question, "history": list(history)})
        previous = next((t.content for t in reversed(history) if t.role == "user"), "")
        return f"{previous} {question}".strip() if previous else question


def build_llm_provider(settings: Settings) -> LLMProvider | None:
    """Return the configured provider, or ``None`` when generation is unavailable (retrieval-only mode)."""
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    key = settings.resolved_llm_key()
    if not key:
        return None
    return AnthropicProvider(settings, key)


def require_provider(provider: LLMProvider | None) -> LLMProvider:
    if provider is None:
        raise LLMNotConfigured()
    return provider
