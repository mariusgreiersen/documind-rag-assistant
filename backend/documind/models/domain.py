"""Internal domain objects passed between pipeline stages.

These are plain dataclasses (not API schemas) so that every stage can be tested
without FastAPI. Source metadata (document, page, character span) travels with
the text from extraction to the final citation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class PageText:
    """Cleaned text of one PDF page. ``page_number`` is the 1-based physical page index."""

    page_number: int
    text: str


@dataclass(frozen=True)
class ExtractedPdf:
    page_count: int
    pages: list[PageText]
    metadata_title: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def text_page_count(self) -> int:
        return sum(1 for p in self.pages if p.text)


@dataclass(frozen=True)
class Chunk:
    """A passage of a single page. ``text == page_text[char_start:char_end]`` always holds."""

    chunk_id: str
    document_id: str
    page_number: int
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    token_count: int
    content_hash: str


@dataclass(frozen=True)
class ScoredChunk:
    """A retrieved chunk with its trusted source metadata.

    ``distance`` is Chroma's cosine distance (1 - cosine similarity) and ``score``
    is the cosine similarity itself. Neither is a probability of relevance.
    """

    chunk_id: str
    document_id: str
    filename: str
    title: str
    page_number: int
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    distance: float

    @property
    def score(self) -> float:
        return round(1.0 - self.distance, 4)


@dataclass
class DocumentRecord:
    id: str
    filename: str
    title: str
    sha256: str
    size_bytes: int
    page_count: int
    status: DocumentStatus
    created_at: str
    stored_name: str
    chunk_count: int = 0
    text_page_count: int = 0
    error: str | None = None
    is_demo: bool = False
    embedding_model: str | None = None
    chunk_size_tokens: int | None = None
    chunk_overlap_tokens: int | None = None
    indexed_at: str | None = None
    pipeline_version: str | None = None
