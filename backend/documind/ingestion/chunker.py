"""Token-aware, page-aware chunking.

Design decisions:

* Tokens are counted with the *embedding model's own tokenizer*, so "256 tokens"
  means exactly what the embedding model will see. Sentence-transformer models
  truncate inputs longer than their ``max_seq_length``; a chunk larger than that
  would be silently cut off at embedding time, so the pipeline refuses such
  configurations unless truncation is explicitly allowed (used in experiments).
* A chunk never crosses a page boundary, so every chunk has exactly one page
  number and page-level citations stay reliable.
* Every chunk is an exact substring of the cleaned page text
  (``page.text[char_start:char_end]``), which makes passages locatable for
  highlighting and lets the evaluation match evidence by character span.
* Chunk ends prefer sentence boundaries in the last part of the window. The next
  chunk starts about ``overlap`` tokens earlier, preferably at a sentence start
  (the overlap may then vary between half and twice the configured value),
  otherwise at a word start.
* Chunk IDs are deterministic (document ID + page + sequence), so re-ingesting
  the same document with the same configuration reproduces the same IDs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from documind.models.domain import Chunk, PageText

Span = tuple[int, int]

_SENTENCE_END = (".", "!", "?")


class Tokenizer(Protocol):
    def token_spans(self, text: str) -> list[Span]:
        """Character offsets ``(start, end)`` of each token in ``text``."""
        ...


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = 256
    chunk_overlap: int = 32
    min_chunk_tokens: int = 24
    # Only search this final fraction of a window for a good boundary.
    boundary_search_fraction: float = 0.3

    def __post_init__(self) -> None:
        if self.chunk_size < 8:
            raise ValueError("chunk_size must be at least 8 tokens")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")
        if self.min_chunk_tokens < 1:
            raise ValueError("min_chunk_tokens must be positive")


def make_chunk_id(document_id: str, page_number: int, chunk_index: int) -> str:
    return f"{document_id}:p{page_number}:c{chunk_index}"


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def _is_word_start(text: str, spans: Sequence[Span], i: int) -> bool:
    """True if token ``i`` starts a new word (not a sub-word continuation)."""
    if i == 0:
        return True
    prev_end, start = spans[i - 1][1], spans[i][0]
    return start > prev_end or not text[start].isalnum() or not text[prev_end - 1].isalnum()


def _boundary_strength(text: str, spans: Sequence[Span], i: int) -> int:
    """How good it is to end a chunk after token ``i`` (0 = mid-sentence)."""
    if i + 1 >= len(spans):
        return 3
    end, next_start = spans[i][1], spans[i + 1][0]
    gap = text[end:next_start]
    if "\n" in gap and text[end - 1] in _SENTENCE_END:
        return 3
    if text[end - 1] in _SENTENCE_END and gap:
        return 2
    if "\n" in gap:
        return 1
    return 0


def _choose_end(text: str, spans: Sequence[Span], start: int, cfg: ChunkingConfig) -> int:
    """Exclusive token index at which the chunk starting at ``start`` ends."""
    n = len(spans)
    hard_end = min(start + cfg.chunk_size, n)
    if hard_end == n:
        return n
    floor = start + max(cfg.min_chunk_tokens, int(cfg.chunk_size * (1 - cfg.boundary_search_fraction)))
    best_i, best_strength = None, 0
    for i in range(hard_end - 1, max(floor, start) - 1, -1):
        strength = _boundary_strength(text, spans, i)
        if strength > best_strength:
            best_i, best_strength = i, strength
            if strength == 3:
                break
    return best_i + 1 if best_i is not None and best_strength >= 2 else hard_end


def _choose_next_start(text: str, spans: Sequence[Span], start: int, end: int, cfg: ChunkingConfig) -> int:
    """Token index where the chunk after ``[start, end)`` begins."""
    target = max(end - cfg.chunk_overlap, start + 1)
    if cfg.chunk_overlap > 0:
        lo = max(end - 2 * cfg.chunk_overlap, start + 1)
        hi = max(end - cfg.chunk_overlap // 2, lo)
        sentence_starts = [i for i in range(lo, hi + 1) if i < end and _boundary_strength(text, spans, i - 1) >= 2]
        if sentence_starts:
            return min(sentence_starts, key=lambda i: abs(i - target))
    while target < end and not _is_word_start(text, spans, target):
        target += 1
    return target


def chunk_page(
    page: PageText,
    tokenizer: Tokenizer,
    cfg: ChunkingConfig,
) -> list[tuple[int, int, int]]:
    """Split one page into ``(char_start, char_end, token_count)`` windows."""
    text = page.text
    spans = [s for s in tokenizer.token_spans(text) if s[1] > s[0]]
    n = len(spans)
    if n < cfg.min_chunk_tokens:
        return []

    windows: list[tuple[int, int, int]] = []
    start = 0
    while start < n:
        end = _choose_end(text, spans, start, cfg)
        windows.append((spans[start][0], spans[end - 1][1], end - start))
        if end >= n:
            break
        next_start = _choose_next_start(text, spans, start, end, cfg)
        # Avoid a tiny trailing chunk: make the final window a full-size window instead.
        if n - next_start < cfg.chunk_size and n - end < cfg.min_chunk_tokens:
            tail_start = max(n - cfg.chunk_size, start + 1)
            while tail_start < n and not _is_word_start(text, spans, tail_start):
                tail_start += 1
            if tail_start < end:
                windows.append((spans[tail_start][0], spans[n - 1][1], n - tail_start))
                break
        start = next_start
    return windows


def chunk_document(
    document_id: str,
    pages: Iterable[PageText],
    tokenizer: Tokenizer,
    cfg: ChunkingConfig,
) -> list[Chunk]:
    """Chunk every page of a document, dropping empty and duplicate passages."""
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for page in pages:
        if not page.text:
            continue
        for char_start, char_end, token_count in chunk_page(page, tokenizer, cfg):
            text = page.text[char_start:char_end]
            digest = content_hash(text)
            if not text.strip() or digest in seen:
                continue
            seen.add(digest)
            index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(document_id, page.page_number, index),
                    document_id=document_id,
                    page_number=page.page_number,
                    chunk_index=index,
                    text=text,
                    char_start=char_start,
                    char_end=char_end,
                    token_count=token_count,
                    content_hash=digest,
                )
            )
    return chunks


class WhitespaceTokenizer:
    """Dependency-free tokenizer (one token per whitespace-separated word). Used in tests."""

    def token_spans(self, text: str) -> list[Span]:
        spans: list[Span] = []
        start = None
        for i, ch in enumerate(text):
            if ch.isspace():
                if start is not None:
                    spans.append((start, i))
                    start = None
            elif start is None:
                start = i
        if start is not None:
            spans.append((start, len(text)))
        return spans
