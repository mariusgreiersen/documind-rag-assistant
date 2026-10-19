import { Activity, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ChatResponse } from '@/types/api'

function Row({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-[12.5px]">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn('text-right', mono && 'font-mono text-[11.5px]')}>{value ?? '—'}</span>
    </div>
  )
}

const ms = (v?: number | null) => (v === undefined || v === null ? '—' : `${v.toFixed(0)} ms`)

export function DiagnosticsPanel({ response, onOpenSource }: { response: ChatResponse | null; onOpenSource: (index: number) => void }) {
  if (!response) {
    return (
      <div className="flex flex-col items-center gap-2 px-6 py-16 text-center text-sm text-muted-foreground">
        <Activity className="size-5" />
        Ask a question, then open “Diagnostics” on an answer to inspect how it was retrieved.
      </div>
    )
  }
  const d = response.diagnostics
  if (!d) return <p className="p-6 text-sm text-muted-foreground">Diagnostics are disabled on this server.</p>

  const gated = d.gate === 'below_relevance_threshold'
  return (
    <div className="space-y-5 p-4">
      <section>
        <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Query</h3>
        <p className="rounded-lg bg-muted/60 px-3 py-2 text-[13px]">{d.question}</p>
        {d.query_rewritten && (
          <p className="mt-2 rounded-lg border border-dashed px-3 py-2 text-[12.5px]">
            <span className="text-muted-foreground">Rewritten for retrieval: </span>
            {d.search_query}
          </p>
        )}
      </section>

      <section className="divide-y rounded-lg border px-3">
        <Row label="Documents searched" value={d.documents_searched} />
        <Row label="Top-K" value={d.top_k} />
        <Row label="Passages in context" value={d.passages_in_context} />
        <Row label="Embedding" value={ms(d.embedding_ms)} />
        <Row label="Vector search" value={ms(d.search_ms)} />
        {d.rewrite_ms != null && <Row label="Query rewrite" value={ms(d.rewrite_ms)} />}
        <Row label="Generation" value={d.llm_called ? ms(d.generation_ms) : 'not called'} />
        {d.input_tokens != null && <Row label="Tokens (in / out)" value={`${d.input_tokens} / ${d.output_tokens}`} />}
      </section>

      <section className="rounded-lg border p-3">
        <div className="mb-2 flex items-center gap-2 text-[12.5px] font-medium">
          <ShieldCheck className="size-4 text-primary" /> Grounding checks
        </div>
        <Row
          label="Top cosine similarity"
          value={
            <span className={cn(gated && 'text-amber-600 dark:text-amber-400')}>
              {d.top_score?.toFixed(3) ?? '—'} {gated ? '<' : '≥'} {d.min_relevance_score?.toFixed(2)}
            </span>
          }
        />
        <Row label="Relevance gate" value={gated ? 'Blocked — LLM not called' : 'Passed'} />
        {d.llm_called && (
          <>
            <Row label="Model status" value={d.model_status} mono />
            <Row label="Rejected citation IDs" value={d.rejected_citation_ids?.length ? d.rejected_citation_ids.join(', ') : 'none'} mono />
            <Row label="Downgraded" value={d.downgraded ? d.downgrade_reason : 'no'} />
            <Row label="Sentence citation coverage" value={d.citation_coverage !== undefined ? `${Math.round(d.citation_coverage * 100)}%` : '—'} />
          </>
        )}
        {d.generation_error && <Row label="Generation error" value={d.generation_error} />}
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          Cosine similarity ranks passages; it is not a probability that a passage answers the question.
        </p>
      </section>

      <section>
        <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Retrieved chunks</h3>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-[12px]">
            <thead className="bg-muted/60 text-left text-muted-foreground">
              <tr>
                <th className="px-2.5 py-1.5 font-medium">Ref</th>
                <th className="px-2.5 py-1.5 font-medium">Score</th>
                <th className="px-2.5 py-1.5 font-medium">Document</th>
                <th className="px-2.5 py-1.5 font-medium">Page</th>
              </tr>
            </thead>
            <tbody>
              {response.sources.map((s, i) => {
                const cited = response.citations.some((c) => c.chunk_id === s.chunk_id)
                return (
                  <tr key={s.chunk_id} onClick={() => onOpenSource(i)} className="cursor-pointer border-t hover:bg-muted/40" title={s.chunk_id}>
                    <td className="px-2.5 py-1.5 font-mono">
                      {s.ref_id}
                      {cited && <span className="ml-1 rounded bg-accent px-1 text-[10px] text-accent-foreground">cited</span>}
                    </td>
                    <td className="px-2.5 py-1.5 font-mono tabular-nums">{s.score.toFixed(3)}</td>
                    <td className="max-w-[150px] truncate px-2.5 py-1.5">{s.title}</td>
                    <td className="px-2.5 py-1.5 tabular-nums">{s.page}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
