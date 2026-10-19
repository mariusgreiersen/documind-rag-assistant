"""Document lifecycle: upload -> validate -> store -> index, plus deletion and recovery.

Consistency rules:

* Retrieval only ever searches documents whose metadata status is ``ready``, so
  a half-indexed or failed document can never contribute passages.
* Deletion removes vectors first (so passages disappear from search
  immediately), then metadata, then the stored file. A leftover file is
  harmless and is removed by ``reconcile()`` at the next startup.
* Uploaded files are stored as ``<document_id>.pdf`` inside an
  application-managed directory. The user-supplied filename is display-only and
  never touches the filesystem.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from documind.core.config import Settings
from documind.core.errors import DocumentNotFound, DocumentNotReady, DuplicateDocument, NoDocumentsIndexed, ReadOnlyWorkspace, WorkspaceFull
from documind.core.logging import log_event, timed
from documind.documents.metadata_store import MetadataStore
from documind.embeddings.provider import EmbeddingProvider
from documind.ingestion.chunker import ChunkingConfig
from documind.ingestion.pdf_parser import extract_pdf
from documind.ingestion.pipeline import PIPELINE_VERSION, check_chunk_size, index_document
from documind.models.domain import DocumentRecord, DocumentStatus, ExtractedPdf, ScoredChunk
from documind.vectorstore.chroma_store import ChromaVectorStore

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")
_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def safe_display_name(filename: str | None) -> str:
    """A display-only filename: no directories, control or reserved characters."""
    name = re.split(r"[\\/]", filename or "")[-1]
    name = _UNSAFE_CHARS.sub("", name)
    name = " ".join(name.split()).strip(" .")
    return name[:150] or "document.pdf"


def title_from_filename(filename: str) -> str:
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    title = " ".join(re.sub(r"[_\-]+", " ", stem).split())
    return title or "Untitled document"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DocumentService:
    def __init__(self, settings: Settings, metadata: MetadataStore, store: ChromaVectorStore, embedder: EmbeddingProvider) -> None:
        self._settings = settings
        self._metadata = metadata
        self._store = store
        self._embedder = embedder
        self._chunking = ChunkingConfig(
            chunk_size=settings.chunk_size_tokens,
            chunk_overlap=settings.chunk_overlap_tokens,
            min_chunk_tokens=settings.min_chunk_tokens,
        )
        self._index_lock = threading.Lock()
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)

    @property
    def chunking(self) -> ChunkingConfig:
        return self._chunking

    def validate_configuration(self) -> None:
        check_chunk_size(self._chunking, self._embedder)

    # -- upload -----------------------------------------------------------------
    def create_from_upload(
        self,
        data: bytes,
        filename: str | None,
        *,
        replace: bool = False,
        document_id: str | None = None,
        is_demo: bool = False,
    ) -> tuple[DocumentRecord, ExtractedPdf]:
        """Validate and store an upload. Returns a ``processing`` record; call ``index`` next."""
        if self._settings.read_only and not is_demo:
            raise ReadOnlyWorkspace()
        s = self._settings
        with timed() as t:
            extracted = extract_pdf(
                data,
                max_bytes=s.max_upload_bytes,
                max_pages=s.max_pages,
                min_chars_per_page=s.min_chars_per_page,
                min_text_page_ratio=s.min_text_page_ratio,
            )
        sha256 = hashlib.sha256(data).hexdigest()
        log_event(
            logger,
            "extraction_completed",
            pages=extracted.page_count,
            text_pages=extracted.text_page_count,
            chars=sum(len(p.text) for p in extracted.pages),
            warnings=len(extracted.warnings),
            ms=t["ms"],
        )

        existing = self._metadata.find_by_hash(sha256)
        if existing is not None:
            if not replace:
                raise DuplicateDocument(
                    f'This document has already been uploaded as "{existing.title}".',
                    details={"document_id": existing.id},
                )
            self.delete(existing.id, allow_read_only=is_demo)
        if self._metadata.count() >= s.max_documents:
            raise WorkspaceFull(f"The workspace is limited to {s.max_documents} documents. Delete a document to upload another.")

        doc_id = document_id or f"doc_{uuid.uuid4().hex[:16]}"
        if not _DOC_ID.match(doc_id):
            raise ValueError(f"invalid document id {doc_id!r}")
        display_name = safe_display_name(filename)
        stored_name = f"{doc_id}.pdf"
        target = s.uploads_dir / stored_name
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(target)

        record = DocumentRecord(
            id=doc_id,
            filename=display_name,
            title=extracted.metadata_title or title_from_filename(display_name),
            sha256=sha256,
            size_bytes=len(data),
            page_count=extracted.page_count,
            status=DocumentStatus.PROCESSING,
            created_at=now_iso(),
            stored_name=stored_name,
            text_page_count=extracted.text_page_count,
            is_demo=is_demo,
        )
        self._metadata.insert(record)
        log_event(logger, "document_uploaded", document_id=doc_id, pages=record.page_count, bytes=record.size_bytes, demo=is_demo)
        return record, extracted

    def index(self, document_id: str, extracted: ExtractedPdf) -> DocumentRecord:
        """Chunk, embed and index a stored document; marks it ``ready`` or ``failed``."""
        record = self._require(document_id)
        log_event(logger, "ingestion_started", document_id=document_id, pages=record.page_count)
        try:
            with self._index_lock:
                stats = index_document(
                    document_id=document_id,
                    filename=record.filename,
                    title=record.title,
                    pages=extracted.pages,
                    embedder=self._embedder,
                    store=self._store,
                    cfg=self._chunking,
                )
            if stats.chunk_count == 0:
                raise ValueError("no chunks produced")
        except Exception as exc:
            log_event(logger, "ingestion_failed", logging.ERROR, document_id=document_id, error=repr(exc))
            try:
                self._store.delete_document(document_id)
            except Exception:
                log_event(logger, "ingestion_cleanup_failed", logging.ERROR, document_id=document_id)
            self._metadata.update(document_id, status=DocumentStatus.FAILED, error="Indexing failed. Delete the document and try again.")
            return self._require(document_id)

        self._metadata.update(
            document_id,
            status=DocumentStatus.READY,
            chunk_count=stats.chunk_count,
            error=None,
            embedding_model=self._embedder.model_id,
            chunk_size_tokens=self._chunking.chunk_size,
            chunk_overlap_tokens=self._chunking.chunk_overlap,
            indexed_at=now_iso(),
            pipeline_version=PIPELINE_VERSION,
        )
        log_event(
            logger,
            "ingestion_completed",
            document_id=document_id,
            chunks=stats.chunk_count,
            embed_ms=stats.embed_ms,
            total_ms=round(stats.chunk_ms + stats.embed_ms + stats.index_ms, 1),
        )
        return self._require(document_id)

    def upload(self, data: bytes, filename: str | None, **kwargs: object) -> DocumentRecord:
        """Synchronous upload + index (CLI, demo seeding and tests)."""
        record, extracted = self.create_from_upload(data, filename, **kwargs)  # type: ignore[arg-type]
        return self.index(record.id, extracted)

    # -- queries ----------------------------------------------------------------
    def list_documents(self) -> list[DocumentRecord]:
        return self._metadata.list_documents()

    def get(self, document_id: str) -> DocumentRecord:
        return self._require(document_id)

    def file_path(self, document_id: str) -> Path:
        record = self._require(document_id)
        path = (self._settings.uploads_dir / record.stored_name).resolve()
        # stored_name is generated by us, but verify containment anyway (defence in depth).
        if self._settings.uploads_dir.resolve() not in path.parents or not path.is_file():
            raise DocumentNotFound("The stored file for this document is missing.")
        return path

    def chunks(self, document_id: str) -> list[ScoredChunk]:
        record = self._require(document_id)
        if record.status != DocumentStatus.READY:
            raise DocumentNotReady()
        return self._store.get_document_chunks(document_id)

    def search_scope(self, document_ids: list[str] | None) -> list[str]:
        """Resolve the documents a query may search: requested ones, or every ready document."""
        ready = set(self._metadata.ready_ids())
        if document_ids:
            for doc_id in document_ids:
                record = self._metadata.get(doc_id)
                if record is None:
                    raise DocumentNotFound(f"Document {doc_id} was not found.")
                if record.status != DocumentStatus.READY:
                    raise DocumentNotReady(f'"{record.title}" is not ready for search yet.')
            scope = [d for d in dict.fromkeys(document_ids) if d in ready]
        else:
            scope = sorted(ready)
        if not scope:
            raise NoDocumentsIndexed()
        return scope

    # -- deletion & recovery ------------------------------------------------------
    def delete(self, document_id: str, *, allow_read_only: bool = False) -> None:
        if self._settings.read_only and not allow_read_only:
            raise ReadOnlyWorkspace()
        record = self._require(document_id)
        self._store.delete_document(document_id)  # raises -> nothing else is touched
        self._metadata.delete(document_id)
        try:
            (self._settings.uploads_dir / record.stored_name).unlink(missing_ok=True)
        except OSError:
            log_event(logger, "file_delete_failed", logging.WARNING, document_id=document_id)
        log_event(logger, "document_deleted", document_id=document_id)

    def reconcile(self) -> dict[str, int]:
        """Repair state left by a crash: interrupted ingestions, orphan vectors and files."""
        interrupted = 0
        for record in self._metadata.list_documents():
            if record.status == DocumentStatus.PROCESSING:
                self._store.delete_document(record.id)
                self._metadata.update(
                    record.id, status=DocumentStatus.FAILED, error="Processing was interrupted. Delete the document and upload it again."
                )
                interrupted += 1
        known = {r.id for r in self._metadata.list_documents()}
        orphan_vectors = self._store.document_ids() - known
        for doc_id in orphan_vectors:
            self._store.delete_document(doc_id)
        known_files = {r.stored_name for r in self._metadata.list_documents()}
        orphan_files = 0
        for path in self._settings.uploads_dir.glob("*"):
            if path.is_file() and path.name not in known_files:
                path.unlink(missing_ok=True)
                orphan_files += 1
        # Documents indexed with another embedding model or chunking configuration have no
        # vectors in the current collection (or stale ones). Vectors from different models
        # must never be mixed, so re-index them from the stored PDF.
        stale = [r for r in self._metadata.list_documents() if r.status == DocumentStatus.READY and self._is_stale(r)]
        for record in stale:
            log_event(logger, "reindex_stale_document", document_id=record.id, previous_model=record.embedding_model)
            self.reindex(record.id)
        summary = {
            "interrupted": interrupted,
            "orphan_vector_documents": len(orphan_vectors),
            "orphan_files": orphan_files,
            "reindexed": len(stale),
        }
        log_event(logger, "reconcile_completed", **summary)
        return summary

    def _is_stale(self, record: DocumentRecord) -> bool:
        return (
            record.embedding_model != self._embedder.model_id
            or record.chunk_size_tokens != self._chunking.chunk_size
            or record.chunk_overlap_tokens != self._chunking.chunk_overlap
            or record.pipeline_version != PIPELINE_VERSION
        )

    def reindex(self, document_id: str) -> DocumentRecord:
        """Re-extract and re-index one stored document."""
        record = self._require(document_id)
        data = (self._settings.uploads_dir / record.stored_name).read_bytes()
        s = self._settings
        extracted = extract_pdf(
            data,
            max_bytes=s.max_upload_bytes,
            max_pages=s.max_pages,
            min_chars_per_page=s.min_chars_per_page,
            min_text_page_ratio=s.min_text_page_ratio,
        )
        self._metadata.update(document_id, status=DocumentStatus.PROCESSING)
        return self.index(document_id, extracted)

    def reindex_all(self) -> list[DocumentRecord]:
        """Re-extract and re-index every stored document (after changing model or chunking)."""
        return [self.reindex(r.id) for r in self._metadata.list_documents()]

    # -- demo -------------------------------------------------------------------
    def demo_manifest(self) -> list[dict]:
        path = self._settings.demo_dir / "manifest.json"
        if not path.is_file():
            return []
        return list(json.loads(path.read_text(encoding="utf-8"))["documents"])

    def seed_demo(self) -> list[DocumentRecord]:
        """Index the bundled demo documents that are not already in the workspace."""
        loaded = []
        for entry in self.demo_manifest():
            existing = self._metadata.get(entry["id"])
            if existing is not None and existing.status == DocumentStatus.READY:
                continue
            if existing is not None:
                self.delete(existing.id, allow_read_only=True)
            data = (self._settings.demo_dir / entry["filename"]).read_bytes()
            try:
                loaded.append(self.upload(data, entry["filename"], document_id=entry["id"], is_demo=True))
            except DuplicateDocument:
                continue  # the same file was uploaded manually; keep the user's copy
        log_event(logger, "demo_seeded", documents=len(loaded))
        return loaded

    def _require(self, document_id: str) -> DocumentRecord:
        record = self._metadata.get(document_id)
        if record is None:
            raise DocumentNotFound()
        return record
