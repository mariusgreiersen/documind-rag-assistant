"""Retrieval and answer metrics.

Definitions (K is the cut-off; "relevant" is defined in :func:`matched_evidence`):

* **Hit@K** (a.k.a. Recall@K, any-relevant): 1 if at least one relevant chunk is
  in the top K, else 0, averaged over answerable questions.
* **Evidence recall@K** (Recall@K, all-evidence): the fraction of a question's
  evidence items that are covered by at least one top-K chunk, averaged. A
  question with two required passages scores 0.5 if only one is retrieved.
* **Precision@K**: relevant chunks in the top K divided by K, averaged. Most
  questions have only one or two relevant chunks, so the attainable maximum is
  well below 1.0 for K >= 3; compare configurations, not absolute values.
* **MRR@K**: mean of 1/rank of the first relevant chunk (0 if none in top K).
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import mean

from documind.evaluation.dataset import EvidenceSpan


def overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def matched_evidence(
    chunk_document_id: str,
    chunk_page: int,
    chunk_start: int,
    chunk_end: int,
    evidence: Sequence[EvidenceSpan],
    min_fraction: float = 0.5,
) -> set[int]:
    """Indices of evidence items this chunk covers.

    A chunk covers an evidence item when it is on the same document and page and
    contains at least ``min_fraction`` of the evidence's characters.
    """
    hits = set()
    for ev in evidence:
        if ev.document_id != chunk_document_id or ev.page != chunk_page:
            continue
        length = ev.end - ev.start
        if length and overlap(chunk_start, chunk_end, ev.start, ev.end) / length >= min_fraction:
            hits.add(ev.index)
    return hits


def hit_at_k(relevant: Sequence[bool], k: int) -> float:
    return 1.0 if any(relevant[:k]) else 0.0


def precision_at_k(relevant: Sequence[bool], k: int) -> float:
    return sum(relevant[:k]) / k


def reciprocal_rank(relevant: Sequence[bool], k: int | None = None) -> float:
    for rank, is_relevant in enumerate(relevant[: k or len(relevant)], start=1):
        if is_relevant:
            return 1.0 / rank
    return 0.0


def evidence_recall_at_k(matches: Sequence[set[int]], n_evidence: int, k: int) -> float:
    if n_evidence == 0:
        raise ValueError("evidence recall is undefined without evidence")
    covered: set[int] = set().union(*matches[:k]) if matches[:k] else set()
    return len(covered) / n_evidence


def safe_mean(values: Sequence[float]) -> float | None:
    return round(mean(values), 4) if values else None


def contains_any(text: str, alternatives: str) -> bool:
    """``alternatives`` is ``"a|b"``: true if any alternative occurs (case-insensitive)."""
    lowered = text.lower()
    return any(alt.strip().lower() in lowered for alt in alternatives.split("|") if alt.strip())


def key_fact_recall(answer: str, key_facts: Sequence[str]) -> float | None:
    """Heuristic: share of expected key terms present in the answer text."""
    if not key_facts:
        return None
    return sum(contains_any(answer, fact) for fact in key_facts) / len(key_facts)
