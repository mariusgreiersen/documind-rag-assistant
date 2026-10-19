"""Question answering: retrieve -> relevance gate -> generate -> validate citations.

Answer statuses (also documented in the API schema):

* ``answered`` - supported by the cited passages.
* ``partially_answered`` - some parts supported, others listed as unsupported.
* ``insufficient_evidence`` - the documents do not support an answer. Produced
  either by the relevance gate (no LLM call) or by the model itself, or by the
  validator when an answer carried no valid citation.
* ``retrieval_only`` - no LLM is configured; only passages are returned.
* ``generation_unavailable`` - the LLM call failed; passages are still returned.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from documind.core.config import Settings
from documind.core.errors import LLMProviderError
from documind.core.logging import log_event, timed
from documind.documents.document_service import DocumentService
from documind.generation.citation_validator import ValidatedCitation, validate_answer
from documind.generation.llm_provider import LLMProvider
from documind.generation.prompts import INSUFFICIENT_EVIDENCE_MESSAGE, HistoryTurn, SourcePassage, fit_sources_to_budget, label_sources
from documind.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)

RETRIEVAL_ONLY_NOTICE = (
    "Retrieval-only mode: no AI provider is configured, so no answer was generated. "
    "These are the most relevant passages found by semantic search."
)
LOW_RELEVANCE_NOTICE = (
    "No passage was similar enough to the question, so no answer was generated. The closest passages are shown for reference."
)


@dataclass
class AnswerOutcome:
    status: str
    answer: str | None
    citations: list[ValidatedCitation]
    sources: list[SourcePassage]
    unsupported_aspects: list[str] = field(default_factory=list)
    notice: str | None = None
    model: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


class AnswerService:
    def __init__(self, settings: Settings, retriever: Retriever, documents: DocumentService, llm: LLMProvider | None) -> None:
        self._settings = settings
        self._retriever = retriever
        self._documents = documents
        self._llm = llm

    @property
    def llm(self) -> LLMProvider | None:
        return self._llm

    def bound_history(self, history: Sequence[HistoryTurn]) -> list[HistoryTurn]:
        turns = [HistoryTurn(t.role, t.content[:2000]) for t in history if t.content.strip()]
        return turns[-self._settings.max_history_turns :]

    def answer(
        self,
        question: str,
        *,
        document_ids: list[str] | None = None,
        top_k: int | None = None,
        history: Sequence[HistoryTurn] = (),
    ) -> AnswerOutcome:
        s = self._settings
        question = self._retriever.validate_query(question)
        scope = self._documents.search_scope(document_ids)
        history = self.bound_history(history)
        top_k = top_k or s.default_top_k

        # Follow-up questions are rewritten into standalone search queries. History
        # only shapes the query; evidence always comes from fresh retrieval.
        search_query, rewrite_ms, rewrite_error = question, None, None
        if history and self._llm is not None:
            try:
                with timed() as t:
                    search_query = self._retriever.validate_query(self._llm.rewrite_query(question, history))
                rewrite_ms = t["ms"]
            except LLMProviderError as exc:
                rewrite_error = exc.message

        retrieval = self._retriever.search(search_query, document_ids=scope, top_k=top_k)
        sources = fit_sources_to_budget(label_sources(retrieval.chunks), s.max_context_chars)
        diagnostics: dict[str, Any] = {
            "question": question,
            "search_query": search_query,
            "query_rewritten": search_query != question,
            "rewrite_ms": rewrite_ms,
            "rewrite_error": rewrite_error,
            "top_k": retrieval.top_k,
            "documents_searched": len(scope),
            "retrieval_ms": retrieval.total_ms,
            "embedding_ms": retrieval.embedding_ms,
            "search_ms": retrieval.search_ms,
            "top_score": retrieval.top_score,
            "min_relevance_score": s.min_relevance_score,
            "passages_in_context": len(sources),
            "llm_called": False,
        }

        if not sources or (retrieval.top_score or 0.0) < s.min_relevance_score:
            diagnostics["gate"] = "below_relevance_threshold"
            log_event(logger, "answer_gated", top_score=retrieval.top_score, threshold=s.min_relevance_score)
            return AnswerOutcome(
                status="insufficient_evidence",
                answer=INSUFFICIENT_EVIDENCE_MESSAGE,
                citations=[],
                sources=sources,
                notice=LOW_RELEVANCE_NOTICE,
                diagnostics=diagnostics,
            )

        if self._llm is None:
            return AnswerOutcome(
                status="retrieval_only", answer=None, citations=[], sources=sources, notice=RETRIEVAL_ONLY_NOTICE, diagnostics=diagnostics
            )

        try:
            with timed() as t:
                result = self._llm.generate_answer(question, sources, history)
        except LLMProviderError as exc:
            diagnostics["generation_error"] = exc.message
            return AnswerOutcome(
                status="generation_unavailable", answer=None, citations=[], sources=sources, notice=exc.message, diagnostics=diagnostics
            )

        validated = validate_answer(result.answer, sources)
        diagnostics.update(
            {
                "llm_called": True,
                "generation_ms": t["ms"],
                "model_status": result.answer.status,
                "rejected_citation_ids": validated.rejected_citation_ids,
                "downgraded": validated.downgraded,
                "downgrade_reason": validated.downgrade_reason,
                "citation_coverage": validated.citation_coverage,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
            }
        )
        log_event(
            logger,
            "answer_generated",
            status=validated.status,
            citations=len(validated.citations),
            rejected=len(validated.rejected_citation_ids),
            ms=t["ms"],
        )
        return AnswerOutcome(
            status=validated.status,
            answer=validated.answer,
            citations=validated.citations,
            sources=sources,
            unsupported_aspects=validated.unsupported_aspects,
            model=result.model,
            diagnostics=diagnostics,
        )
