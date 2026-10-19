# The RAG pipeline in detail

This document explains each stage, the decisions behind it and the failure modes it
guards against. File references point to `backend/documind/`.

## 1. Extraction (`ingestion/pdf_parser.py`)

pypdf extracts text page by page. Page numbers are **1-based physical page
indices** (the first page of the file is page 1); printed page labels such as "iv"
are not used. Validation rejects:

| Condition | Error code | User message (abridged) |
|---|---|---|
| Not a PDF by content | `unsupported_file_type` | Only PDF files are supported |
| Over `MAX_UPLOAD_MB` | `file_too_large` | The file is larger than the 10 MB limit |
| Unreadable structure | `pdf_corrupted` | This file could not be read as a PDF |
| Password required | `pdf_encrypted` | This PDF is password-protected |
| More than `MAX_PAGES` | `too_many_pages` | The limit is 50 pages per document |
| Under half the pages have text | `no_extractable_text` | This PDF appears to contain scanned pages. OCR is not supported |

A page with fewer than 20 characters counts as having no text. An empty page keeps
its position, so later pages keep their numbers. If a single page fails to extract,
it becomes empty and a warning is recorded; the document is not failed.

**Limitations.** pypdf returns text in content-stream order. Multi-column layouts
can interleave columns, tables lose their structure, and text inside images is
invisible. Mathematical notation and unusual fonts can extract poorly. Scanned
PDFs are rejected rather than indexed empty.

## 2. Cleaning (`ingestion/cleaner.py`)

Applied per page, so page boundaries survive:

* NFKC Unicode normalisation (ligatures, full-width characters);
* removal of soft hyphens and control characters;
* joining words split by a line-end hyphen between lowercase letters. This is a
  heuristic: a compound hyphenated at a line break loses its hyphen;
* collapsing horizontal whitespace and dropping blank lines;
* **removing repeated page furniture.** A line of at most 80 characters that occurs
  on at least 60% of pages (and at least 3) is treated as a header, footer or page
  number and removed. Numbers are ignored when comparing lines of at most 25
  characters ("Page 3" ≡ "Page 4"); longer lines must match exactly, so content
  rows that differ only in their figures are kept.

Footers matter for retrieval. Before this step, every chunk of the demo corpus
began with "DocuMind demo corpus Page N", which added the same noise to every
embedding.

## 3. Chunking (`ingestion/chunker.py`)

* **Token-aware with the embedding model's own tokenizer.** Chunk sizes are
  counted in the same word pieces the model embeds.
* **Never larger than the model's input.** Sentence-transformer models silently
  truncate long inputs. With `all-MiniLM-L6-v2` (`max_seq_length` 256), a
  600-token passage embeds *identically* (cosine 1.000) to its first 300 tokens:
  everything after the cut has no influence on retrieval. The guard compares the
  chunk size against `max_seq_length` minus the `[CLS]`/`[SEP]` tokens, and the
  app refuses to start with a larger configuration. A test documents the
  truncation behaviour (`test_text_beyond_the_input_limit_does_not_affect_the_embedding`).
* **Page-bounded.** A chunk never crosses a page, so every chunk has exactly one
  page number and page citations are exact.
* **Exact substrings.** `chunk.text == page_text[char_start:char_end]`, which makes
  passages locatable for highlighting and lets the evaluation match evidence by
  character span.
* **Boundaries.** A chunk ends at the last sentence end (`.`, `!`, `?`) in the final
  30% of its window, if there is one. The next chunk starts about `overlap` tokens
  earlier, at a sentence start when one lies between half and twice the overlap,
  otherwise at a word start (never inside a word piece). A tiny final remainder is
  absorbed by making the last window full-size instead.
* **Deterministic IDs.** `<document_id>:p<page>:c<index>`. Re-indexing the same
  document with the same configuration reproduces the same IDs.
* Empty chunks and exact duplicates (by normalised SHA-256) are dropped.

Default: **500 tokens with 60 overlap**, chosen by measurement (see
[evaluation.md](evaluation.md)).

## 4. Embeddings (`embeddings/`)

Default model: **`BAAI/bge-small-en-v1.5`**, MIT licence, 384 dimensions, 512-token
input (510 content tokens), about 130 MB. It runs on CPU without an API key. Queries
get the model authors' retrieval instruction ("Represent this sentence for searching
relevant passages: "); passages do not. Embeddings are L2-normalised and batched
(`EMBEDDING_BATCH_SIZE`).

