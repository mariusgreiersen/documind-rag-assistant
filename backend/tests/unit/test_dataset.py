"""The version-controlled benchmark must stay valid: these tests run in CI without a model."""

from collections import Counter

import pytest
from pydantic import ValidationError

from documind.core.config import REPO_ROOT, Settings
from documind.evaluation.dataset import DEFAULT_DATASET, EvalCase, find_spans, load_cases, locate_evidence
from documind.evaluation.harness import demo_page_texts


@pytest.fixture(scope="module")
def cases():
    return load_cases(DEFAULT_DATASET)


def test_benchmark_size_and_coverage(cases):
    assert len(cases) >= 20
    categories = Counter(c.category for c in cases)
    for required in ("direct", "multi_passage", "multi_document", "paraphrase", "noisy"):
        assert categories[required] >= 2, required
    assert sum(not c.answerable for c in cases) >= 5
    assert len({c.id for c in cases}) == len(cases)


def test_every_evidence_item_is_found_exactly_once_on_its_page(cases):
    settings = Settings(_env_file=None, demo_dir=REPO_ROOT / "data" / "demo")
    located = locate_evidence(cases, demo_page_texts(settings))
    assert sum(len(v) for v in located.values()) == sum(len(c.evidence) for c in cases)


def test_multi_document_cases_really_span_documents(cases):
    for case in cases:
        if case.category in {"multi_document", "conflicting"}:
            assert len({e.document_id for e in case.evidence}) >= 2, case.id


def test_wrong_page_is_reported():
    case = EvalCase.model_validate(
        {
            "id": "x",
            "question": "What?",
            "answerable": True,
            "category": "direct",
            "evidence": [{"document_id": "d", "page": 2, "text": "some evidence text"}],
            "reference_answer": "r",
        }
    )
    with pytest.raises(ValueError, match="found 0 times"):
        locate_evidence([case], {("d", 1): "some evidence text", ("d", 2): "different text"})


def test_answerability_and_evidence_must_agree():
    with pytest.raises(ValidationError):
        EvalCase.model_validate({"id": "x", "question": "What?", "answerable": True, "category": "c", "reference_answer": "r"})


def test_find_spans_ignores_whitespace_differences():
    page = "alpha beta\ngamma   delta\nepsilon"
    spans = find_spans(page, "beta gamma delta")
    assert spans == [(6, 24)]
    assert page[6:24] == "beta\ngamma   delta"
    assert find_spans(page, "not present") == []
