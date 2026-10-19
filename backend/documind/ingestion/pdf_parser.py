"""PDF validation and per-page text extraction with pypdf.

Validation happens on the raw bytes before anything is written to disk:
signature, structure, encryption, page count and the presence of extractable
text. Page numbers are 1-based physical page indices (PDF page labels such as
"iv" are not used).
"""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from documind.core.errors import CorruptedPdf, EmptyFile, EncryptedPdf, FileTooLarge, NoExtractableText, TooManyPages, UnsupportedFileType
from documind.core.logging import log_event
from documind.ingestion.cleaner import normalize_page_text, remove_repeated_lines
from documind.models.domain import ExtractedPdf, PageText

logger = logging.getLogger(__name__)

PDF_SIGNATURE = b"%PDF-"


def check_signature(data: bytes) -> None:
    """Reject files that are not PDFs, regardless of their name or declared content type.

    The PDF specification allows the header to appear within the first 1024 bytes.
    """
    if not data:
        raise EmptyFile()
    if PDF_SIGNATURE not in data[:1024]:
        raise UnsupportedFileType("Only PDF files are supported. This file does not look like a PDF.")


def extract_pdf(
    data: bytes,
    *,
    max_bytes: int,
    max_pages: int,
    min_chars_per_page: int = 20,
    min_text_page_ratio: float = 0.5,
) -> ExtractedPdf:
    if len(data) > max_bytes:
        raise FileTooLarge(f"The file is larger than the {max_bytes / 1024 / 1024:.0f} MB limit.")
    check_signature(data)

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            # Some PDFs are encrypted only to restrict permissions and open with an
            # empty user password. Anything else needs a password we do not have.
            try:
                opened = reader.decrypt("")
            except Exception as exc:  # pypdf raises several types here (incl. missing crypto deps)
                raise EncryptedPdf() from exc
            if not opened:
                raise EncryptedPdf()
        page_count = len(reader.pages)
    except EncryptedPdf:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        log_event(logger, "pdf_open_failed", logging.WARNING, error=type(exc).__name__)
        raise CorruptedPdf() from exc

    if page_count == 0:
        raise CorruptedPdf("This PDF has no pages.")
    if page_count > max_pages:
        raise TooManyPages(f"This PDF has {page_count} pages. The limit is {max_pages} pages per document.")

    texts: list[str] = []
    warnings: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # a single broken page should not fail the whole document
            warnings.append(f"page {index + 1}: text extraction failed ({type(exc).__name__})")
            raw = ""
        texts.append(normalize_page_text(raw))
    texts = remove_repeated_lines(texts)
    pages = [PageText(page_number=i + 1, text=text if len(text) >= min_chars_per_page else "") for i, text in enumerate(texts)]

    text_pages = sum(1 for p in pages if p.text)
    if text_pages == 0:
        raise NoExtractableText()
    if text_pages / page_count < min_text_page_ratio:
        raise NoExtractableText(
            f"Only {text_pages} of {page_count} pages contain extractable text. This PDF appears to contain "
            "scanned pages. OCR is not supported in the current version."
        )

    return ExtractedPdf(page_count=page_count, pages=pages, metadata_title=_metadata_title(reader), warnings=warnings)


def _metadata_title(reader: PdfReader) -> str | None:
    try:
        title = reader.metadata.title if reader.metadata else None
    except Exception:
        return None
    if not title:
        return None
    title = " ".join(str(title).split())
    # Ignore placeholder titles that many PDF producers write.
    if len(title) < 3 or title.lower() in {"untitled", "microsoft word", "document"} or title.lower().endswith((".doc", ".docx", ".pdf")):
        return None
    return title[:200]
