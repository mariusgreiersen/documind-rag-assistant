"""Application configuration, read from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/documind/core/config.py -> repository root is three levels above "documind".
REPO_ROOT = Path(__file__).resolve().parents[3]


# Query instructions recommended by the model authors for retrieval (passages get no prefix).
KNOWN_QUERY_PREFIXES = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-large-en-v1.5": "Represent this sentence for searching relevant passages: ",
}


def default_query_prefix(model: str) -> str:
    return KNOWN_QUERY_PREFIXES.get(model, "")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore", populate_by_name=True)

    # --- Application -------------------------------------------------------
    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    # Public demo deployments set this to true: uploads and deletions are disabled.
    read_only: bool = False
    # Exposes retrieval diagnostics (scores, rewritten queries, timings) in API responses.
    enable_diagnostics: bool = True
    seed_demo_on_startup: bool = False

    # --- Storage -----------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data" / "runtime"
    demo_dir: Path = REPO_ROOT / "data" / "demo"
    chroma_persist_dir: Path | None = None  # defaults to <data_dir>/chroma

    # --- Upload limits -----------------------------------------------------
    max_upload_mb: float = 10.0
    max_pages: int = 50
    max_documents: int = 10
    # Pages with fewer extractable characters than this count as "no text" (likely scanned).
    min_chars_per_page: int = 20
    # If fewer than this fraction of pages have text, the PDF is rejected as scanned.
    min_text_page_ratio: float = 0.5

    # --- Embeddings & chunking ----------------------------------------------
    embedding_provider: Literal["local"] = "local"
    # Chosen by measurement: see evals/results/experiments.md and docs/evaluation.md.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Instruction prefix added to queries only. None = the model's documented default
    # (see KNOWN_QUERY_PREFIXES); set "" to disable.
    embedding_query_prefix: str | None = None
    embedding_batch_size: int = 32
    embedding_device: str = "cpu"
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 60
    min_chunk_tokens: int = 24

    # --- Retrieval ---------------------------------------------------------
    default_top_k: int = 5
    max_top_k: int = 20
    # Cosine similarity below which the best retrieved passage is considered irrelevant
    # and the LLM is not called. Calibrated in evals/results (see docs/evaluation.md).
    min_relevance_score: float = 0.55
    max_question_chars: int = 1000

    # --- LLM ---------------------------------------------------------------
    llm_provider: Literal["anthropic", "mock", "none"] = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_api_key: SecretStr | None = None
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_max_tokens: int = 16000
    llm_timeout_seconds: float = 90.0
    # Server-side refusal fallback (Anthropic beta "server-side-fallback-2026-07-01").
    llm_refusal_fallback: bool = True
    max_context_chars: int = 24000
    max_history_turns: int = 6

    @model_validator(mode="after")
    def _derive(self) -> Settings:
        if self.chroma_persist_dir is None:
            self.chroma_persist_dir = self.data_dir / "chroma"
        if self.embedding_query_prefix is None:
            self.embedding_query_prefix = default_query_prefix(self.embedding_model)
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_SIZE_TOKENS")
        return self

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def metadata_db_path(self) -> Path:
        return self.data_dir / "documind.db"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    def resolved_llm_key(self) -> str | None:
        """LLM_API_KEY, falling back to the provider's conventional variable."""
        if self.llm_api_key and self.llm_api_key.get_secret_value():
            return self.llm_api_key.get_secret_value()
        if self.llm_provider == "anthropic":
            import os

            return os.environ.get("ANTHROPIC_API_KEY") or None
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
