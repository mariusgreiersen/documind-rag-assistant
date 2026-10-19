"""HTTP-level tests through FastAPI's TestClient (fake embedder, mock LLM, real Chroma and SQLite)."""

import pytest

from documind.generation.llm_provider import MockLLMProvider
from tests.conftest import encrypt_pdf, make_image_only_pdf, make_pdf


def upload(client, data: bytes, name: str = "notes.pdf", **params):
    return client.post("/api/v1/documents/upload", files={"file": (name, data, "application/pdf")}, params=params)


def test_health_and_config(make_client):
    client = make_client()
    assert client.get("/health").json() == {"status": "ok", "version": "1.0.0"}
    config = client.get("/api/v1/config").json()
    assert config["llm_configured"] is False
    assert config["score_metric"] == "cosine_similarity"
    assert "api_key" not in str(config).lower()


def test_upload_then_list_get_chunks_file(make_client, sample_pdf):
    client = make_client()
    res = upload(client, sample_pdf)
    assert res.status_code == 202
    doc = res.json()
    # TestClient runs background tasks before returning, so indexing has finished.
    doc = client.get(f"/api/v1/documents/{doc['id']}").json()
    assert doc["status"] == "ready" and doc["page_count"] == 3 and doc["chunk_count"] > 0

    listing = client.get("/api/v1/documents").json()
    assert [d["id"] for d in listing["documents"]] == [doc["id"]]
    assert listing["limits"]["max_documents"] == 10

    chunks = client.get(f"/api/v1/documents/{doc['id']}/chunks").json()["chunks"]
    assert {c["page"] for c in chunks} == {1, 2, 3}

    pdf = client.get(f"/api/v1/documents/{doc['id']}/file")
    assert pdf.status_code == 200
    assert pdf.content == sample_pdf
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("inline")
    assert pdf.headers["x-content-type-options"] == "nosniff"


def test_search_returns_scored_passages_with_page_numbers(make_client, sample_pdf):
    client = make_client()
    doc_id = upload(client, sample_pdf).json()["id"]
    body = client.post("/api/v1/search", json={"query": "cache stampede cache-aside", "top_k": 2}).json()
    assert body["score_metric"] == "cosine_similarity"
    top = body["results"][0]
    assert top["rank"] == 1 and top["document_id"] == doc_id and top["page"] == 2
    assert top["score"] >= body["results"][1]["score"]
    assert abs(top["score"] + top["distance"] - 1) < 1e-3


def test_search_filtered_to_one_document(make_client, sample_pdf):
    client = make_client()
    a = upload(client, sample_pdf, "a.pdf").json()["id"]
    b = upload(client, make_pdf(["Completely different text about cache stampedes and caching layers."]), "b.pdf").json()["id"]
    body = client.post("/api/v1/search", json={"query": "cache stampede", "document_ids": [b], "top_k": 5}).json()
    assert {r["document_id"] for r in body["results"]} == {b}
    assert a != b


def test_chat_retrieval_only_without_key(make_client, sample_pdf):
    client = make_client()
    upload(client, sample_pdf)
    body = client.post("/api/v1/chat/query", json={"question": "When is a Raft log entry committed?"}).json()
    assert body["status"] == "retrieval_only"
    assert body["answer"] is None
    assert body["sources"][0]["ref_id"] == "S1"
    assert body["diagnostics"]["llm_called"] is False


def test_chat_with_llm_returns_trusted_citations(make_client, sample_pdf):
    client = make_client(llm=MockLLMProvider())
    doc_id = upload(client, sample_pdf).json()["id"]
    body = client.post("/api/v1/chat/query", json={"question": "When is a Raft log entry committed?"}).json()
    assert body["status"] == "answered"
    cit = body["citations"][0]
    assert cit["number"] == 1 and cit["document_id"] == doc_id and cit["page"] == 1 and cit["filename"] == "notes.pdf"
    assert "[1]" in body["answer"]


def test_diagnostics_can_be_disabled(make_client, sample_pdf):
    client = make_client(enable_diagnostics=False)
    upload(client, sample_pdf)
    assert client.post("/api/v1/chat/query", json={"question": "Raft"}).json()["diagnostics"] is None


