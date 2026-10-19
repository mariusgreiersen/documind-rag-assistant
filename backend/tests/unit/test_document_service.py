import pytest

from documind.core.errors import DocumentNotFound, DocumentNotReady, DuplicateDocument, NoDocumentsIndexed, ReadOnlyWorkspace, WorkspaceFull
from documind.documents.document_service import safe_display_name, title_from_filename
from documind.ingestion.pipeline import ChunkTooLargeForModel
from documind.models.domain import DocumentStatus
from tests.conftest import make_pdf


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\evil.pdf", "evil.pdf"),
        ("C:/Users/me/report.pdf", "report.pdf"),
        ("rep\x00ort<script>.pdf", "reportscript.pdf"),
        ("   ", "document.pdf"),
        (None, "document.pdf"),
        ("..", "document.pdf"),
    ],
)
def test_display_names_never_contain_paths(raw, expected):
    assert safe_display_name(raw) == expected


def test_title_from_filename():
    assert title_from_filename("raft_consensus-notes.pdf") == "raft consensus notes"


def test_upload_indexes_and_stores_file_under_generated_name(make_container, sample_pdf, settings):
    c = make_container()
    record = c.documents.upload(sample_pdf, "../../secret/notes.pdf")
    assert record.status == DocumentStatus.READY
    assert record.filename == "notes.pdf"
    assert record.title == "Systems Notes"  # from PDF metadata
    assert record.chunk_count == c.store.count(record.id) > 0
    stored = list(settings.uploads_dir.iterdir())
    assert [p.name for p in stored] == [f"{record.id}.pdf"]
    assert c.documents.file_path(record.id).read_bytes() == sample_pdf


def test_chunks_keep_document_and_page_metadata(make_container, sample_pdf):
    c = make_container()
    record = c.documents.upload(sample_pdf, "notes.pdf")
    chunks = c.documents.chunks(record.id)
    assert {ch.page_number for ch in chunks} == {1, 2, 3}
    assert all(ch.document_id == record.id and ch.filename == "notes.pdf" for ch in chunks)
    assert any("majority of servers" in ch.text for ch in chunks if ch.page_number == 1)


def test_duplicate_upload_is_rejected_unless_replaced(make_container, sample_pdf):
    c = make_container()
    first = c.documents.upload(sample_pdf, "a.pdf")
    with pytest.raises(DuplicateDocument) as exc:
        c.documents.upload(sample_pdf, "b.pdf")
    assert exc.value.details["document_id"] == first.id
    second = c.documents.upload(sample_pdf, "b.pdf", replace=True)
    assert second.id != first.id
    assert [d.id for d in c.documents.list_documents()] == [second.id]
    assert c.store.count(first.id) == 0


def test_workspace_limit(make_container):
    c = make_container(max_documents=2)
    for i in range(2):
        c.documents.upload(make_pdf([f"Document number {i} talks about topic {i} at length."]), f"{i}.pdf")
    with pytest.raises(WorkspaceFull):
        c.documents.upload(make_pdf(["A third document that should not fit in the workspace."]), "3.pdf")


def test_delete_removes_vectors_metadata_and_file(make_container, sample_pdf, settings):
    c = make_container()
    record = c.documents.upload(sample_pdf, "notes.pdf")
    path = c.documents.file_path(record.id)
    c.documents.delete(record.id)
    assert c.store.count(record.id) == 0
    assert not path.exists()
    with pytest.raises(DocumentNotFound):
        c.documents.get(record.id)
    with pytest.raises(NoDocumentsIndexed):
        c.documents.search_scope(None)


def test_search_scope_validation(make_container, sample_pdf):
    c = make_container()
    record = c.documents.upload(sample_pdf, "notes.pdf")
    assert c.documents.search_scope(None) == [record.id]
    assert c.documents.search_scope([record.id, record.id]) == [record.id]
    with pytest.raises(DocumentNotFound):
        c.documents.search_scope(["doc_missing"])


def test_processing_documents_are_not_searchable(make_container, sample_pdf):
    c = make_container()
    record, _ = c.documents.create_from_upload(sample_pdf, "notes.pdf")
    with pytest.raises(DocumentNotReady):
        c.documents.search_scope([record.id])
    with pytest.raises(NoDocumentsIndexed):
        c.documents.search_scope(None)


