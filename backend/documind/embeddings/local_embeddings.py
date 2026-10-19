"""Local embeddings with Sentence Transformers (no API key, runs on CPU)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from documind.core.errors import EmbeddingError
from documind.core.logging import log_event, timed
from documind.ingestion.chunker import Span

logger = logging.getLogger(__name__)


class SentenceTransformerEmbedder:
    """Wraps a ``SentenceTransformer`` model. The model is loaded lazily on first use."""

    def __init__(self, model_name: str, *, device: str = "cpu", batch_size: int = 32, query_prefix: str = "") -> None:
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._query_prefix = query_prefix
        self._model: Any = None
        self._lock = threading.Lock()

    # -- lazy loading ---------------------------------------------------------
    def _load(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer

                        with timed() as t:
                            model = SentenceTransformer(self._model_name, device=self._device)
                    except Exception as exc:
                        log_event(logger, "embedding_model_load_failed", logging.ERROR, model=self._model_name, error=repr(exc))
                        raise EmbeddingError() from exc
                    # Tokenising whole pages for chunking exceeds the model's input length by
                    # design. Silence that warning through logging; changing the tokenizer's
                    # model_max_length instead would also disable truncation inside encode().
                    logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)
                    self._model = model
                    log_event(logger, "embedding_model_loaded", model=self._model_name, ms=t["ms"], dim=self.dimension)
        return self._model

    @property
    def model_id(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        model = self._load()
        getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(getter())

    @property
    def max_seq_length(self) -> int:
        return int(self._load().max_seq_length)

    @property
    def max_input_tokens(self) -> int:
        """Content tokens that fit: ``max_seq_length`` minus special tokens such as [CLS]/[SEP]."""
        model = self._load()
        return self.max_seq_length - int(model.tokenizer.num_special_tokens_to_add(pair=False))

    def token_spans(self, text: str) -> list[Span]:
        encoded = self._load().tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return [(int(a), int(b)) for a, b in encoded["offset_mapping"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = self._load().encode(
                texts, batch_size=self._batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
            )
        except EmbeddingError:
            raise
        except Exception as exc:
            log_event(logger, "embedding_failed", logging.ERROR, count=len(texts), error=repr(exc))
            raise EmbeddingError() from exc
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([self._query_prefix + text])[0]
