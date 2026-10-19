from documind.generation.citation_validator import RawAnswer, sentence_citation_coverage, validate_answer
from documind.generation.prompts import INSUFFICIENT_EVIDENCE_MESSAGE, label_sources
from documind.models.domain import ScoredChunk


def chunk(i: int, page: int = 1, doc: str = "doc-a") -> ScoredChunk:
    return ScoredChunk(
        chunk_id=f"{doc}:p{page}:c{i}",
        document_id=doc,
        filename=f"{doc}.pdf",
        title=f"Title {doc}",
        page_number=page,
        chunk_index=i,
        text=f"Passage {i} text.",
        char_start=0,
        char_end=16,
        distance=0.3,
    )


SOURCES = label_sources([chunk(0, 2), chunk(1, 5), chunk(2, 7, "doc-b")])  # S1, S2, S3


def test_valid_markers_are_renumbered_in_order_of_first_use():
    raw = RawAnswer("answered", "Leaders replicate entries [S3]. Majorities overlap [S1]. Again [S3].", ["S3", "S1"])
    result = validate_answer(raw, SOURCES)
    assert result.answer == "Leaders replicate entries [1]. Majorities overlap [2]. Again [1]."
    assert [(c.number, c.source.ref_id) for c in result.citations] == [(1, "S3"), (2, "S1")]
    assert result.status == "answered"
    assert result.rejected_citation_ids == []


def test_citation_metadata_comes_from_the_backend_not_the_model():
    raw = RawAnswer("answered", "A claim [S2] (see Imaginary Book, page 99).", ["S2"])
    cit = validate_answer(raw, SOURCES).citations[0]
    assert (cit.source.chunk.document_id, cit.source.chunk.page_number, cit.source.chunk.title) == ("doc-a", 5, "Title doc-a")


def test_unknown_markers_are_removed_and_reported():
    raw = RawAnswer("answered", "Supported claim [S1]. Fabricated claim [S9].", ["S1", "S9", "S42"])
    result = validate_answer(raw, SOURCES)
    assert result.answer == "Supported claim [1]. Fabricated claim."
    assert result.rejected_citation_ids == ["S9", "S42"]
    assert len(result.citations) == 1


def test_grouped_and_lowercase_markers():
    raw = RawAnswer("answered", "Both say so [S1, s3; S7].", [])
    result = validate_answer(raw, SOURCES)
    assert result.answer == "Both say so [1][2]."
    assert result.rejected_citation_ids == ["S7"]


def test_answer_without_any_valid_citation_is_downgraded():
    raw = RawAnswer("answered", "Northwind's 2028 revenue was DKK 1 billion [S99].", ["S99"])
    result = validate_answer(raw, SOURCES)
    assert result.status == "insufficient_evidence"
    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert result.downgraded and result.downgrade_reason == "no_valid_citations"
    assert result.citations == []


def test_uncited_answer_is_downgraded_even_without_markers():
    result = validate_answer(RawAnswer("answered", "A confident answer with no sources.", []), SOURCES)
    assert result.status == "insufficient_evidence"


def test_listed_sources_without_inline_markers_are_attached_not_dropped():
    raw = RawAnswer("answered", "The documents agree on this point.", ["S2"])
    result = validate_answer(raw, SOURCES)
    assert result.answer == "The documents agree on this point. [1]"
    assert result.citations[0].source.ref_id == "S2"


def test_insufficient_evidence_keeps_model_explanation():
    raw = RawAnswer("insufficient_evidence", "The documents cover 2024 and 2025 only.", [])
    result = validate_answer(raw, SOURCES)
    assert result.status == "insufficient_evidence"
    assert result.answer == "The documents cover 2024 and 2025 only."
    assert not result.downgraded


def test_empty_insufficient_answer_gets_standard_message():
    assert validate_answer(RawAnswer("insufficient_evidence", "", []), SOURCES).answer == INSUFFICIENT_EVIDENCE_MESSAGE


def test_partial_answer_keeps_unsupported_aspects():
    raw = RawAnswer("partially_answered", "Revenue in 2025 was 48.2 million [S1].", ["S1"], ["2028 revenue", " "])
    result = validate_answer(raw, SOURCES)
    assert result.status == "partially_answered"
    assert result.unsupported_aspects == ["2028 revenue"]


def test_unknown_status_is_treated_as_answered_and_still_validated():
    result = validate_answer(RawAnswer("definitely_true", "Claim [S1].", ["S1"]), SOURCES)
    assert result.status == "answered"


def test_citation_coverage_heuristic():
    assert sentence_citation_coverage("First sentence is cited here [1]. Second sentence is not cited at all.") == 0.5
    assert sentence_citation_coverage("") == 0.0
