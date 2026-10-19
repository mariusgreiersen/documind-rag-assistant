import itertools

import pytest

from documind.ingestion.chunker import ChunkingConfig, WhitespaceTokenizer, chunk_document, chunk_page, make_chunk_id
from documind.models.domain import PageText

TOK = WhitespaceTokenizer()


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def sentences(n: int) -> str:
    return " ".join(f"Sentence number {i} has exactly seven words." for i in range(n))


def test_short_page_is_one_chunk():
    page = PageText(1, words(30))
    chunks = chunk_document("doc", [page], TOK, ChunkingConfig(chunk_size=50, chunk_overlap=5, min_chunk_tokens=5))
    assert len(chunks) == 1
    assert chunks[0].text == page.text


@pytest.mark.parametrize(("size", "overlap"), [(20, 0), (20, 5), (50, 10), (64, 16)])
def test_chunks_respect_size_and_cover_every_token(size, overlap):
    page = PageText(1, words(437))
    cfg = ChunkingConfig(chunk_size=size, chunk_overlap=overlap, min_chunk_tokens=3)
    chunks = chunk_document("doc", [page], TOK, cfg)
    covered = set()
    for c in chunks:
        assert c.token_count <= size
        assert len(c.text.split()) == c.token_count
        covered.update(c.text.split())
    assert covered == set(page.text.split())  # nothing is lost between chunks


def test_chunks_start_at_sentence_starts_when_one_is_near():
    page = PageText(1, sentences(60))
    chunks = chunk_document("doc", [page], TOK, ChunkingConfig(chunk_size=40, chunk_overlap=8, min_chunk_tokens=3))
    for c in chunks:
        assert c.text.startswith("Sentence number"), c.text[:30]
    for a, b in itertools.pairwise(chunks):
        assert a.char_end > b.char_start  # still overlapping


def test_consecutive_chunks_overlap_by_configured_tokens():
    page = PageText(1, words(200))
    chunks = chunk_document("doc", [page], TOK, ChunkingConfig(chunk_size=40, chunk_overlap=10, min_chunk_tokens=3))
    for a, b in itertools.pairwise(chunks):
        shared = set(a.text.split()) & set(b.text.split())
        assert len(shared) >= 10 or b is chunks[-1]


def test_chunk_text_is_an_exact_substring_of_the_page():
    page = PageText(4, sentences(40))
    for c in chunk_document("doc", [page], TOK, ChunkingConfig(chunk_size=30, chunk_overlap=6, min_chunk_tokens=3)):
        assert page.text[c.char_start : c.char_end] == c.text


def test_page_metadata_is_preserved_and_chunks_never_cross_pages():
    pages = [PageText(1, words(80, "a")), PageText(2, ""), PageText(3, words(80, "c"))]
    chunks = chunk_document("doc", pages, TOK, ChunkingConfig(chunk_size=30, chunk_overlap=5, min_chunk_tokens=3))
    assert {c.page_number for c in chunks} == {1, 3}
    for c in chunks:
        prefix = "a" if c.page_number == 1 else "c"
        assert all(w.startswith(prefix) for w in c.text.split())


def test_prefers_sentence_boundaries():
    page = PageText(1, sentences(30))
    chunks = chunk_document("doc", [page], TOK, ChunkingConfig(chunk_size=40, chunk_overlap=0, min_chunk_tokens=3))
    for c in chunks[:-1]:
        assert c.text.endswith("words."), c.text


def test_ids_are_deterministic_and_sequential():
    pages = [PageText(1, words(120)), PageText(2, words(120, "x"))]
    cfg = ChunkingConfig(chunk_size=50, chunk_overlap=10, min_chunk_tokens=3)
    first = chunk_document("doc-1", pages, TOK, cfg)
    second = chunk_document("doc-1", pages, TOK, cfg)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.chunk_index for c in first] == list(range(len(first)))
    assert first[0].chunk_id == make_chunk_id("doc-1", 1, 0) == "doc-1:p1:c0"
    assert len({c.chunk_id for c in first}) == len(first)


def test_duplicate_passages_are_dropped():
    boilerplate = "Confidential company report. Do not distribute outside the organisation under any circumstances."
    pages = [PageText(1, boilerplate), PageText(2, boilerplate), PageText(3, words(20))]
    chunks = chunk_document("doc", pages, TOK, ChunkingConfig(chunk_size=50, chunk_overlap=5, min_chunk_tokens=3))
    assert [c.page_number for c in chunks] == [1, 3]


def test_pages_below_minimum_length_produce_no_chunks():
    pages = [PageText(1, "Page 7"), PageText(2, words(40))]
    chunks = chunk_document("doc", pages, TOK, ChunkingConfig(chunk_size=50, chunk_overlap=5, min_chunk_tokens=5))
    assert [c.page_number for c in chunks] == [2]


def test_no_tiny_trailing_chunk():
    page = PageText(1, words(102))
    windows = chunk_page(page, TOK, ChunkingConfig(chunk_size=50, chunk_overlap=0, min_chunk_tokens=10))
    assert all(tokens >= 10 for _, _, tokens in windows)
    assert windows[-1][1] == len(page.text)


def test_subword_tokens_do_not_start_a_chunk_mid_word():
    class CharPairTokenizer:
        """Splits every word into two-character pieces, like a sub-word tokenizer."""

        def token_spans(self, text):
            spans, i = [], 0
            for word in text.split(" "):
                for j in range(0, len(word), 2):
                    spans.append((i + j, i + min(j + 2, len(word))))
                i += len(word) + 1
            return spans

    page = PageText(1, " ".join(["concurrency"] * 60))
    chunks = chunk_document("doc", [page], CharPairTokenizer(), ChunkingConfig(chunk_size=40, chunk_overlap=7, min_chunk_tokens=3))
    for c in chunks:
        assert c.text.startswith("concurrency"), c.text[:20]


@pytest.mark.parametrize(("size", "overlap", "min_tokens"), [(4, 0, 1), (20, 20, 1), (20, -1, 1), (20, 2, 0)])
def test_invalid_configuration_is_rejected(size, overlap, min_tokens):
    with pytest.raises(ValueError):
        ChunkingConfig(chunk_size=size, chunk_overlap=overlap, min_chunk_tokens=min_tokens)
