"""Evaluation harness shared by ``run`` (baseline) and ``experiments``.

Every evaluation builds an isolated, temporary workspace (its own SQLite file
and Chroma directory), indexes the bundled demo corpus through the production
``DocumentService``, and queries it through the production ``Retriever`` and
``AnswerService``. The user's workspace is never touched.
"""

from __future__ import annotations

import platform
import tempfile
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from documind.container import Container, build_container
from documind.core.config import Settings
from documind.evaluation.dataset import EvalCase, EvidenceSpan, locate_evidence
from documind.evaluation.metrics import (
    contains_any,
    evidence_recall_at_k,
    hit_at_k,
    key_fact_recall,
    matched_evidence,
    precision_at_k,
    reciprocal_rank,
    safe_mean,
)
from documind.generation.llm_provider import LLMProvider
from documind.ingestion.pdf_parser import extract_pdf

KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class RetrievalConfig:
    name: str
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    query_prefix: str = "Represent this sentence for searching relevant passages: "
    chunk_size: int = 500
    chunk_overlap: int = 60
    min_chunk_tokens: int = 24

    @classmethod
    def from_settings(cls, s: Settings, name: str = "configured") -> RetrievalConfig:
        return cls(name, s.embedding_model, s.embedding_query_prefix or "", s.chunk_size_tokens, s.chunk_overlap_tokens, s.min_chunk_tokens)


def environment_info() -> dict[str, str]:
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(terse=True),
        "processor": platform.processor() or platform.machine(),
        "sentence_transformers": version("sentence-transformers"),
        "chromadb": version("chromadb"),
        "torch": version("torch"),
    }


@contextmanager
def eval_workspace(
    cfg: RetrievalConfig,
    base: Settings,
    *,
    llm: LLMProvider | None = None,
) -> Iterator[tuple[Container, float]]:
    """Index the demo corpus into a throwaway workspace; yields (container, ingest_seconds)."""
    with tempfile.TemporaryDirectory(prefix="documind-eval-", ignore_cleanup_errors=True) as tmp:
        settings = base.model_copy(
            update={
                "data_dir": Path(tmp),
                "chroma_persist_dir": Path(tmp) / "chroma",
                "embedding_model": cfg.embedding_model,
                "embedding_query_prefix": cfg.query_prefix,
                "chunk_size_tokens": cfg.chunk_size,
                "chunk_overlap_tokens": cfg.chunk_overlap,
                "min_chunk_tokens": cfg.min_chunk_tokens,
                "read_only": False,
                "max_documents": 50,
            }
        )
        container = build_container(settings, llm=llm)
        try:
            container.embedder.dimension  # noqa: B018 - load the model before timing ingestion
            started = time.perf_counter()
            container.documents.seed_demo()
            ingest_seconds = time.perf_counter() - started
            yield container, ingest_seconds
        finally:
            container.close()


def demo_page_texts(settings: Settings) -> dict[tuple[str, int], str]:
    """Extracted page text of every demo document, keyed by (document_id, page)."""
    import json

    manifest = json.loads((settings.demo_dir / "manifest.json").read_text(encoding="utf-8"))
    texts: dict[tuple[str, int], str] = {}
    for entry in manifest["documents"]:
        data = (settings.demo_dir / entry["filename"]).read_bytes()
        extracted = extract_pdf(data, max_bytes=50 * 1024 * 1024, max_pages=500)
        for page in extracted.pages:
            texts[(entry["id"], page.page_number)] = page.text
    return texts


# --- retrieval -------------------------------------------------------------------
@dataclass
class RetrievalRow:
    case_id: str
    category: str
    answerable: bool
    top_score: float | None
    relevant: list[bool]
    evidence_matches: list[list[int]]
    n_evidence: int
    retrieved: list[dict[str, Any]] = field(default_factory=list)


