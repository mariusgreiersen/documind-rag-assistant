import { useEffect, useRef } from 'react'
import { ArrowRight, FileUp, FlaskConical, Gauge, Quote, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AssistantMessage } from '@/components/chat/AssistantMessage'
import { Composer } from '@/components/chat/Composer'
import { BrandMark } from '@/components/layout/Brand'
import type { Conversation } from '@/hooks/useConversations'
import type { AppConfig, ChatResponse, DocumentInfo } from '@/types/api'

const DEMO_QUESTIONS = [
  { q: 'Summarize the main ideas of the Raft lecture notes.', hint: 'Summary' },
  { q: 'Compare optimistic and pessimistic concurrency control.', hint: 'Comparison' },
  { q: 'What does the caching guide say about scalability?', hint: 'Topic search' },
  { q: 'Which page explains how Raft elects a leader?', hint: 'Page lookup' },
  { q: 'Is optimistic concurrency control always faster than locking?', hint: 'Conflicting sources' },
  { q: "What is Northwind's revenue in 2028?", hint: 'Not in the documents' },
]

const GENERIC_QUESTIONS = [
  { q: 'Summarize the main ideas of this document.', hint: 'Summary' },
  { q: 'What are the key findings or conclusions?', hint: 'Findings' },
  { q: 'Which page explains the main method or algorithm?', hint: 'Page lookup' },
  { q: 'What limitations does the document mention?', hint: 'Limitations' },
]

interface ChatViewProps {
  config: AppConfig | null
  documents: DocumentInfo[]
  conversation: Conversation | null
  busy: boolean
  scopeLabel: string
  onAsk: (question: string) => void
  onUpload: () => void
  onTryDemo: () => void
  demoLoading: boolean
  onOpenCitation: (response: ChatResponse, n: number) => void
  onOpenSource: (response: ChatResponse, index: number) => void
  onOpenDiagnostics: (response: ChatResponse) => void
  showDiagnostics: boolean
}

