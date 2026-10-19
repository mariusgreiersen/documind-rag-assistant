import pytest

from documind.core.errors import CorruptedPdf, EmptyFile, EncryptedPdf, FileTooLarge, NoExtractableText, TooManyPages, UnsupportedFileType
from documind.ingestion.pdf_parser import extract_pdf
from tests.conftest import encrypt_pdf, make_image_only_pdf, make_pdf

LIMITS = {"max_bytes": 5 * 1024 * 1024, "max_pages": 10}


def test_extracts_text_per_page_with_one_based_page_numbers(sample_pdf):
    result = extract_pdf(sample_pdf, **LIMITS)
    assert result.page_count == 3
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert "majority of servers" in result.pages[0].text
    assert "Cache-aside" in result.pages[1].text
    assert "two-phase locking" in result.pages[2].text
    assert result.metadata_title == "Systems Notes"


def test_text_file_renamed_to_pdf_is_rejected_by_content():
    with pytest.raises(UnsupportedFileType):
        extract_pdf(b"This is plain text pretending to be a PDF.", **LIMITS)


def test_executable_content_is_rejected():
    with pytest.raises(UnsupportedFileType):
        extract_pdf(b"MZ\x90\x00" + b"\x00" * 100, **LIMITS)


def test_empty_file():
    with pytest.raises(EmptyFile):
        extract_pdf(b"", **LIMITS)


def test_oversized_file():
    data = make_pdf(["small"])
    with pytest.raises(FileTooLarge):
        extract_pdf(data, max_bytes=len(data) - 1, max_pages=10)


def test_corrupted_pdf():
    with pytest.raises(CorruptedPdf):
        extract_pdf(b"%PDF-1.7\n" + b"\x00garbage" * 50, **LIMITS)


def test_truncated_pdf_is_rejected_or_partially_read(sample_pdf):
    """A PDF cut in half must never be indexed silently as if it were complete."""
    with pytest.raises((CorruptedPdf, NoExtractableText)):
        extract_pdf(sample_pdf[: len(sample_pdf) // 3], **LIMITS)


def test_password_protected_pdf(sample_pdf):
    with pytest.raises(EncryptedPdf):
        extract_pdf(encrypt_pdf(sample_pdf, "hunter2"), **LIMITS)


def test_encrypted_pdf_with_empty_user_password_is_readable(sample_pdf):
    result = extract_pdf(encrypt_pdf(sample_pdf, ""), **LIMITS)
    assert result.page_count == 3
    assert "Raft" in result.pages[0].text


def test_scanned_pdf_without_text_is_rejected_with_ocr_message():
    with pytest.raises(NoExtractableText) as exc:
        extract_pdf(make_image_only_pdf(), **LIMITS)
    assert "OCR is not supported" in exc.value.message


def test_mostly_scanned_pdf_is_rejected():
    data = make_pdf(["Real text on the first page only, long enough to count as text.", "", "", ""])
    with pytest.raises(NoExtractableText):
        extract_pdf(data, **LIMITS)


def test_page_limit():
    data = make_pdf([f"Page {i} has enough words to be considered real text." for i in range(4)])
    with pytest.raises(TooManyPages):
        extract_pdf(data, max_bytes=LIMITS["max_bytes"], max_pages=3)


def test_blank_pages_keep_their_position(sample_pdf):
    data = make_pdf(["First page with plenty of extractable words.", "", "Third page with plenty of extractable words."])
    result = extract_pdf(data, **LIMITS)
    assert [bool(p.text) for p in result.pages] == [True, False, True]
    assert result.pages[2].page_number == 3


def test_placeholder_metadata_title_is_ignored():
    data = make_pdf(["Some words that are long enough to be text."], title="Microsoft Word - draft.docx")
    assert extract_pdf(data, **LIMITS).metadata_title is None
