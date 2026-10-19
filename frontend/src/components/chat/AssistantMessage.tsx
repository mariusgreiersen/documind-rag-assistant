import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Activity, AlertTriangle, Check, CircleSlash, Copy, FileSearch, ShieldAlert, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { collapse, linkCitations } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { AnswerStatus, ChatResponse } from '@/types/api'
import type { AssistantTurn } from '@/hooks/useConversations'

const STATUS: Record<AnswerStatus, { label: string; icon: typeof Check; className: string }> = {
  answered: { label: 'Grounded answer', icon: Sparkles, className: 'text-emerald-700 bg-emerald-50 ring-emerald-600/15 dark:text-emerald-300 dark:bg-emerald-400/10' },
  partially_answered: { label: 'Partially answered', icon: AlertTriangle, className: 'text-amber-700 bg-amber-50 ring-amber-600/20 dark:text-amber-300 dark:bg-amber-400/10' },
  insufficient_evidence: { label: 'Insufficient evidence', icon: CircleSlash, className: 'text-slate-700 bg-slate-100 ring-slate-500/15 dark:text-slate-300 dark:bg-white/5' },
  retrieval_only: { label: 'Retrieval only · no AI answer', icon: FileSearch, className: 'text-indigo-700 bg-indigo-50 ring-indigo-600/15 dark:text-indigo-300 dark:bg-indigo-400/10' },
  generation_unavailable: { label: 'AI provider unavailable', icon: ShieldAlert, className: 'text-red-700 bg-red-50 ring-red-600/15 dark:text-red-300 dark:bg-red-400/10' },
}

interface AssistantMessageProps {
  turn: AssistantTurn
  onOpenCitation: (response: ChatResponse, citationNumber: number) => void
  onOpenSource: (response: ChatResponse, sourceIndex: number) => void
  onOpenDiagnostics: (response: ChatResponse) => void
  showDiagnostics: boolean
}

export function AssistantMessage({ turn, onOpenCitation, onOpenSource, onOpenDiagnostics, showDiagnostics }: AssistantMessageProps) {
  if (turn.pending) return <PendingMessage />
  if (turn.error || !turn.response) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-[13.5px] text-destructive">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        {turn.error ?? 'Something went wrong.'}
      </div>
    )
  }
  return (
    <ResponseView
      response={turn.response}
      onOpenCitation={onOpenCitation}
      onOpenSource={onOpenSource}
      onOpenDiagnostics={onOpenDiagnostics}
      showDiagnostics={showDiagnostics}
    />
  )
}

function PendingMessage() {
  return (
    <div className="flex items-center gap-3 py-2 text-[13px] text-muted-foreground" role="status" aria-live="polite">
      <span className="flex gap-1">
        <span className="dm-dot size-1.5 rounded-full bg-primary" />
        <span className="dm-dot size-1.5 rounded-full bg-primary" />
        <span className="dm-dot size-1.5 rounded-full bg-primary" />
      </span>
      Searching your documents and checking the evidence…
    </div>
  )
}

