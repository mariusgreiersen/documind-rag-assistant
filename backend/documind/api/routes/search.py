from __future__ import annotations

from fastapi import APIRouter

from documind.api.deps import ContainerDep, search_result
from documind.models.schemas import ErrorResponse, SearchRequest, SearchResponse

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={r: {"model": ErrorResponse} for r in (404, 409, 422, 503)},
    summary="Semantic search over indexed passages",
    description=(
        "Embeds the query with the same model used for indexing and returns the `top_k` nearest passages. "
        "`score` is cosine similarity (higher is closer); it is a ranking signal, not a probability of relevance. "
        "Works without an LLM API key."
    ),
)
def search(c: ContainerDep, body: SearchRequest) -> SearchResponse:
    scope = c.documents.search_scope(body.document_ids)
    result = c.retriever.search(body.query, document_ids=scope, top_k=body.top_k)
    return SearchResponse(
        query=result.query,
        top_k=result.top_k,
        embedding_model=c.embedder.model_id,
        took_ms=result.total_ms,
        results=[search_result(chunk, rank) for rank, chunk in enumerate(result.chunks, start=1)],
    )
