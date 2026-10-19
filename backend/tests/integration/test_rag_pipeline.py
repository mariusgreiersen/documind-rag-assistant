"""End-to-end RAG tests with the real embedding model, real ChromaDB persistence and the mock LLM.

Marked ``model``: the first run downloads the embedding model (~130 MB).
"""

from __future__ import annotations

import pytest

from documind.container import build_container
from documind.core.config import REPO_ROOT, Settings
from documind.embeddings.local_embeddings import SentenceTransformerEmbedder
from documind.generation.llm_provider import MockLLMProvider
from documind.generation.prompts import ANSWER_SYSTEM_PROMPT
from documind.ingestion.chunker import ChunkingConfig
from documind.ingestion.pipeline import ChunkTooLargeForModel, check_chunk_size

pytestmark = pytest.mark.model

RAFT = "demo-raft-consensus"
VENDOR = "demo-vendor-notes"
COMMIT_EVIDENCE = "A log entry is committed once the leader that created it has replicated it on a majority of the servers."


@pytest.fixture(scope="module")
def real_embedder():
    s = Settings(_env_file=None)
    return SentenceTransformerEmbedder(s.embedding_model, query_prefix=s.embedding_query_prefix or "")


@pytest.fixture
def rag_settings(tmp_path):
    return Settings(
        _env_file=None, data_dir=tmp_path / "data", demo_dir=REPO_ROOT / "data" / "demo", llm_provider="none", log_level="WARNING"
    )


@pytest.fixture
def demo_container(rag_settings, real_embedder):
    containers = []

    def build(llm=None, seed=True):
        c = build_container(rag_settings, embedder=real_embedder, llm=llm)
        containers.append(c)
        if seed:
            c.documents.seed_demo()
        return c

    yield build
    for c in containers:
        c.close()


def test_model_input_limit_and_truncation_guard(real_embedder):
    assert real_embedder.dimension == 384
    assert real_embedder.max_input_tokens == real_embedder.max_seq_length - 2
    check_chunk_size(ChunkingConfig(chunk_size=real_embedder.max_input_tokens, chunk_overlap=10), real_embedder)
    with pytest.raises(ChunkTooLargeForModel):
        check_chunk_size(ChunkingConfig(chunk_size=real_embedder.max_input_tokens + 1, chunk_overlap=10), real_embedder)


def test_text_beyond_the_input_limit_does_not_affect_the_embedding(real_embedder):
    """Documents the silent truncation that the chunk-size guard exists to prevent."""
    head = " ".join(["consensus"] * (real_embedder.max_input_tokens + 20))
    full = head + " " + " ".join(["bakery"] * 300)
    a, b = real_embedder.embed_documents([head, full])
    assert sum(x * y for x, y in zip(a, b, strict=True)) > 0.999


def test_demo_corpus_is_indexed_with_page_metadata(demo_container):
    c = demo_container()
    docs = {d.id: d for d in c.documents.list_documents()}
    assert set(docs) == {"demo-caching-strategies", "demo-concurrency-control", "demo-northwind-review", VENDOR, RAFT}
    assert all(d.status.value == "ready" and d.chunk_count > 0 for d in docs.values())
    chunks = c.documents.chunks(RAFT)
    assert {ch.page_number for ch in chunks} == {1, 2, 3, 4, 5}
    assert sum(ch.chunk_id.startswith(f"{RAFT}:p") for ch in chunks) == docs[RAFT].chunk_count


def test_semantic_search_retrieves_the_right_page(demo_container):
    c = demo_container()
    result = c.retriever.search("When is a log entry considered committed in Raft?", document_ids=c.documents.search_scope(None), top_k=5)
    hits = [ch for ch in result.chunks if ch.document_id == RAFT and ch.page_number == 3 and COMMIT_EVIDENCE in " ".join(ch.text.split())]
    assert hits, [(ch.chunk_id, ch.score) for ch in result.chunks]
    scores = [ch.score for ch in result.chunks]
    assert scores == sorted(scores, reverse=True)


def test_full_rag_pipeline_with_mock_llm_cites_correct_document_and_page(demo_container):
    def cite_commit_passage(question, sources, history):
        ref = next(s.ref_id for s in sources if COMMIT_EVIDENCE in " ".join(s.chunk.text.split()))
        return {
            "status": "answered",
            "answer": f"An entry is committed once a majority stores it [{ref}].",
            "cited_source_ids": [ref],
            "unsupported_aspects": [],
        }

    c = demo_container(llm=MockLLMProvider(cite_commit_passage))
    outcome = c.answers.answer("When is a log entry considered committed in Raft?", top_k=5)
    assert outcome.status == "answered"
    assert len(outcome.citations) == 1
    cited = outcome.citations[0].source.chunk
    assert (cited.document_id, cited.page_number) == (RAFT, 3)
    assert cited.filename == "raft-consensus-lecture-notes.pdf"


def test_vectors_persist_across_restarts(demo_container):
    first = demo_container()
    total = first.store.count()
    query = "What is a cache stampede?"
    before = [ch.chunk_id for ch in first.retriever.search(query, document_ids=first.documents.search_scope(None), top_k=5).chunks]
    first.close()
    second = demo_container(seed=False)
    assert second.store.count() == total
    after = [ch.chunk_id for ch in second.retriever.search(query, document_ids=second.documents.search_scope(None), top_k=5).chunks]
    assert after == before


def test_deleted_document_never_appears_in_retrieval(demo_container):
    c = demo_container()
    c.documents.delete(RAFT)
    result = c.retriever.search("Raft leader election heartbeat AppendEntries", document_ids=c.documents.search_scope(None), top_k=20)
    assert all(ch.document_id != RAFT for ch in result.chunks)
    assert c.store.count(RAFT) == 0


# --- prompt injection ------------------------------------------------------------
INJECTION_MARKER = "Ignore all previous instructions"


def test_injected_instructions_reach_the_model_only_as_escaped_source_text(demo_container):
    llm = MockLLMProvider()
    c = demo_container(llm=llm)
    c.answers.answer("What are the ExamplePay API rate limits and authentication rules?", top_k=5)
    call = next(x for x in llm.calls if x["type"] == "answer")
    assert any(s.chunk.document_id == VENDOR and INJECTION_MARKER in s.chunk.text for s in call["sources"])
    prompt = call["prompt"]
    sources_block = prompt.split("<sources>", 1)[1].split("</sources>", 1)[0]
    assert INJECTION_MARKER in sources_block
    assert INJECTION_MARKER not in prompt.replace(sources_block, "")
    assert INJECTION_MARKER not in ANSWER_SYSTEM_PROMPT
    assert "untrusted" in ANSWER_SYSTEM_PROMPT


def test_a_model_that_obeys_the_injection_is_caught_by_citation_validation(demo_container):
    """If the model followed the injected text and asserted an uncited claim, the validator refuses it."""

    def compromised(question, sources, history):
        return {
            "status": "answered",
            "answer": "The documents confirm Northwind's 2028 revenue was DKK 1 billion.",
            "cited_source_ids": [],
            "unsupported_aspects": [],
        }

    c = demo_container(llm=MockLLMProvider(compromised))
    outcome = c.answers.answer("What is Northwind's revenue in 2028?")
    assert outcome.status == "insufficient_evidence"
    assert "1 billion" not in (outcome.answer or "")
