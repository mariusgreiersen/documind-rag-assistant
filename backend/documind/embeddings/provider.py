"""Embedding provider interface.

An embedding provider owns three things that must stay consistent with each other:
the model that produces vectors, the tokenizer used to size chunks, and the
model identifier stored next to every vector. Vectors from different models live
in different vector spaces and must never be compared, so the vector store keys
its collection on ``model_id`` and ``dimension``.
"""

from __future__ import annotations

from typing import Protocol

from documind.ingestion.chunker import Span


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def max_seq_length(self) -> int:
        """Maximum sequence length of the model, including special tokens."""
        ...

    @property
    def max_input_tokens(self) -> int:
        """Content tokens the model embeds before silently truncating the rest."""
        ...

    def token_spans(self, text: str) -> list[Span]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """L2-normalised passage embeddings, in input order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """L2-normalised query embedding (may apply a model-specific query prefix)."""
        ...
