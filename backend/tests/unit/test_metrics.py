import pytest

from documind.evaluation.dataset import EvidenceSpan
from documind.evaluation.metrics import (
    contains_any,
    evidence_recall_at_k,
    hit_at_k,
    key_fact_recall,
    matched_evidence,
    overlap,
    precision_at_k,
    reciprocal_rank,
)

REL = [False, True, False, True, False]


def test_hit_at_k():
    assert hit_at_k(REL, 1) == 0.0
    assert hit_at_k(REL, 2) == 1.0
    assert hit_at_k([False] * 5, 5) == 0.0


def test_precision_at_k_divides_by_k():
    assert precision_at_k(REL, 1) == 0.0
    assert precision_at_k(REL, 2) == 0.5
    assert precision_at_k(REL, 5) == 0.4
    # Fewer results than K still divides by K: missing results count as not relevant.
    assert precision_at_k([True], 5) == 0.2


def test_reciprocal_rank():
    assert reciprocal_rank(REL) == 0.5
    assert reciprocal_rank([True]) == 1.0
    assert reciprocal_rank([False, False, False, True], k=3) == 0.0
    assert reciprocal_rank([]) == 0.0


def test_evidence_recall_counts_distinct_evidence_items():
    matches = [set(), {0}, {0}, {1}]
    assert evidence_recall_at_k(matches, 2, 1) == 0.0
    assert evidence_recall_at_k(matches, 2, 3) == 0.5
    assert evidence_recall_at_k(matches, 2, 4) == 1.0
    with pytest.raises(ValueError):
        evidence_recall_at_k(matches, 0, 3)


def test_overlap():
    assert overlap(0, 10, 5, 20) == 5
    assert overlap(0, 10, 10, 20) == 0


def test_chunk_relevance_requires_same_document_page_and_half_the_evidence():
    ev = [EvidenceSpan("q", 0, "doc", 3, 100, 200)]
    assert matched_evidence("doc", 3, 0, 1000, ev) == {0}  # contains it
    assert matched_evidence("doc", 3, 150, 400, ev) == {0}  # exactly half
    assert matched_evidence("doc", 3, 160, 400, ev) == set()  # less than half
    assert matched_evidence("doc", 2, 0, 1000, ev) == set()  # other page
    assert matched_evidence("other", 3, 0, 1000, ev) == set()  # other document


def test_key_fact_recall_supports_alternatives():
    assert key_fact_recall("It uses MVCC and snapshots.", ["multiversion|mvcc", "snapshot"]) == 1.0
    assert key_fact_recall("Nothing relevant.", ["majority"]) == 0.0
    assert key_fact_recall("anything", []) is None
    assert contains_any("Two failures", "two|2")