function ResponseView({
  response,
  onOpenCitation,
  onOpenSource,
  onOpenDiagnostics,
  showDiagnostics,
}: { response: ChatResponse } & Omit<AssistantMessageProps, 'turn'>) {
  const [copied, setCopied] = useState(false)
  const status = STATUS[response.status]
  const StatusIcon = status.icon
  const numbers = useMemo(() => new Set(response.citations.map((c) => c.number)), [response.citations])
  const markdown = useMemo(() => (response.answer ? linkCitations(response.answer, numbers) : ''), [response.answer, numbers])
  const showPassages = response.status === 'retrieval_only' || response.status === 'generation_unavailable'

  const copy = async () => {
    const sources = response.citations.map((c) => `[${c.number}] ${c.title}, page ${c.page}`).join('\n')
    await navigator.clipboard.writeText(`${response.answer ?? ''}${sources ? `\n\nSources:\n${sources}` : ''}`)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-medium ring-1 ring-inset', status.className)}>
          <StatusIcon className="size-3.5" aria-hidden />
          {status.label}
        </span>
        {response.model && <span className="text-[11px] text-muted-foreground">{response.model}</span>}
      </div>

      {response.notice && (
        <p className="rounded-lg border border-dashed bg-muted/40 px-3 py-2 text-[12.5px] leading-relaxed text-muted-foreground">{response.notice}</p>
      )}

      {response.answer && (
        <div className="answer-md text-foreground">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => {
                const match = href?.match(/^#cite-(\d+)$/)
                if (match) {
                  const n = Number(match[1])
                  const c = response.citations.find((x) => x.number === n)
                  return (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          data-citation
                          onClick={() => onOpenCitation(response, n)}
                          className="mx-0.5 inline-flex h-4.5 min-w-4.5 -translate-y-px items-center justify-center rounded-md bg-accent px-1 align-middle font-mono text-[10.5px] font-semibold text-accent-foreground ring-1 ring-inset ring-primary/20 transition hover:bg-primary hover:text-primary-foreground"
                          aria-label={`Open source ${n}: ${c?.title}, page ${c?.page}`}
                        >
                          {n}
                        </button>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-xs">
                        {c?.title} — page {c?.page}
                      </TooltipContent>
                    </Tooltip>
                  )
                }
                return (
                  <a href={href} target="_blank" rel="noreferrer noopener">
                    {children}
                  </a>
                )
              },
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      )}

      {response.unsupported_aspects.length > 0 && (
        <div className="rounded-lg border border-amber-500/25 bg-amber-50/60 px-3 py-2 text-[12.5px] dark:bg-amber-400/5">
          <p className="font-medium text-amber-800 dark:text-amber-300">Not supported by the documents</p>
          <ul className="mt-1 list-disc pl-4 text-amber-900/80 dark:text-amber-200/80">
            {response.unsupported_aspects.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {response.citations.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Sources</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {response.citations.map((c) => (
              <button
                key={c.number}
                onClick={() => onOpenCitation(response, c.number)}
                className="group flex items-start gap-2.5 rounded-xl border bg-card px-3 py-2.5 text-left shadow-xs transition hover:border-primary/40 hover:shadow-sm"
              >
                <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-md bg-accent font-mono text-[10.5px] font-semibold text-accent-foreground">{c.number}</span>
                <span className="min-w-0">
                  <span className="block truncate text-[12.5px] font-medium">{c.title}</span>
                  <span className="block text-[11.5px] text-muted-foreground">Page {c.page}</span>
                  <span className="mt-1 line-clamp-2 block text-[11.5px] leading-snug text-muted-foreground/90">“{collapse(c.text)}”</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {showPassages && response.sources.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Most relevant passages (semantic search)</p>
          <ol className="space-y-2">
            {response.sources.map((s, i) => (
              <li key={s.chunk_id}>
                <button
                  onClick={() => onOpenSource(response, i)}
                  className="w-full rounded-xl border bg-card px-3.5 py-3 text-left shadow-xs transition hover:border-primary/40 hover:shadow-sm"
                >
                  <div className="mb-1 flex items-center justify-between gap-3 text-[12px]">
                    <span className="flex min-w-0 items-baseline gap-1.5 font-medium">
                      <span className="text-muted-foreground">{i + 1}.</span>
                      <span className="truncate">{s.title}</span>
                      <span className="shrink-0 rounded bg-muted px-1.5 py-px text-[11px] font-normal text-muted-foreground">p. {s.page}</span>
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-muted-foreground" title="Cosine similarity (not a probability)">
                      cos {s.score.toFixed(3)}
                    </span>
                  </div>
                  <p className="line-clamp-3 text-[12.5px] leading-relaxed text-muted-foreground">{collapse(s.text)}</p>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="flex items-center gap-1 pt-0.5">
        {response.answer && (
          <Button variant="ghost" size="xs" onClick={() => void copy()} className="text-muted-foreground">
            {copied ? <Check /> : <Copy />} {copied ? 'Copied' : 'Copy'}
          </Button>
        )}
        {showDiagnostics && response.diagnostics && (
          <Button variant="ghost" size="xs" onClick={() => onOpenDiagnostics(response)} className="text-muted-foreground">
            <Activity /> Diagnostics
          </Button>
        )}
      </div>
    </div>
  )
}