def test_failed_indexing_marks_document_failed_and_leaves_no_vectors(make_container, sample_pdf, embedder, monkeypatch):
    c = make_container()
    record, extracted = c.documents.create_from_upload(sample_pdf, "notes.pdf")

    def boom(texts):
        raise RuntimeError("embedding backend crashed")

    monkeypatch.setattr(embedder, "embed_documents", boom)
    result = c.documents.index(record.id, extracted)
    assert result.status == DocumentStatus.FAILED
    assert result.error
    assert c.store.count(record.id) == 0


def test_reconcile_repairs_interrupted_ingestion_and_orphans(make_container, sample_pdf, settings):
    c = make_container()
    record, _ = c.documents.create_from_upload(sample_pdf, "notes.pdf")  # never indexed: simulates a crash
    (settings.uploads_dir / "orphan.pdf").write_bytes(b"%PDF-1.4 leftover")
    summary = c.documents.reconcile()
    assert summary["interrupted"] == 1 and summary["orphan_files"] == 1
    assert c.documents.get(record.id).status == DocumentStatus.FAILED
    assert not (settings.uploads_dir / "orphan.pdf").exists()


def test_read_only_workspace_blocks_uploads_and_deletes_but_allows_demo(make_container, sample_pdf):
    c = make_container(read_only=True)
    with pytest.raises(ReadOnlyWorkspace):
        c.documents.upload(sample_pdf, "notes.pdf")
    loaded = c.documents.seed_demo()
    assert loaded and all(d.is_demo and d.status == DocumentStatus.READY for d in loaded)
    with pytest.raises(ReadOnlyWorkspace):
        c.documents.delete(loaded[0].id)


def test_seed_demo_is_idempotent(make_container):
    c = make_container()
    first = c.documents.seed_demo()
    assert len(first) == 5
    assert c.documents.seed_demo() == []
    assert {d.id for d in c.documents.list_documents()} == {d.id for d in first}


def test_chunk_size_larger_than_model_input_is_refused(make_container):
    c = make_container(chunk_size_tokens=300, chunk_overlap_tokens=30)  # fake model embeds 254 tokens
    with pytest.raises(ChunkTooLargeForModel):
        c.documents.validate_configuration()


def test_changed_chunking_configuration_triggers_reindex_on_startup(make_container, sample_pdf):
    c1 = make_container(chunk_size_tokens=64, chunk_overlap_tokens=8)
    record = c1.documents.upload(sample_pdf, "notes.pdf")
    c1.close()
    c2 = make_container(chunk_size_tokens=16, chunk_overlap_tokens=4)
    summary = c2.documents.reconcile()
    assert summary["reindexed"] == 1
    updated = c2.documents.get(record.id)
    assert updated.chunk_size_tokens == 16
    assert updated.chunk_count > record.chunk_count
    assert c2.store.count(record.id) == updated.chunk_count  # old, larger chunks are gone


def test_old_database_schema_is_migrated(tmp_path):
    import sqlite3

    from documind.documents.metadata_store import MetadataStore

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT, title TEXT, sha256 TEXT, size_bytes INTEGER, page_count INTEGER, "
        "status TEXT, created_at TEXT, stored_name TEXT, chunk_count INTEGER DEFAULT 0, text_page_count INTEGER DEFAULT 0, error TEXT, "
        "is_demo INTEGER DEFAULT 0, embedding_model TEXT, chunk_size_tokens INTEGER, chunk_overlap_tokens INTEGER, indexed_at TEXT)"
    )
    conn.execute(
        "INSERT INTO documents (id, filename, title, sha256, size_bytes, page_count, status, created_at, stored_name) "
        "VALUES ('d1', 'a.pdf', 'A', 'x', 1, 1, 'ready', '2026-01-01', 'd1.pdf')"
    )
    conn.commit()
    conn.close()
    store = MetadataStore(db)
    record = store.get("d1")
    assert record is not None and record.pipeline_version is None  # will be treated as stale and re-indexed
    store.close()


def test_metadata_persists_across_restarts(make_container, sample_pdf):
    c1 = make_container()
    record = c1.documents.upload(sample_pdf, "notes.pdf")
    c1.close()
    c2 = make_container()
    assert c2.documents.get(record.id).status == DocumentStatus.READY
    assert c2.store.count(record.id) == record.chunk_count
