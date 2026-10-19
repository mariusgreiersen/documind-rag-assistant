from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from documind.container import Container
from documind.models.domain import DocumentRecord, ScoredChunk
from documind.models.schemas import DocumentOut, SearchResult, WorkspaceLimits


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def document_out(record: DocumentRecord) -> DocumentOut:
    return DocumentOut(
        id=record.id,
        filename=record.filename,
        title=record.title,
        size_bytes=record.size_bytes,
        page_count=record.page_count,
        text_page_count=record.text_page_count,
        chunk_count=record.chunk_count,
        status=record.status.value,
        error=record.error,
        created_at=record.created_at,
        indexed_at=record.indexed_at,
        is_demo=record.is_demo,
        sha256=record.sha256,
        embedding_model=record.embedding_model,
        chunk_size_tokens=record.chunk_size_tokens,
        chunk_overlap_tokens=record.chunk_overlap_tokens,
    )


def search_result(chunk: ScoredChunk, rank: int) -> SearchResult:
    return SearchResult(
        rank=rank,
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        filename=chunk.filename,
        title=chunk.title,
        page=chunk.page_number,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        score=chunk.score,
        distance=round(chunk.distance, 4),
        char_start=chunk.char_start,
        char_end=chunk.char_end,
    )


def limits(container: Container) -> WorkspaceLimits:
    s = container.settings
    return WorkspaceLimits(max_documents=s.max_documents, max_upload_mb=s.max_upload_mb, max_pages=s.max_pages)
