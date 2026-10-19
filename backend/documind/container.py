"""Wires the application's components together.

All collaborators can be injected, which is how tests swap in a fake embedder,
an in-memory vector store or the mock LLM without patching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from documind.core.config import Settings
from documind.documents.document_service import DocumentService
from documind.documents.metadata_store import MetadataStore
from documind.embeddings.local_embeddings import SentenceTransformerEmbedder
from documind.embeddings.provider import EmbeddingProvider
from documind.generation.answer_service import AnswerService
from documind.generation.llm_provider import LLMProvider, build_llm_provider
from documind.retrieval.retriever import Retriever
from documind.vectorstore.chroma_store import ChromaVectorStore

_UNSET: Any = object()


@dataclass
class Container:
    settings: Settings
    embedder: EmbeddingProvider
    store: ChromaVectorStore
    metadata: MetadataStore
    documents: DocumentService
    retriever: Retriever
    answers: AnswerService
    llm: LLMProvider | None

    def close(self) -> None:
        self.metadata.close()


def build_container(
    settings: Settings,
    *,
    embedder: EmbeddingProvider | None = None,
    llm: LLMProvider | None = _UNSET,
    chroma_client: Any = None,
    in_memory_vectors: bool = False,
) -> Container:
    embedder = embedder or SentenceTransformerEmbedder(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
        query_prefix=settings.embedding_query_prefix or "",
    )
    store = ChromaVectorStore(
        None if in_memory_vectors else settings.chroma_persist_dir,
        embedding_model=embedder.model_id,
        dimension=embedder.dimension,
        client=chroma_client,
    )
    metadata = MetadataStore(settings.metadata_db_path)
    documents = DocumentService(settings, metadata, store, embedder)
    retriever = Retriever(embedder, store, max_query_chars=settings.max_question_chars, max_top_k=settings.max_top_k)
    provider = build_llm_provider(settings) if llm is _UNSET else llm
    answers = AnswerService(settings, retriever, documents, provider)
    return Container(settings, embedder, store, metadata, documents, retriever, answers, provider)
