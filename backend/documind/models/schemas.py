"""Request and response schemas for the public REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AnswerStatus = Literal["answered", "partially_answered", "insufficient_evidence", "retrieval_only", "generation_unavailable"]


class ErrorBody(BaseModel):
    code: str = Field(examples=["pdf_encrypted"])
    message: str = Field(examples=["This PDF is password-protected. Remove the password and upload it again."])
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- Documents -----------------------------------------------------------------
class DocumentOut(BaseModel):
    id: str
    filename: str
    title: str
    file_type: Literal["pdf"] = "pdf"
    size_bytes: int
    page_count: int
    text_page_count: int
    chunk_count: int
    status: Literal["processing", "ready", "failed"]
    error: str | None = None
    created_at: str
    indexed_at: str | None = None
    is_demo: bool = False
    sha256: str
    embedding_model: str | None = None
    chunk_size_tokens: int | None = None
    chunk_overlap_tokens: int | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "doc_3f9c1a2b4d5e6f70",
                "filename": "raft-consensus-lecture-notes.pdf",
                "title": "Raft Consensus: Lecture Notes on Leader Election and Log Replication",
                "file_type": "pdf",
                "size_bytes": 10817,
                "page_count": 5,
                "text_page_count": 5,
                "chunk_count": 14,
                "status": "ready",
                "created_at": "2026-10-19T20:15:00+00:00",
                "sha256": "9f2e53856e47…",
            }
        }
    )


class WorkspaceLimits(BaseModel):
    max_documents: int
    max_upload_mb: float
    max_pages: int


class DocumentListOut(BaseModel):
    documents: list[DocumentOut]
    limits: WorkspaceLimits


class ChunkOut(BaseModel):
    chunk_id: str
    document_id: str
    page: int
    chunk_index: int
    text: str
    char_start: int
    char_end: int


class DocumentChunksOut(BaseModel):
    document_id: str
    embedding_model: str | None
    chunks: list[ChunkOut]


class DeleteResponse(BaseModel):
    deleted: str


# --- Search --------------------------------------------------------------------
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000, examples=["What are the main findings?"])
    document_ids: list[str] | None = Field(
        default=None, max_length=50, description="Restrict the search to these documents. Omit to search all ready documents."
    )
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    filename: str
    title: str
    page: int = Field(description="1-based physical PDF page number")
    chunk_index: int
    text: str
    score: float = Field(description="Cosine similarity between query and passage embeddings (higher is closer). Not a probability.")
    distance: float = Field(description="Chroma cosine distance = 1 - score.")
    char_start: int
    char_end: int


class SearchResponse(BaseModel):
    query: str
    top_k: int
    score_metric: Literal["cosine_similarity"] = "cosine_similarity"
    embedding_model: str
    took_ms: float
    results: list[SearchResult]


# --- Chat ----------------------------------------------------------------------
class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000, examples=["What are the main findings?"])
    document_ids: list[str] | None = Field(default=None, max_length=50)
    top_k: int = Field(default=5, ge=1, le=10)
    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=20,
        description="Previous turns, used only to interpret follow-up questions. Never treated as evidence.",
    )


class Citation(BaseModel):
    number: int = Field(description="The number shown in the answer text, e.g. [1]")
    ref_id: str = Field(description="Reference ID assigned to the passage before generation (S1, S2, …)")
    chunk_id: str
    document_id: str
    filename: str
    title: str
    page: int
    text: str
    score: float
    char_start: int
    char_end: int


class SourcePassageOut(SearchResult):
    ref_id: str


class ChatResponse(BaseModel):
    status: AnswerStatus
    answer: str | None = Field(description="Markdown answer with [n] citation markers, or null when no answer was generated.")
    citations: list[Citation]
    sources: list[SourcePassageOut] = Field(description="All passages retrieved for the question, in rank order.")
    unsupported_aspects: list[str] = Field(default_factory=list)
    notice: str | None = None
    model: str | None = None
    diagnostics: dict[str, Any] | None = Field(default=None, description="Retrieval diagnostics (only when diagnostics are enabled).")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "answered",
                "answer": "A Raft log entry is committed once the leader has replicated it on a majority of servers [1].",
                "citations": [
                    {
                        "number": 1,
                        "ref_id": "S1",
                        "chunk_id": "demo-raft-consensus:p3:c4",
                        "document_id": "demo-raft-consensus",
                        "filename": "raft-consensus-lecture-notes.pdf",
                        "title": "Raft Consensus: Lecture Notes on Leader Election and Log Replication",
                        "page": 3,
                        "text": "A log entry is committed once the leader that created it has replicated it on a majority of the servers. …",
                        "score": 0.71,
                        "char_start": 512,
                        "char_end": 1630,
                    }
                ],
                "sources": [],
                "unsupported_aspects": [],
                "notice": None,
                "model": "claude-opus-5-5",
            }
        }
    )


# --- System --------------------------------------------------------------------
class HealthOut(BaseModel):
    status: Literal["ok"]
    version: str


class ConfigOut(BaseModel):
    version: str
    llm_configured: bool
    llm_provider: str | None
    llm_model: str | None
    embedding_model: str
    embedding_dimension: int
    max_seq_length: int
    max_input_tokens: int
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    default_top_k: int
    min_relevance_score: float
    score_metric: Literal["cosine_similarity"] = "cosine_similarity"
    read_only: bool
    diagnostics_enabled: bool
    demo_available: bool
    limits: WorkspaceLimits


class DemoLoadResponse(BaseModel):
    loaded: list[DocumentOut]
    documents: list[DocumentOut]
