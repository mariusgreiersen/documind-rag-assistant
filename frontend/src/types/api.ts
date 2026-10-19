// Types mirroring the FastAPI response models (backend/documind/models/schemas.py).

export type DocumentStatus = 'processing' | 'ready' | 'failed'

export interface DocumentInfo {
  id: string
  filename: string
  title: string
  file_type: 'pdf'
  size_bytes: number
  page_count: number
  text_page_count: number
  chunk_count: number
  status: DocumentStatus
  error: string | null
  created_at: string
  indexed_at: string | null
  is_demo: boolean
  sha256: string
  embedding_model: string | null
  chunk_size_tokens: number | null
  chunk_overlap_tokens: number | null
}

export interface WorkspaceLimits {
  max_documents: number
  max_upload_mb: number
  max_pages: number
}

export interface DocumentList {
  documents: DocumentInfo[]
  limits: WorkspaceLimits
}

export interface ChunkInfo {
  chunk_id: string
  document_id: string
  page: number
  chunk_index: number
  text: string
  char_start: number
  char_end: number
}

export interface SearchResult {
  rank: number
  chunk_id: string
  document_id: string
  filename: string
  title: string
  page: number
  chunk_index: number
  text: string
  /** Cosine similarity between query and passage embeddings. Not a probability. */
  score: number
  distance: number
  char_start: number
  char_end: number
}

export interface SearchResponse {
  query: string
  top_k: number
  score_metric: 'cosine_similarity'
  embedding_model: string
  took_ms: number
  results: SearchResult[]
}

export type AnswerStatus = 'answered' | 'partially_answered' | 'insufficient_evidence' | 'retrieval_only' | 'generation_unavailable'

export interface Citation {
  number: number
  ref_id: string
  chunk_id: string
  document_id: string
  filename: string
  title: string
  page: number
  text: string
  score: number
  char_start: number
  char_end: number
}

export interface SourcePassage extends SearchResult {
  ref_id: string
}

export interface Diagnostics {
  question?: string
  search_query?: string
  query_rewritten?: boolean
  rewrite_ms?: number | null
  rewrite_error?: string | null
  top_k?: number
  documents_searched?: number
  retrieval_ms?: number
  embedding_ms?: number
  search_ms?: number
  generation_ms?: number
  top_score?: number | null
  min_relevance_score?: number
  passages_in_context?: number
  llm_called?: boolean
  gate?: string
  model_status?: string
  rejected_citation_ids?: string[]
  downgraded?: boolean
  downgrade_reason?: string | null
  citation_coverage?: number
  input_tokens?: number | null
  output_tokens?: number | null
  generation_error?: string
}

export interface ChatResponse {
  status: AnswerStatus
  answer: string | null
  citations: Citation[]
  sources: SourcePassage[]
  unsupported_aspects: string[]
  notice: string | null
  model: string | null
  diagnostics: Diagnostics | null
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface AppConfig {
  version: string
  llm_configured: boolean
  llm_provider: string | null
  llm_model: string | null
  embedding_model: string
  embedding_dimension: number
  max_seq_length: number
  max_input_tokens: number
  chunk_size_tokens: number
  chunk_overlap_tokens: number
  default_top_k: number
  min_relevance_score: number
  score_metric: 'cosine_similarity'
  read_only: boolean
  diagnostics_enabled: boolean
  demo_available: boolean
  limits: WorkspaceLimits
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}

/** A passage the source viewer can display: a citation, a retrieved source or a search hit. */
export interface ViewerPassage {
  document_id: string
  title: string
  filename: string
  page: number
  text: string
  chunk_id: string
  score?: number
  label?: string
  char_start?: number
  char_end?: number
}
