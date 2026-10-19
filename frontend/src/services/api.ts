import type {
  ApiErrorBody,
  AppConfig,
  ChatResponse,
  DocumentInfo,
  DocumentList,
  HistoryMessage,
  SearchResponse,
  ChunkInfo,
} from '@/types/api'

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, init)
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the DocuMind server. Check that the backend is running.')
  }
  if (!res.ok) {
    let body: Partial<ApiErrorBody> = {}
    try {
      body = (await res.json()) as ApiErrorBody
    } catch {
      /* non-JSON error */
    }
    const err = body.error
    throw new ApiError(res.status, err?.code ?? 'http_error', err?.message ?? `Request failed (${res.status}).`, err?.details ?? {})
  }
  return (await res.json()) as T
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  config: () => request<AppConfig>('/api/v1/config'),
  listDocuments: () => request<DocumentList>('/api/v1/documents'),
  getDocument: (id: string) => request<DocumentInfo>(`/api/v1/documents/${encodeURIComponent(id)}`),
  chunks: (id: string) => request<{ document_id: string; chunks: ChunkInfo[] }>(`/api/v1/documents/${encodeURIComponent(id)}/chunks`),
  fileUrl: (id: string) => `${BASE}/api/v1/documents/${encodeURIComponent(id)}/file`,
  upload: (file: File, replace = false) => {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentInfo>(`/api/v1/documents/upload${replace ? '?replace=true' : ''}`, { method: 'POST', body: form })
  },
  deleteDocument: (id: string) => request<{ deleted: string }>(`/api/v1/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  loadDemo: () => request<{ loaded: DocumentInfo[]; documents: DocumentInfo[] }>('/api/v1/demo/load', { method: 'POST' }),
  search: (query: string, topK: number, documentIds?: string[]) =>
    request<SearchResponse>('/api/v1/search', json({ query, top_k: topK, document_ids: documentIds?.length ? documentIds : null })),
  ask: (question: string, topK: number, documentIds: string[] | undefined, history: HistoryMessage[]) =>
    request<ChatResponse>('/api/v1/chat/query', json({ question, top_k: topK, document_ids: documentIds?.length ? documentIds : null, history })),
}
