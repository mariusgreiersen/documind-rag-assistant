"""Application errors with stable machine-readable codes and user-facing messages.

Every error returned by the API has the shape::

    {"error": {"code": "pdf_encrypted", "message": "...", "details": {...}}}

Messages are written for end users. Technical details are logged server-side and
never included in responses.
"""

from __future__ import annotations

from typing import Any


class DocuMindError(Exception):
    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


# --- Upload / ingestion -------------------------------------------------------
class UnsupportedFileType(DocuMindError):
    status_code = 415
    code = "unsupported_file_type"
    message = "Only PDF files are supported."


class FileTooLarge(DocuMindError):
    status_code = 413
    code = "file_too_large"


class EmptyFile(DocuMindError):
    code = "empty_file"
    message = "The uploaded file is empty."


class CorruptedPdf(DocuMindError):
    status_code = 422
    code = "pdf_corrupted"
    message = "This file could not be read as a PDF. It may be corrupted."


class EncryptedPdf(DocuMindError):
    status_code = 422
    code = "pdf_encrypted"
    message = "This PDF is password-protected. Remove the password and upload it again."


class TooManyPages(DocuMindError):
    status_code = 422
    code = "too_many_pages"


class NoExtractableText(DocuMindError):
    status_code = 422
    code = "no_extractable_text"
    message = "This PDF appears to contain scanned pages. OCR is not supported in the current version, so the text cannot be extracted."


class DuplicateDocument(DocuMindError):
    status_code = 409
    code = "duplicate_document"
    message = "This document has already been uploaded."


class WorkspaceFull(DocuMindError):
    status_code = 409
    code = "workspace_full"


class ReadOnlyWorkspace(DocuMindError):
    status_code = 403
    code = "read_only"
    message = "This is a read-only demo workspace. Uploading and deleting documents are disabled."


# --- Documents / retrieval ----------------------------------------------------
class DocumentNotFound(DocuMindError):
    status_code = 404
    code = "document_not_found"
    message = "Document not found."


class DocumentNotReady(DocuMindError):
    status_code = 409
    code = "document_not_ready"
    message = "This document is still being processed."


class NoDocumentsIndexed(DocuMindError):
    status_code = 409
    code = "no_documents"
    message = "No indexed documents are available. Upload a document first."


class InvalidQuery(DocuMindError):
    status_code = 422
    code = "invalid_query"


class VectorStoreError(DocuMindError):
    status_code = 503
    code = "vector_store_error"
    message = "The search index is temporarily unavailable."


class EmbeddingError(DocuMindError):
    status_code = 503
    code = "embedding_error"
    message = "The embedding model is unavailable."


# --- Generation ---------------------------------------------------------------
class LLMNotConfigured(DocuMindError):
    status_code = 503
    code = "llm_not_configured"
    message = "No AI provider is configured. You can still search your documents."


class LLMProviderError(DocuMindError):
    status_code = 503
    code = "llm_unavailable"
    message = "The AI provider is temporarily unavailable. You can still search your documents."