export function ChatView(props: ChatViewProps) {
  const { config, documents, conversation, busy } = props
  const bottom = useRef<HTMLDivElement>(null)
  const ready = documents.filter((d) => d.status === 'ready')
  const turns = conversation?.turns ?? []

  const lastTurn = turns[turns.length - 1]
  useEffect(() => {
    if (turns.length) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, lastTurn])

  const hasDemo = documents.some((d) => d.is_demo)
  const suggestions = hasDemo ? DEMO_QUESTIONS : GENERIC_QUESTIONS

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 pb-8 pt-6 sm:px-6">
          {documents.length === 0 ? (
            <Welcome onUpload={props.onUpload} onTryDemo={props.onTryDemo} demoLoading={props.demoLoading} config={config} />
          ) : turns.length === 0 ? (
            <div className="pt-[8vh]">
              <div className="mb-8 text-center">
                <BrandMark className="mx-auto mb-4 size-11" />
                <h1 className="text-2xl font-semibold tracking-tight">What would you like to know?</h1>
                <p className="mt-2 text-[14px] text-muted-foreground">
                  Answers use only your {ready.length} indexed document{ready.length === 1 ? '' : 's'} and cite the exact page they come from.
                </p>
              </div>
              <div className="grid gap-2.5 sm:grid-cols-2">
                {suggestions.map((s) => (
                  <button
                    key={s.q}
                    onClick={() => props.onAsk(s.q)}
                    disabled={busy || ready.length === 0}
                    className="group flex items-start justify-between gap-3 rounded-xl border bg-card px-4 py-3 text-left shadow-xs transition hover:border-primary/40 hover:shadow-sm disabled:opacity-50"
                  >
                    <span>
                      <span className="block text-[13.5px] leading-snug">{s.q}</span>
                      <span className="mt-1 block text-[11.5px] text-muted-foreground">{s.hint}</span>
                    </span>
                    <ArrowRight className="mt-0.5 size-4 shrink-0 text-muted-foreground/50 transition group-hover:translate-x-0.5 group-hover:text-primary" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-7">
              {turns.map((turn) =>
                turn.role === 'user' ? (
                  <div key={turn.id} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[14px] leading-relaxed text-primary-foreground shadow-sm">
                      {turn.content}
                    </div>
                  </div>
                ) : (
                  <div key={turn.id} className="flex gap-3">
                    <BrandMark className="mt-0.5 size-7 shrink-0 rounded-md" />
                    <div className="min-w-0 flex-1">
                      <AssistantMessage
                        turn={turn}
                        onOpenCitation={props.onOpenCitation}
                        onOpenSource={props.onOpenSource}
                        onOpenDiagnostics={props.onOpenDiagnostics}
                        showDiagnostics={props.showDiagnostics}
                      />
                    </div>
                  </div>
                ),
              )}
            </div>
          )}
          <div ref={bottom} />
        </div>
      </div>

      <div className="shrink-0 bg-gradient-to-t from-background via-background to-background/0 px-4 pb-4 pt-2 sm:px-6">
        <div className="mx-auto w-full max-w-3xl">
          <Composer
            onSubmit={props.onAsk}
            disabled={ready.length === 0}
            busy={busy}
            placeholder={ready.length ? 'Ask a question about your documents…' : 'Upload a document to start asking questions'}
            scopeLabel={props.scopeLabel}
          />
          <p className="mt-2 text-center text-[11px] text-muted-foreground">
            {config?.llm_configured
              ? 'Answers are generated only from retrieved passages and can still be wrong. Check the cited pages.'
              : 'Retrieval-only mode: no AI provider is configured, so you will see ranked passages instead of generated answers.'}
          </p>
        </div>
      </div>
    </div>
  )
}

function Welcome({ onUpload, onTryDemo, demoLoading, config }: { onUpload: () => void; onTryDemo: () => void; demoLoading: boolean; config: AppConfig | null }) {
  const features = [
    { icon: ShieldCheck, title: 'Grounded answers', text: 'Answers may only use passages retrieved from your PDFs. If the evidence is missing, DocuMind says so.' },
    { icon: Quote, title: 'Verified citations', text: 'Every citation is checked against the retrieved passages and opens the exact page.' },
    { icon: Gauge, title: 'Measured retrieval', text: 'Retrieval quality is benchmarked with Recall@K, Precision@K and MRR.' },
  ]
  return (
    <div className="pt-[9vh] text-center">
      <BrandMark className="mx-auto mb-5 size-12 rounded-xl" />
      <h1 className="text-3xl font-semibold tracking-tight sm:text-[34px]">Your documents, one intelligent workspace.</h1>
      <p className="mx-auto mt-3 max-w-xl text-[15px] leading-relaxed text-muted-foreground">
        Upload PDFs, search them by meaning and ask questions. Every answer links back to the page it came from.
      </p>
      <div className="mt-7 flex flex-wrap justify-center gap-2.5">
        <Button size="lg" onClick={onUpload} disabled={config?.read_only} className="h-10 px-4">
          <FileUp /> Upload PDFs
        </Button>
        {config?.demo_available && (
          <Button size="lg" variant="outline" onClick={onTryDemo} disabled={demoLoading} className="h-10 px-4">
            <FlaskConical /> {demoLoading ? 'Indexing demo documents…' : 'Try the demo'}
          </Button>
        )}
      </div>
      <div className="mt-12 grid gap-3 text-left sm:grid-cols-3">
        {features.map(({ icon: Icon, title, text }) => (
          <div key={title} className="rounded-xl border bg-card p-4 shadow-xs">
            <span className="mb-3 grid size-8 place-items-center rounded-lg bg-accent text-accent-foreground">
              <Icon className="size-4" />
            </span>
            <p className="text-[13.5px] font-medium">{title}</p>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{text}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
