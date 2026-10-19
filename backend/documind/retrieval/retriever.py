"""Semantic retrieval: embed the query, search the vector store, return ranked passages.

Retrieval is independent of answer generation, so search works without an LLM.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from documind.core.errors import InvalidQuery
from documind.core.logging import log_event, timed
from documind.embeddings.provider import EmbeddingProvider
from documind.models.domain import ScoredChunk
from documind.vectorstore.chroma_store import ChromaVectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    top_k: int
    chunks: list[ScoredChunk]
    embedding_ms: float
    search_ms: float

    @property
    def top_score(self) -> float | None:
        return self.chunks[0].score if self.chunks else None

    @property
    def total_ms(self) -> float:
        return round(self.embedding_ms + self.search_ms, 1)


class Retriever:
    def __init__(self, embedder: EmbeddingProvider, store: ChromaVectorStore, *, max_query_chars: int = 1000, max_top_k: int = 20) -> None:
        self._embedder = embedder
        self._store = store
        self._max_query_chars = max_query_chars
        self._max_top_k = max_top_k

    def validate_query(self, query: str) -> str:
        cleaned = " ".join((query or "").split())
        if not cleaned:
            raise InvalidQuery("Enter a question or search query.")
        if len(cleaned) > self._max_query_chars:
            raise InvalidQuery(f"Queries are limited to {self._max_query_chars} characters.")
        return cleaned

    def search(self, query: str, *, document_ids: Sequence[str], top_k: int) -> RetrievalResult:
        query = self.validate_query(query)
        top_k = max(1, min(top_k, self._max_top_k))
        with timed() as t_embed:
            vector = self._embedder.embed_query(query)
        with timed() as t_search:
            chunks = self._store.query(vector, top_k=top_k, document_ids=document_ids)
        result = RetrievalResult(query=query, top_k=top_k, chunks=chunks, embedding_ms=t_embed["ms"], search_ms=t_search["ms"])
        log_event(
            logger,
            "retrieval_completed",
            query_chars=len(query),
            documents=len(document_ids),
            top_k=top_k,
            results=len(chunks),
            top_score=result.top_score,
            ms=result.total_ms,
        )
        return result