def test_delete_removes_document_from_search(make_client, sample_pdf):
    client = make_client()
    keep = upload(client, make_pdf(["Another document about raft consensus and leaders and logs."]), "keep.pdf").json()["id"]
    gone = upload(client, sample_pdf).json()["id"]
    assert client.delete(f"/api/v1/documents/{gone}").json() == {"deleted": gone}
    results = client.post("/api/v1/search", json={"query": "raft log entry committed majority", "top_k": 10}).json()["results"]
    assert {r["document_id"] for r in results} == {keep}
    assert client.get(f"/api/v1/documents/{gone}").status_code == 404
    assert client.get(f"/api/v1/documents/{gone}/file").status_code == 404


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (b"just text", 415, "unsupported_file_type"),
        (b"%PDF-1.7\n" + b"\x00junk" * 40, 422, "pdf_corrupted"),
        (None, 422, "pdf_encrypted"),
        (make_image_only_pdf(), 422, "no_extractable_text"),
    ],
)
def test_upload_validation_errors(make_client, sample_pdf, data, status, code):
    client = make_client()
    res = upload(client, data if data is not None else encrypt_pdf(sample_pdf, "pw"))
    assert res.status_code == status
    body = res.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert "Traceback" not in res.text
    assert client.get("/api/v1/documents").json()["documents"] == []  # nothing half-stored


def test_empty_and_oversized_uploads(make_client):
    client = make_client(max_upload_mb=0.01)
    assert upload(client, b"").json()["error"]["code"] == "empty_file"
    big = upload(client, b"%PDF-1.4\n" + b"0" * 20_000)
    assert big.status_code == 413 and big.json()["error"]["code"] == "file_too_large"


def test_duplicate_upload_conflict(make_client, sample_pdf):
    client = make_client()
    first = upload(client, sample_pdf).json()["id"]
    dup = upload(client, sample_pdf, "copy.pdf")
    assert dup.status_code == 409
    assert dup.json()["error"]["details"]["document_id"] == first
    assert upload(client, sample_pdf, "copy.pdf", replace="true").status_code == 202


def test_path_traversal_in_document_id_is_not_found(make_client, sample_pdf):
    client = make_client()
    upload(client, sample_pdf)
    for doc_id in ("..%2F..%2Fdocumind.db", "..\\..\\documind.db", "%2e%2e"):
        res = client.get(f"/api/v1/documents/{doc_id}/file")
        assert res.status_code == 404
        assert res.headers["content-type"].startswith("application/json")


def test_request_validation_errors_use_the_error_shape(make_client, sample_pdf):
    client = make_client()
    upload(client, sample_pdf)
    for payload in ({"query": ""}, {"query": "x", "top_k": 0}, {"query": "x" * 2000}, {}):
        res = client.post("/api/v1/search", json=payload)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "validation_error"


def test_search_without_documents(make_client):
    res = make_client().post("/api/v1/search", json={"query": "anything"})
    assert res.status_code == 409
    assert res.json()["error"]["message"] == "No indexed documents are available. Upload a document first."


def test_read_only_mode(make_client, sample_pdf):
    client = make_client(read_only=True)
    res = upload(client, sample_pdf)
    assert res.status_code == 403 and res.json()["error"]["code"] == "read_only"
    loaded = client.post("/api/v1/demo/load").json()
    assert len(loaded["documents"]) == 5
    assert client.delete(f"/api/v1/documents/{loaded['documents'][0]['id']}").status_code == 403


def test_cors_only_allows_configured_origins(make_client):
    client = make_client(cors_origins=["http://localhost:5173"])
    ok = client.options("/api/v1/documents", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/v1/documents", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_openapi_documents_every_endpoint(make_client):
    paths = make_client().get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/documents/upload",
        "/api/v1/documents",
        "/api/v1/documents/{document_id}",
        "/api/v1/documents/{document_id}/file",
        "/api/v1/search",
        "/api/v1/chat/query",
        "/health",
    ):
        assert path in paths
