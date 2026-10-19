from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile, status
from fastapi.responses import FileResponse

from documind.api.deps import ContainerDep, document_out, limits
from documind.core.errors import EmptyFile, FileTooLarge
from documind.models.schemas import (
    ChunkOut,
    DeleteResponse,
    DemoLoadResponse,
    DocumentChunksOut,
    DocumentListOut,
    DocumentOut,
    ErrorResponse,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])

_ERRORS: dict[int | str, dict[str, Any]] = {r: {"model": ErrorResponse} for r in (400, 403, 404, 409, 413, 415, 422)}


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload without ever buffering more than ``max_bytes + 1`` bytes."""
    buffer = bytearray()
    while chunk := await file.read(1024 * 1024):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise FileTooLarge(f"The file is larger than the {max_bytes / 1024 / 1024:.0f} MB limit.")
    if not buffer:
        raise EmptyFile()
    return bytes(buffer)


@router.post(
    "/documents/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ERRORS,
    summary="Upload a PDF",
    description=(
        "Validates the file (PDF signature, structure, encryption, size, page count, extractable text) and stores it. "
        "Chunking, embedding and indexing run in the background; poll `GET /documents/{id}` until `status` is `ready` or `failed`. "
        "A file with the same SHA-256 as an existing document is rejected with 409 unless `replace=true`."
    ),
)
async def upload_document(
    c: ContainerDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="A text-based PDF")],
    replace: Annotated[bool, Query(description="Replace an existing document with identical content")] = False,
) -> DocumentOut:
    data = await _read_limited(file, c.settings.max_upload_bytes)
    record, extracted = c.documents.create_from_upload(data, file.filename, replace=replace)
    background.add_task(c.documents.index, record.id, extracted)
    return document_out(record)


@router.get("/documents", response_model=DocumentListOut, summary="List documents")
def list_documents(c: ContainerDep) -> DocumentListOut:
    return DocumentListOut(documents=[document_out(r) for r in c.documents.list_documents()], limits=limits(c))


@router.get("/documents/{document_id}", response_model=DocumentOut, responses=_ERRORS, summary="Get document metadata")
def get_document(c: ContainerDep, document_id: str) -> DocumentOut:
    return document_out(c.documents.get(document_id))


@router.get(
    "/documents/{document_id}/file",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}, 404: {"model": ErrorResponse}},
    summary="Download the original PDF for preview",
)
def get_document_file(c: ContainerDep, document_id: str) -> FileResponse:
    record = c.documents.get(document_id)
    return FileResponse(
        c.documents.file_path(document_id),
        media_type="application/pdf",
        filename=record.filename if record.filename.lower().endswith(".pdf") else f"{record.filename}.pdf",
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/documents/{document_id}/chunks",
    response_model=DocumentChunksOut,
    responses=_ERRORS,
    summary="Inspect the indexed chunks of a document",
)
def get_document_chunks(c: ContainerDep, document_id: str) -> DocumentChunksOut:
    record = c.documents.get(document_id)
    chunks = c.documents.chunks(document_id)
    return DocumentChunksOut(
        document_id=document_id,
        embedding_model=record.embedding_model,
        chunks=[
            ChunkOut(
                chunk_id=x.chunk_id,
                document_id=x.document_id,
                page=x.page_number,
                chunk_index=x.chunk_index,
                text=x.text,
                char_start=x.char_start,
                char_end=x.char_end,
            )
            for x in chunks
        ],
    )


@router.delete("/documents/{document_id}", response_model=DeleteResponse, responses=_ERRORS, summary="Delete a document and its index")
def delete_document(c: ContainerDep, document_id: str) -> DeleteResponse:
    c.documents.delete(document_id)
    return DeleteResponse(deleted=document_id)


@router.post(
    "/demo/load",
    response_model=DemoLoadResponse,
    tags=["demo"],
    responses=_ERRORS,
    summary="Load the bundled demo documents",
    description="Indexes the original sample documents in data/demo that are not yet in the workspace. Synchronous; takes a few seconds.",
)
def load_demo(c: ContainerDep) -> DemoLoadResponse:
    loaded = c.documents.seed_demo()
    return DemoLoadResponse(loaded=[document_out(r) for r in loaded], documents=[document_out(r) for r in c.documents.list_documents()])
