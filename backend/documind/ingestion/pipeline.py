"""Chunk -> embed -> index for one already-extracted document.

Shared by the API (document service) and the evaluation experiments, so both
measure exactly the same pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from documind.core.logging import log_event, timed
from documind.embeddings.provider import EmbeddingProvider
from documind.ingestion.chunker import ChunkingConfig, chunk_document
from documind.models.domain import Chunk, PageText
from documind.vectorstore.chroma_store import ChromaVectorStore

logger = logging.getLogger(__name__)

# Bump when extraction, cleaning or chunking logic changes in a way that changes chunks.
# Documents indexed by another version are re-indexed automatically at startup.
PIPELINE_VERSION = "2"


class ChunkTooLargeForModel(ValueError):
    pass


@dataclass(frozen=True)
class IndexStats:
    chunk_count: int
    chunk_ms: float
    embed_ms: float
    index_ms: float


def check_chunk_size(cfg: ChunkingConfig, embedder: EmbeddingProvider, *, allow_truncation: bool = False) -> None:
    """Refuse chunk sizes the embedding model would silently truncate."""
    if cfg.chunk_size > embedder.max_input_tokens and not allow_truncation:
        raise ChunkTooLargeForModel(
            f"CHUNK_SIZE_TOKENS={cfg.chunk_size} exceeds the {embedder.max_input_tokens} content tokens that "
            f"{embedder.model_id} embeds (max_seq_length={embedder.max_seq_length} incl. special tokens); "
            "the end of each chunk would never be embedded"
        )


def build_chunks(document_id: str, pages: Sequence[PageText], embedder: EmbeddingProvider, cfg: ChunkingConfig) -> list[Chunk]:
    return chunk_document(document_id, pages, embedder, cfg)


def index_document(
    *,
    document_id: str,
    filename: str,
    title: str,
    pages: Sequence[PageText],
    embedder: EmbeddingProvider,
    store: ChromaVectorStore,
    cfg: ChunkingConfig,
) -> IndexStats:
    with timed() as t_chunk:
        chunks = build_chunks(document_id, pages, embedder, cfg)
    log_event(logger, "chunking_completed", document_id=document_id, chunks=len(chunks), ms=t_chunk["ms"])
    with timed() as t_embed:
        vectors = embedder.embed_documents([c.text for c in chunks])
    log_event(logger, "embedding_completed", document_id=document_id, chunks=len(chunks), ms=t_embed["ms"], model=embedder.model_id)
    with timed() as t_index:
        # Remove chunks from any previous indexing run so that a re-index with a
        # different configuration cannot leave stale passages behind.
        store.delete_document(document_id)
        store.add_chunks(chunks, vectors, filename=filename, title=title)
    log_event(logger, "indexing_completed", document_id=document_id, chunks=len(chunks), ms=t_index["ms"])
    return IndexStats(chunk_count=len(chunks), chunk_ms=t_chunk["ms"], embed_ms=t_embed["ms"], index_ms=t_index["ms"])