def evaluate_retrieval(
    container: Container, cases: Sequence[EvalCase], spans: dict[str, list[EvidenceSpan]], k_max: int = 10
) -> list[RetrievalRow]:
    scope = container.documents.search_scope(None)
    rows = []
    for case in cases:
        result = container.retriever.search(case.question, document_ids=scope, top_k=k_max)
        matches = [matched_evidence(c.document_id, c.page_number, c.char_start, c.char_end, spans.get(case.id, [])) for c in result.chunks]
        rows.append(
            RetrievalRow(
                case_id=case.id,
                category=case.category,
                answerable=case.answerable,
                top_score=result.top_score,
                relevant=[bool(m) for m in matches],
                evidence_matches=[sorted(m) for m in matches],
                n_evidence=len(case.evidence),
                retrieved=[{"chunk_id": c.chunk_id, "page": c.page_number, "score": c.score} for c in result.chunks],
            )
        )
    return rows


def random_baseline(
    container: Container, cases: Sequence[EvalCase], spans: dict[str, list[EvidenceSpan]], ks: Sequence[int] = KS
) -> dict[str, Any]:
    """Expected Hit@K if chunks were ranked uniformly at random.

    With N chunks of which r are relevant, P(hit within K) = 1 - C(N-r, K) / C(N, K).
    Small corpora make high Hit@K easy, so measured values should be read against this.
    """
    from math import comb

    chunks = [ch for doc_id in container.documents.search_scope(None) for ch in container.store.get_document_chunks(doc_id)]
    n = len(chunks)
    out: dict[str, Any] = {"corpus_chunks": n}
    answerable = [c for c in cases if c.answerable]
    relevant_counts = [
        sum(bool(matched_evidence(ch.document_id, ch.page_number, ch.char_start, ch.char_end, spans.get(c.id, []))) for ch in chunks)
        for c in answerable
    ]
    for k in ks:
        kk = min(k, n)
        out[f"random_hit@{k}"] = safe_mean([1 - comb(n - r, kk) / comb(n, kk) for r in relevant_counts])
    return out


def recall_at_token_budget(rows: Sequence[RetrievalRow], chunk_size: int, budget_tokens: int = 2500) -> tuple[int, float | None]:
    """Evidence recall when retrieving ~``budget_tokens`` of passages, so configurations with
    different chunk sizes are compared at the same amount of context given to the LLM."""
    k = max(1, round(budget_tokens / chunk_size))
    answerable = [r for r in rows if r.answerable]
    return k, safe_mean([evidence_recall_at_k([set(m) for m in r.evidence_matches], r.n_evidence, k) for r in answerable])


def summarize_retrieval(rows: Sequence[RetrievalRow], ks: Sequence[int] = KS) -> dict[str, Any]:
    answerable = [r for r in rows if r.answerable]
    summary: dict[str, Any] = {"questions_total": len(rows), "questions_answerable": len(answerable)}
    for k in ks:
        summary[f"hit@{k}"] = safe_mean([hit_at_k(r.relevant, k) for r in answerable])
        summary[f"evidence_recall@{k}"] = safe_mean(
            [evidence_recall_at_k([set(m) for m in r.evidence_matches], r.n_evidence, k) for r in answerable]
        )
        summary[f"precision@{k}"] = safe_mean([precision_at_k(r.relevant, k) for r in answerable])
    summary["full_coverage@5"] = safe_mean(
        [1.0 if evidence_recall_at_k([set(m) for m in r.evidence_matches], r.n_evidence, 5) == 1.0 else 0.0 for r in answerable]
    )
    summary["mrr@10"] = safe_mean([reciprocal_rank(r.relevant, 10) for r in answerable])

    by_category: dict[str, list[RetrievalRow]] = defaultdict(list)
    for r in answerable:
        by_category[r.category].append(r)
    summary["by_category"] = {
        cat: {
            "n": len(rs),
            "hit@5": safe_mean([hit_at_k(r.relevant, 5) for r in rs]),
            "evidence_recall@5": safe_mean([evidence_recall_at_k([set(m) for m in r.evidence_matches], r.n_evidence, 5) for r in rs]),
            "mrr@10": safe_mean([reciprocal_rank(r.relevant, 10) for r in rs]),
        }
        for cat, rs in sorted(by_category.items())
    }
    return summary


