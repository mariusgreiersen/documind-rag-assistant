from __future__ import annotations

from fastapi import APIRouter

from documind.api.deps import ContainerDep, search_result
from documind.generation.prompts import HistoryTurn
from documind.models.schemas import ChatRequest, ChatResponse, Citation, ErrorResponse, SourcePassageOut

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post(
    "/chat/query",
    response_model=ChatResponse,
    responses={r: {"model": ErrorResponse} for r in (404, 409, 422)},
    summary="Ask a question and get a grounded, cited answer",
    description="""
Retrieves the most relevant passages and, if an LLM is configured and the best passage passes the relevance
threshold, generates an answer that may only use those passages. Citation markers are validated against the
retrieved passages and rendered from backend metadata.

`status` values:

* `answered` – every part of the answer is supported by cited passages.
* `partially_answered` – some parts are supported; the rest are listed in `unsupported_aspects`.
* `insufficient_evidence` – the documents do not contain enough information (decided by the relevance gate, the model, or the citation validator).
* `retrieval_only` – no LLM is configured; `sources` contains the retrieved passages and `answer` is null.
* `generation_unavailable` – the LLM call failed; `sources` is still populated.
""",
)
def chat_query(c: ContainerDep, body: ChatRequest) -> ChatResponse:
    outcome = c.answers.answer(
        body.question,
        document_ids=body.document_ids,
        top_k=body.top_k,
        history=[HistoryTurn(m.role, m.content) for m in body.history],
    )
    citations = [
        Citation(
            number=cit.number,
            ref_id=cit.source.ref_id,
            chunk_id=cit.source.chunk.chunk_id,
            document_id=cit.source.chunk.document_id,
            filename=cit.source.chunk.filename,
            title=cit.source.chunk.title,
            page=cit.source.chunk.page_number,
            text=cit.source.chunk.text,
            score=cit.source.chunk.score,
            char_start=cit.source.chunk.char_start,
            char_end=cit.source.chunk.char_end,
        )
        for cit in outcome.citations
    ]
    sources = [
        SourcePassageOut(ref_id=s.ref_id, **search_result(s.chunk, rank).model_dump()) for rank, s in enumerate(outcome.sources, start=1)
    ]
    return ChatResponse(
        status=outcome.status,  # type: ignore[arg-type]
        answer=outcome.answer,
        citations=citations,
        sources=sources,
        unsupported_aspects=outcome.unsupported_aspects,
        notice=outcome.notice,
        model=outcome.model,
        diagnostics=outcome.diagnostics if c.settings.enable_diagnostics else None,
    )
