# Architecture

DocuMind is a FastAPI backend with an explicit, framework-free RAG pipeline and a
React single-page app. Every pipeline stage is a small module with a narrow
interface, so each one is tested on its own and can be replaced independently.

## Components

```mermaid
flowchart LR
    subgraph Browser
        UI[React + TypeScript UI<br/>chat · search · library · source viewer]
    end
    subgraph Backend[FastAPI backend]
        API[REST API /api/v1<br/>thin route handlers]
        DS[DocumentService<br/>upload · index · delete · reconcile]
        R[Retriever]
        AS[AnswerService<br/>gate · generate · validate]
        CV[Citation validator]
        LLM[LLMProvider<br/>Anthropic · mock]
        EMB[EmbeddingProvider<br/>Sentence Transformers]
        VS[(ChromaDB<br/>persistent, cosine)]
        MD[(SQLite<br/>document metadata)]
        FS[(Managed file store<br/>&lt;doc_id&gt;.pdf)]
    end
    UI -->|JSON / multipart| API
    API --> DS & R & AS
    DS --> EMB & VS & MD & FS
    R --> EMB & VS
    AS --> R & LLM & CV
```

| Module | Responsibility | Depends on |
|---|---|---|
| `ingestion/pdf_parser.py` | Signature, structure, encryption, page-count and text checks; per-page extraction with pypdf | `cleaner` |
| `ingestion/cleaner.py` | Unicode normalisation, de-hyphenation, whitespace, removal of repeated headers/footers | — |
| `ingestion/chunker.py` | Token-aware, page-bounded chunks with character offsets and deterministic IDs | a `Tokenizer` |
| `ingestion/pipeline.py` | chunk → embed → index for one document; chunk-size guard | embedder, vector store |
| `embeddings/` | `EmbeddingProvider` protocol and the Sentence Transformers implementation | sentence-transformers |
| `vectorstore/chroma_store.py` | One collection per embedding model; add, query, filter, delete, count | chromadb |
| `documents/` | Document lifecycle and SQLite metadata (source of truth for status) | all of the above |
| `retrieval/retriever.py` | Query validation, query embedding, filtered similarity search | embedder, vector store |
| `generation/` | Prompts, LLM adapters, citation validation, answer orchestration | retriever, LLM |
| `evaluation/` | Benchmark dataset, metrics, baseline run and experiments | the production services |
| `api/` | HTTP layer: request validation, response models, error mapping | the services |

`container.py` wires the components together. Tests build the same container with
a fake embedder, an in-memory Chroma client or the mock LLM, without patching.

## Ingestion pipeline

```mermaid
flowchart LR
    U[Upload] --> V{Validate<br/>size · signature · structure<br/>encryption · pages · text}
    V -- rejected --> E[4xx with a clear message<br/>nothing is stored]
    V -- ok --> S[Store as &lt;doc_id&gt;.pdf<br/>status: processing]
    S --> X[Extract text per page]
    X --> C[Clean<br/>NFKC · de-hyphenate · headers/footers]
    C --> K[Chunk per page<br/>500 tokens · 60 overlap]
    K --> M[Embed<br/>bge-small-en-v1.5]
    M --> I[(ChromaDB)]
    I --> R[status: ready]
```

Validation runs synchronously, so an invalid file is rejected in the upload
response. Chunking, embedding and indexing run as a background task; the UI polls
the document status (`processing` → `ready` or `failed`).

## Question answering

```mermaid
sequenceDiagram
    participant UI
    participant API as /chat/query
    participant AS as AnswerService
    participant R as Retriever
    participant L as LLM
    participant V as Citation validator
    UI->>API: question, document_ids, top_k, history
    API->>AS: answer()
    opt follow-up question and LLM configured
        AS->>L: rewrite into a standalone search query
    end
    AS->>R: search(query, ready documents)
    R-->>AS: ranked chunks + cosine similarity
    alt top similarity < MIN_RELEVANCE_SCORE
        AS-->>API: insufficient_evidence (LLM not called)
    else no LLM configured
        AS-->>API: retrieval_only + passages
    else
        AS->>L: system rules + passages S1..Sk (untrusted) + question
        L-->>AS: JSON {status, answer with [S#], cited_source_ids}
        AS->>V: validate against S1..Sk
        V-->>AS: renumbered [1..n], rejected IDs, downgrade if uncited
        AS-->>API: answer + citations from backend metadata
    end
    API-->>UI: ChatResponse (+ diagnostics)
```

## Consistency and recovery

* **SQLite is the source of truth** for which documents exist and whether they are
  `ready`. Retrieval always filters by the current set of ready document IDs, so a
  half-indexed document can never contribute passages.
* **Deletion order** is vectors → metadata → file. If deleting vectors fails,
  nothing else changes. A file left behind by a later failure is harmless and is
  removed at the next startup.
* **Startup reconciliation** marks interrupted ingestions as failed, deletes orphan
  vectors and files, and **re-indexes documents whose embedding model, chunking
  configuration or ingestion pipeline version differs from the current one**.
* **One Chroma collection per embedding model** (`documind_<model>_<dim>`), with
  the model ID checked against the collection metadata on open. Vectors from
  different models are never compared.

## Data layout

```
data/
  demo/                 bundled sample PDFs + manifest.json + markdown sources
  runtime/              created at runtime (git-ignored, Docker volume)
    uploads/<doc_id>.pdf
    chroma/             persistent Chroma client
    documind.db         SQLite metadata
```

## Frontend

The React app keeps business logic out of components: API calls live in
`services/api.ts`, state in hooks (`useDocuments`, `useConversations`,
`usePreferences`), and components render. Conversations are stored in the
browser's localStorage; the backend is stateless and receives a bounded slice of
history with each question.