def gate_sweep(rows: Sequence[RetrievalRow], thresholds: Sequence[float]) -> list[dict[str, Any]]:
    """Answerability decided by the relevance gate alone (top-1 cosine >= threshold)."""
    out = []
    for t in thresholds:
        passed_answerable = [r for r in rows if r.answerable and (r.top_score or 0) >= t]
        rejected_unanswerable = [r for r in rows if not r.answerable and (r.top_score or 0) < t]
        n_ans = sum(r.answerable for r in rows)
        n_un = len(rows) - n_ans
        out.append(
            {
                "threshold": round(t, 2),
                "answerable_passed": f"{len(passed_answerable)}/{n_ans}",
                "unanswerable_rejected": f"{len(rejected_unanswerable)}/{n_un}",
                "accuracy": round((len(passed_answerable) + len(rejected_unanswerable)) / len(rows), 4),
            }
        )
    return out


# --- answers ---------------------------------------------------------------------
@dataclass
class AnswerRow:
    case_id: str
    category: str
    answerable: bool
    status: str
    answer: str | None
    citations: list[dict[str, Any]]
    rejected_citation_ids: list[str]
    citation_valid: int
    citation_relevant: int
    key_fact_recall: float | None
    forbidden_hit: list[str]
    llm_called: bool
    generation_ms: float | None


def evaluate_answers(container: Container, cases: Sequence[EvalCase], spans: dict[str, list[EvidenceSpan]]) -> list[AnswerRow]:
    rows = []
    for case in cases:
        outcome = container.answers.answer(case.question)
        relevant = 0
        cits = []
        for cit in outcome.citations:
            ch = cit.source.chunk
            is_rel = bool(matched_evidence(ch.document_id, ch.page_number, ch.char_start, ch.char_end, spans.get(case.id, [])))
            relevant += is_rel
            cits.append({"n": cit.number, "chunk_id": ch.chunk_id, "title": ch.title, "page": ch.page_number, "relevant": is_rel})
        answer = outcome.answer or ""
        rows.append(
            AnswerRow(
                case_id=case.id,
                category=case.category,
                answerable=case.answerable,
                status=outcome.status,
                answer=outcome.answer,
                citations=cits,
                rejected_citation_ids=list(outcome.diagnostics.get("rejected_citation_ids", [])),
                citation_valid=len(outcome.citations),
                citation_relevant=relevant,
                key_fact_recall=key_fact_recall(answer, case.key_facts) if case.answerable else None,
                forbidden_hit=[p for p in case.forbidden_phrases if contains_any(answer, p)],
                llm_called=bool(outcome.diagnostics.get("llm_called")),
                generation_ms=outcome.diagnostics.get("generation_ms"),
            )
        )
    return rows


def summarize_answers(rows: Sequence[AnswerRow]) -> dict[str, Any]:
    answerable = [r for r in rows if r.answerable]
    unanswerable = [r for r in rows if not r.answerable]
    answered_statuses = {"answered", "partially_answered"}
    valid = sum(r.citation_valid for r in rows)
    rejected = sum(len(r.rejected_citation_ids) for r in rows)
    cited_rows = [r for r in answerable if r.citation_valid]
    return {
        "questions_total": len(rows),
        "answerable_answered": f"{sum(r.status in answered_statuses for r in answerable)}/{len(answerable)}",
        "unanswerable_declined": f"{sum(r.status == 'insufficient_evidence' for r in unanswerable)}/{len(unanswerable)}",
        "answerability_accuracy": safe_mean(
            [
                1.0 if (r.status in answered_statuses) == r.answerable else 0.0
                for r in rows
                if r.status not in {"generation_unavailable", "retrieval_only"}
            ]
        ),
        "citation_validity_rate": round(valid / (valid + rejected), 4) if valid + rejected else None,
        "citations_valid": valid,
        "citations_rejected": rejected,
        "cited_evidence_precision": round(sum(r.citation_relevant for r in cited_rows) / sum(r.citation_valid for r in cited_rows), 4)
        if cited_rows
        else None,
        "answers_with_relevant_citation": f"{sum(r.citation_relevant > 0 for r in answerable)}/{len(answerable)}",
        "key_fact_recall_heuristic": safe_mean([r.key_fact_recall for r in answerable if r.key_fact_recall is not None]),
        "forbidden_phrase_violations": sum(bool(r.forbidden_hit) for r in rows),
        "generation_errors": sum(r.status == "generation_unavailable" for r in rows),
    }


def as_dicts(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]


def locate(cases: Sequence[EvalCase], settings: Settings) -> dict[str, list[EvidenceSpan]]:
    return locate_evidence(cases, demo_page_texts(settings))
