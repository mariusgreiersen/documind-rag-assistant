"""ChromaDB-backed vector store.

One collection per embedding model: the collection name embeds the model ID and
vector dimension, and the model ID is stored in the collection metadata and
checked when the collection is opened. Switching ``EMBEDDING_MODEL`` therefore
creates a fresh, empty collection instead of mixing incompatible vectors; the
documents must be re-indexed (``python -m documind.cli reindex``).

Similarity is cosine. Chroma returns cosine *distance* (1 - cosine similarity);
``ScoredChunk.score`` exposes the similarity. Because embeddings are
L2-normalised, cosine and inner product rankings are identical.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from documind.core.errors import VectorStoreError
from documind.core.logging import log_event
from documind.models.domain import Chunk, ScoredChunk

logger = logging.getLogger(__name__)


def collection_name_for(model_id: str, dimension: int) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model_id.split("/")[-1]).strip("-").lower()[:40]
    return f"documind_{slug}_{dimension}"


class ChromaVectorStore:
    def __init__(
        self,
        persist_dir: Path | None,
        *,
        embedding_model: str,
        dimension: int,
        client: Any = None,
    ) -> None:
        """``persist_dir=None`` creates an in-memory store (tests and experiments only)."""
        if client is None:
            settings = ChromaSettings(anonymized_telemetry=False, allow_reset=False)
            if persist_dir is None:
                client = chromadb.EphemeralClient(settings=settings)
            else:
                persist_dir.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=str(persist_dir), settings=settings)
        self._client = client
        self.embedding_model = embedding_model
        self.dimension = dimension
        self.collection_name = collection_name_for(embedding_model, dimension)
        try:
            self._collection = client.get_or_create_collection(
                self.collection_name,
                configuration={"hnsw": {"space": "cosine"}},
                metadata={"embedding_model": embedding_model, "dimension": dimension},
                embedding_function=None,  # we always pass our own embeddings
            )
        except Exception as exc:
            log_event(logger, "vector_store_open_failed", logging.ERROR, error=repr(exc))
            raise VectorStoreError() from exc
        stored_model = (self._collection.metadata or {}).get("embedding_model")
        if stored_model != embedding_model:
            raise VectorStoreError(
                f"Collection {self.collection_name} was built with {stored_model!r}, not {embedding_model!r}. Re-index required."
            )

    # -- writes -----------------------------------------------------------------
    def add_chunks(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        *,
        filename: str,
        title: str,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if not chunks:
            return
        if any(len(e) != self.dimension for e in embeddings):
            raise VectorStoreError("Embedding dimension does not match the collection.")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        metadatas = [
            {
                "document_id": c.document_id,
                "filename": filename,
                "title": title,
                "page": c.page_number,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "token_count": c.token_count,
                "content_hash": c.content_hash,
                "embedding_model": self.embedding_model,
                "indexed_at": now,
            }
            for c in chunks
        ]
        try:
            # upsert keeps re-ingestion idempotent: identical chunk IDs replace old rows.
            self._collection.upsert(
                ids=[c.chunk_id for c in chunks],
                embeddings=[list(e) for e in embeddings],
                documents=[c.text for c in chunks],
                metadatas=metadatas,
            )
        except Exception as exc:
            log_event(logger, "vector_store_write_failed", logging.ERROR, error=repr(exc))
            raise VectorStoreError() from exc

    def delete_document(self, document_id: str) -> None:
        try:
            self._collection.delete(where={"document_id": document_id})
        except Exception as exc:
            log_event(logger, "vector_store_delete_failed", logging.ERROR, document_id=document_id, error=repr(exc))
            raise VectorStoreError() from exc

    # -- reads ------------------------------------------------------------------
    def query(self, embedding: Sequence[float], *, top_k: int, document_ids: Sequence[str]) -> list[ScoredChunk]:
        """Nearest chunks among ``document_ids``. An empty list of IDs returns nothing."""
        if not document_ids:
            return []
        where: dict[str, Any] = {"document_id": document_ids[0]} if len(document_ids) == 1 else {"document_id": {"$in": list(document_ids)}}
        try:
            result = self._collection.query(
                query_embeddings=[list(embedding)],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            log_event(logger, "vector_store_query_failed", logging.ERROR, error=repr(exc))
            raise VectorStoreError() from exc
        ids = result["ids"][0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        return [_to_scored(cid, text, meta, dist) for cid, text, meta, dist in zip(ids, docs, metas, dists, strict=True)]

    def get_document_chunks(self, document_id: str) -> list[ScoredChunk]:
        """All chunks of one document in reading order (distance is 0, not meaningful)."""
        try:
            result = self._collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
        except Exception as exc:
            raise VectorStoreError() from exc
        chunks = [
            _to_scored(cid, text, meta, 0.0)
            for cid, text, meta in zip(result["ids"], result["documents"] or [], result["metadatas"] or [], strict=True)
        ]
        return sorted(chunks, key=lambda c: c.chunk_index)

    def count(self, document_id: str | None = None) -> int:
        try:
            if document_id is None:
                return int(self._collection.count())
            return len(self._collection.get(where={"document_id": document_id}, include=[])["ids"])
        except Exception as exc:
            raise VectorStoreError() from exc

    def document_ids(self) -> set[str]:
        """Distinct document IDs present in the collection (used for reconciliation)."""
        try:
            metas = self._collection.get(include=["metadatas"])["metadatas"] or []
        except Exception as exc:
            raise VectorStoreError() from exc
        return {str(m["document_id"]) for m in metas if m and "document_id" in m}


def _to_scored(chunk_id: str, text: str | None, meta: Any, distance: float) -> ScoredChunk:
    m = dict(meta or {})
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id=str(m["document_id"]),
        filename=str(m.get("filename", "")),
        title=str(m.get("title", "")),
        page_number=int(m["page"]),
        chunk_index=int(m.get("chunk_index", 0)),
        text=text or "",
        char_start=int(m.get("char_start", 0)),
        char_end=int(m.get("char_end", 0)),
        distance=float(distance),
    )
