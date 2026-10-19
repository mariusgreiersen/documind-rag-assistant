import pytest

from documind.core.errors import InvalidQuery, LLMProviderError, NoDocumentsIndexed
from documind.generation.llm_provider import MockLLMProvider
from documind.generation.prompts import INSUFFICIENT_EVIDENCE_MESSAGE, HistoryTurn


@pytest.fixture
def indexed(make_container, sample_pdf):
    def build(llm=None, **overrides):
        c = make_container(llm=llm, **overrides)
        record = c.documents.upload(sample_pdf, "notes.pdf")
        return c, record

    return build


def test_retrieval_only_mode_without_llm(indexed):
    c, _ = indexed(llm=None)
    outcome = c.answers.answer("When is a log entry committed in Raft?")
    assert outcome.status == "retrieval_only"
    assert outcome.answer is None
    assert "Retrieval-only mode" in outcome.notice
    assert outcome.sources and outcome.sources[0].chunk.page_number == 1
    assert outcome.diagnostics["llm_called"] is False


def test_grounded_answer_with_validated_citation(indexed):
    llm = MockLLMProvider()
    c, record = indexed(llm=llm)
    outcome = c.answers.answer("When is a log entry committed in Raft?")
    assert outcome.status == "answered"
    assert outcome.answer.endswith("[1]")
    cit = outcome.citations[0]
    assert cit.source.chunk.document_id == record.id
    assert cit.source.chunk.page_number == 1
    assert outcome.diagnostics["llm_called"] is True


def test_relevance_gate_skips_the_llm(indexed):
    llm = MockLLMProvider()
    c, _ = indexed(llm=llm, min_relevance_score=0.99)
    outcome = c.answers.answer("Who won the football world cup?")
    assert outcome.status == "insufficient_evidence"
    assert outcome.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert outcome.diagnostics["gate"] == "below_relevance_threshold"
    assert llm.calls == []


def test_model_declining_is_respected(indexed):
    llm = MockLLMProvider(
        lambda q, s, h: {
            "status": "insufficient_evidence",
            "answer": "The documents do not cover 2028.",
            "cited_source_ids": [],
            "unsupported_aspects": [],
        }
    )
    c, _ = indexed(llm=llm)
    outcome = c.answers.answer("What is the revenue in 2028 for the caching company?")
    assert outcome.status == "insufficient_evidence"
    assert outcome.citations == []


def test_fabricated_citations_are_rejected_and_answer_downgraded(indexed):
    llm = MockLLMProvider(
        lambda q, s, h: {
            "status": "answered",
            "answer": "Revenue was 1 billion [S12].",
            "cited_source_ids": ["S12"],
            "unsupported_aspects": [],
        }
    )
    c, _ = indexed(llm=llm)
    outcome = c.answers.answer("Tell me about caching patterns")
    assert outcome.status == "insufficient_evidence"
    assert outcome.diagnostics["rejected_citation_ids"] == ["S12"]
    assert outcome.diagnostics["downgraded"] is True
    assert "1 billion" not in outcome.answer


def test_provider_failure_still_returns_passages(indexed):
    class FailingLLM(MockLLMProvider):
        def generate_answer(self, question, sources, history):
            raise LLMProviderError()

    c, _ = indexed(llm=FailingLLM())
    outcome = c.answers.answer("What is cache-aside?")
    assert outcome.status == "generation_unavailable"
    assert outcome.sources
    assert "temporarily unavailable" in outcome.notice


def test_follow_up_questions_are_rewritten_with_history_for_retrieval(indexed):
    llm = MockLLMProvider()
    c, _ = indexed(llm=llm)
    history = [HistoryTurn("user", "What is a cache stampede?"), HistoryTurn("assistant", "Many requests miss at once [1].")]
    outcome = c.answers.answer("How common is it?", history=history)
    assert outcome.diagnostics["query_rewritten"] is True
    assert "cache stampede" in outcome.diagnostics["search_query"]
    answer_call = next(call for call in llm.calls if call["type"] == "answer")
    assert answer_call["history"] == history  # history goes to the model as context, not as sources
    assert all("Many requests miss at once" not in s.chunk.text for s in answer_call["sources"])


def test_history_is_bounded(indexed):
    llm = MockLLMProvider()
    c, _ = indexed(llm=llm, max_history_turns=2)
    history = [HistoryTurn("user", f"question {i}") for i in range(10)]
    c.answers.answer("And caching?", history=history)
    answer_call = next(call for call in llm.calls if call["type"] == "answer")
    assert [t.content for t in answer_call["history"]] == ["question 8", "question 9"]


def test_rewrite_failure_falls_back_to_original_question(indexed):
    class NoRewrite(MockLLMProvider):
        def rewrite_query(self, question, history):
            raise LLMProviderError()

    c, _ = indexed(llm=NoRewrite())
    outcome = c.answers.answer("What is cache-aside?", history=[HistoryTurn("user", "hi")])
    assert outcome.diagnostics["search_query"] == "What is cache-aside?"
    assert outcome.diagnostics["rewrite_error"]


def test_empty_and_oversized_questions_are_rejected(indexed):
    c, _ = indexed()
    with pytest.raises(InvalidQuery):
        c.answers.answer("   ")
    with pytest.raises(InvalidQuery):
        c.answers.answer("x" * 5000)


def test_no_documents(make_container):
    c = make_container()
    with pytest.raises(NoDocumentsIndexed):
        c.answers.answer("anything")
