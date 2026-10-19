import { useState } from 'react'
import { Loader2, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, api } from '@/services/api'
import { collapse } from '@/lib/format'
import type { DocumentInfo, SearchResponse, SearchResult } from '@/types/api'

interface SearchViewProps {
  documents: DocumentInfo[]
  selectedIds: Set<string>
  scopeLabel: string
  topK: number
  onOpenResult: (results: SearchResult[], index: number) => void
}

export function SearchView({ documents, selectedIds, scopeLabel, topK, onOpenResult }: SearchViewProps) {
  const [query, setQuery] = useState('')
  const [k, setK] = useState(Math.max(topK, 5))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const ready = documents.some((d) => d.status === 'ready')

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    try {
      setResult(await api.search(query.trim(), k, [...selectedIds]))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Search failed.')
    } finally {
      setLoading(false)
    }
  }

  const max = result?.results[0]?.score ?? 1

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
        <h1 className="text-xl font-semibold tracking-tight">Semantic search</h1>
        <p className="mt-1 text-[13.5px] text-muted-foreground">
          Find passages by meaning, not just keywords. Works without an AI provider; results are ranked by cosine similarity between embeddings.
        </p>

        <form onSubmit={(e) => void run(e)} className="mt-5 flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. how do leaders keep followers from starting elections?"
              maxLength={1000}
              className="h-10 bg-card pl-9"
              aria-label="Search query"
            />
          </div>
          <div className="flex gap-2">
            <select
              value={k}
              onChange={(e) => setK(Number(e.target.value))}
              className="h-10 rounded-lg border bg-card px-2.5 text-[13px]"
              aria-label="Number of results"
            >
              {[3, 5, 10, 20].map((n) => (
                <option key={n} value={n}>
                  Top {n}
                </option>
              ))}
            </select>
            <Button type="submit" className="h-10 px-4" disabled={!ready || loading || !query.trim()}>
              {loading ? <Loader2 className="animate-spin" /> : <Search />} Search
            </Button>
          </div>
        </form>
        <p className="mt-2 text-[11.5px] text-muted-foreground">Scope: {scopeLabel}</p>

        {error && <p className="mt-6 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-[13px] text-destructive">{error}</p>}

        {result && (
          <div className="mt-6">
            <div className="mb-3 flex items-center justify-between text-[12px] text-muted-foreground">
              <span>
                {result.results.length} passages · {result.took_ms.toFixed(0)} ms
              </span>
              <span className="font-mono">{result.embedding_model}</span>
            </div>
            <ol className="space-y-2.5">
              {result.results.map((r, i) => (
                <li key={r.chunk_id}>
                  <button
                    onClick={() => onOpenResult(result.results, i)}
                    className="w-full rounded-xl border bg-card px-4 py-3 text-left shadow-xs transition hover:border-primary/40 hover:shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="flex min-w-0 items-baseline gap-1.5 text-[13px] font-medium">
                        <span className="text-muted-foreground">{r.rank}.</span>
                        <span className="truncate">{r.title}</span>
                        <span className="shrink-0 rounded bg-muted px-1.5 py-px text-[11px] font-normal text-muted-foreground">p. {r.page}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2" title="Cosine similarity: a ranking signal, not a probability">
                        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                          <span className="block h-full rounded-full bg-primary/70" style={{ width: `${Math.max(4, (r.score / max) * 100)}%` }} />
                        </span>
                        <span className="w-12 text-right font-mono text-[11.5px] text-muted-foreground">{r.score.toFixed(3)}</span>
                      </span>
                    </div>
                    <p className="mt-1.5 line-clamp-3 text-[12.5px] leading-relaxed text-muted-foreground">{collapse(r.text)}</p>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}
