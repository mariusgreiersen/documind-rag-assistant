"""Document metadata in SQLite (standard library only).

SQLite is the source of truth for which documents exist and their processing
status. The vector store holds chunks and embeddings; retrieval is always
filtered to documents that this store reports as ``ready``.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import asdict, fields
from pathlib import Path

from documind.models.domain import DocumentRecord, DocumentStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id                   TEXT PRIMARY KEY,
    filename             TEXT NOT NULL,
    title                TEXT NOT NULL,
    sha256               TEXT NOT NULL,
    size_bytes           INTEGER NOT NULL CHECK (size_bytes > 0),
    page_count           INTEGER NOT NULL CHECK (page_count > 0),
    status               TEXT NOT NULL CHECK (status IN ('processing', 'ready', 'failed')),
    created_at           TEXT NOT NULL,
    stored_name          TEXT NOT NULL UNIQUE,
    chunk_count          INTEGER NOT NULL DEFAULT 0,
    text_page_count      INTEGER NOT NULL DEFAULT 0,
    error                TEXT,
    is_demo              INTEGER NOT NULL DEFAULT 0,
    embedding_model      TEXT,
    chunk_size_tokens    INTEGER,
    chunk_overlap_tokens INTEGER,
    indexed_at           TEXT,
    pipeline_version     TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents (sha256);
"""

_COLUMNS = [f.name for f in fields(DocumentRecord)]


class MetadataStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a database was created (additive migrations only)."""
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(documents)")}
        for column, ddl in (("pipeline_version", "TEXT"),):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> DocumentRecord:
        data = dict(row)
        data["status"] = DocumentStatus(data["status"])
        data["is_demo"] = bool(data["is_demo"])
        return DocumentRecord(**data)

    def insert(self, record: DocumentRecord) -> None:
        data = asdict(record)
        data["status"] = record.status.value
        data["is_demo"] = int(record.is_demo)
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        with self._lock:
            self._conn.execute(f"INSERT INTO documents ({', '.join(_COLUMNS)}) VALUES ({placeholders})", data)

    def update(self, document_id: str, **values: object) -> None:
        unknown = set(values) - set(_COLUMNS)
        if unknown:
            raise ValueError(f"unknown columns: {unknown}")
        if "status" in values and isinstance(values["status"], DocumentStatus):
            values["status"] = values["status"].value
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        with self._lock:
            self._conn.execute(f"UPDATE documents SET {assignments} WHERE id = :_id", {**values, "_id": document_id})

    def get(self, document_id: str) -> DocumentRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return self._to_record(row) if row else None

    def find_by_hash(self, sha256: str) -> DocumentRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM documents WHERE sha256 = ? LIMIT 1", (sha256,)).fetchone()
        return self._to_record(row) if row else None

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM documents ORDER BY created_at DESC, id").fetchall()
        return [self._to_record(r) for r in rows]

    def ready_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM documents WHERE status = 'ready'").fetchall()
        return [r["id"] for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