The spec's suggested starting point, `all-MiniLM-L6-v2` (Apache-2.0), was evaluated
too. Its 256-token limit rules out chunks in the 400–600-token range without
truncation. The comparison is in the experiments report.

**Consistency.** Vectors from different models live in different spaces and must
never be compared. The Chroma collection name contains the model ID and dimension,
the model ID is checked against the collection's metadata when it is opened, and
documents indexed with another model are re-indexed at startup.

## 5. Vector store (`vectorstore/chroma_store.py`)

ChromaDB `PersistentClient` with HNSW and the **cosine** space. Each record stores
the vector, the chunk text and metadata: document ID, filename, title, page, chunk
index, character span, token count, content hash, embedding model and indexing
time. Operations: upsert chunks, query with a `document_id` filter, list a
document's chunks, delete by document, and count.

**Scores.** Chroma returns cosine *distance* (1 − cosine similarity). The API
reports both `distance` and `score` = cosine similarity. A higher score means
closer, but **a score is not a probability that a passage is relevant or correct**.
Its scale depends on the model: off-topic questions score about 0.49 with
bge-small but about 0.1 with MiniLM.

## 6. Retrieval (`retrieval/retriever.py`)

Validate the query (non-empty, ≤ 1000 characters), embed it with the same model,
and run a top-K search restricted to documents whose status is `ready`, or to the
user's selection. Retrieval does not depend on the LLM and works without an API key
(`POST /api/v1/search`).

## 7. Relevance gate (`generation/answer_service.py`)

If the best passage's cosine similarity is below `MIN_RELEVANCE_SCORE`, the LLM is
not called and the response is `insufficient_evidence`; the closest passages are
still returned for inspection. The threshold is calibrated on the benchmark (0.55
for bge-small). It reliably catches **off-topic** questions only. On-topic but
unanswerable questions ("Northwind's revenue in **2028**") retrieve highly similar
passages, so they must be declined by the model and the validator.

## 8. Context construction (`generation/prompts.py`)

Retrieved chunks are labelled `S1…Sk` in rank order and trimmed to
`MAX_CONTEXT_CHARS`. The user message contains optional `<conversation_history>`,
`<sources>` with one `<source id="S2" document="…" page="4">` block per passage, and
the `<question>`. All untrusted text is escaped (see [security.md](security.md)).

**Follow-up questions.** When history is present and an LLM is configured, the
question is first rewritten into a standalone search query, so "Which of those
matter for scalability?" retrieves on the earlier topic. Retrieval always runs
again; history is never treated as evidence. Without an LLM, history is ignored.

## 9. Generation (`generation/llm_provider.py`)

`AnthropicProvider` calls the Messages API with structured outputs
(`output_config.format` = JSON schema):

```json
{"status": "answered | partially_answered | insufficient_evidence",
 "answer": "Markdown with inline [S#] markers",
 "cited_source_ids": ["S1", "S3"],
 "unsupported_aspects": ["…"]}
```

Configuration: `LLM_MODEL` (default `claude-opus-5-5`), `LLM_EFFORT` (default
`medium`), a timeout, and SDK retries for transient errors. The server-side refusal
fallback is enabled by default (`LLM_REFUSAL_FALLBACK`). Timeouts, authentication
errors, rate limits, refusals and truncated output map to a `generation_unavailable`
response that still includes the retrieved passages. Token usage reported by the API
is logged and shown in diagnostics.

`MockLLMProvider` produces deterministic, scriptable responses for tests.

> **Not verified live.** No API key was available while this was built, so the
> Anthropic adapter has been exercised by type checks and by the mocked pipeline,
> but not against the real API. See `tests/live/` to run it with a key.

## 10. Citation validation (`generation/citation_validator.py`)

1. Find every marker (`[S2]`, `[S1, S3]`, `[s2]`).
2. Keep markers whose ID was assigned to a retrieved passage; remove the rest and
   report them as `rejected_citation_ids`.
3. Renumber valid markers `[1]…[n]` by first appearance.
4. Build citations from **backend metadata** (document, title, page, chunk text),
   never from text the model wrote.
5. If the model listed valid IDs but placed no inline markers, attach them at the end.
6. If the status is `answered` or `partially_answered` but no valid citation
   remains, **downgrade to `insufficient_evidence`** and replace the text with the
   standard message.

A valid marker only proves the passage was in the context, not that it supports the
claim. Support is measured separately in the evaluation (cited-evidence precision
and manual review).
