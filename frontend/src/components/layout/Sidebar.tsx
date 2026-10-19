import { FileText, FlaskConical, LibraryBig, MessageSquare, MessageSquarePlus, Search, Settings, Trash2, Upload } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { Brand } from '@/components/layout/Brand'
import { StatusDot } from '@/components/documents/StatusBadge'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Conversation } from '@/hooks/useConversations'
import type { AppConfig, DocumentInfo } from '@/types/api'

export type View = 'chat' | 'search' | 'library'

interface SidebarProps {
  config: AppConfig | null
  documents: DocumentInfo[]
  selectedIds: Set<string>
  onToggleDocument: (id: string) => void
  onClearSelection: () => void
  onOpenDocument: (doc: DocumentInfo) => void
  conversations: Conversation[]
  activeConversationId: string | null
  onSelectConversation: (id: string) => void
  onDeleteConversation: (id: string) => void
  onNewChat: () => void
  onUpload: () => void
  onTryDemo: () => void
  demoLoading: boolean
  onOpenSettings: () => void
  view: View
  onViewChange: (view: View) => void
}

function NavButton({ active, icon: Icon, label, onClick, count }: { active: boolean; icon: typeof Search; label: string; onClick: () => void; count?: number }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors',
        active ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground',
      )}
    >
      <Icon className="size-4" aria-hidden />
      <span className="flex-1 text-left">{label}</span>
      {count !== undefined && <span className="text-[11px] tabular-nums text-sidebar-foreground/40">{count}</span>}
    </button>
  )
}

function SectionLabel({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between px-2.5 pb-1.5 pt-4">
      <span className="text-[11px] font-medium uppercase tracking-wider text-sidebar-foreground/40">{children}</span>
      {action}
    </div>
  )
}

export function Sidebar(props: SidebarProps) {
  const { config, documents, selectedIds, view } = props
  const readOnly = config?.read_only ?? false
  const readyCount = documents.filter((d) => d.status === 'ready').length
  const scopeLabel = selectedIds.size ? `${selectedIds.size} selected` : 'All documents'

  return (
    <aside className="flex h-full w-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="px-4 pb-3 pt-4">
        <Brand />
      </div>

      <div className="space-y-1.5 px-3">
        <button
          onClick={props.onNewChat}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-sidebar-primary px-3 py-2 text-[13px] font-medium text-sidebar-primary-foreground shadow-sm transition hover:brightness-110"
        >
          <MessageSquarePlus className="size-4" aria-hidden /> New chat
        </button>
        <button
          onClick={props.onUpload}
          disabled={readOnly}
          title={readOnly ? 'Uploads are disabled in this read-only demo' : undefined}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-sidebar-border bg-white/[0.03] px-3 py-2 text-[13px] font-medium text-sidebar-foreground/90 transition hover:bg-white/[0.07] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Upload className="size-4" aria-hidden /> Upload documents
        </button>
      </div>

      <nav className="mt-3 space-y-0.5 px-3" aria-label="Views">
        <NavButton active={view === 'chat'} icon={MessageSquare} label="Ask" onClick={() => props.onViewChange('chat')} />
        <NavButton active={view === 'search'} icon={Search} label="Semantic search" onClick={() => props.onViewChange('search')} />
        <NavButton active={view === 'library'} icon={LibraryBig} label="Document library" count={documents.length} onClick={() => props.onViewChange('library')} />
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3 [scrollbar-width:thin]">
        <SectionLabel
          action={
            selectedIds.size > 0 ? (
              <button onClick={props.onClearSelection} className="text-[11px] text-sidebar-foreground/50 hover:text-sidebar-foreground">
                Clear
              </button>
            ) : (
              <span className="text-[11px] text-sidebar-foreground/40">{scopeLabel}</span>
            )
          }
        >
          Documents
        </SectionLabel>
        {documents.length === 0 ? (
          <p className="px-2.5 py-2 text-[12px] leading-relaxed text-sidebar-foreground/45">No documents yet. Upload PDFs or try the demo.</p>
        ) : (
          <ul className="space-y-0.5">
            {documents.map((doc) => (
              <li key={doc.id} className="group flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-sidebar-accent/60">
                <Checkbox
                  checked={selectedIds.has(doc.id)}
                  onCheckedChange={() => props.onToggleDocument(doc.id)}
                  disabled={doc.status !== 'ready'}
                  aria-label={`Include ${doc.title} in questions`}
                  className="border-white/25 data-[state=checked]:border-sidebar-primary data-[state=checked]:bg-sidebar-primary"
                />
                <button onClick={() => props.onOpenDocument(doc)} className="flex min-w-0 flex-1 items-center gap-2 text-left" title={doc.title}>
                  <FileText className="size-3.5 shrink-0 text-sidebar-foreground/40" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] text-sidebar-foreground/85">{doc.title}</span>
                    <span className="block text-[10.5px] text-sidebar-foreground/40">
                      {doc.page_count} pages{doc.status === 'ready' ? ` · ${doc.chunk_count} chunks` : ''}
                      {doc.is_demo ? ' · demo' : ''}
                    </span>
                  </span>
                  <StatusDot status={doc.status} />
                </button>
              </li>
            ))}
          </ul>
        )}

        {props.conversations.length > 0 && (
          <>
            <SectionLabel>Recent conversations</SectionLabel>
            <ul className="space-y-0.5">
              {props.conversations.slice(0, 12).map((c) => (
                <li key={c.id} className="group relative">
                  <button
                    onClick={() => props.onSelectConversation(c.id)}
                    className={cn(
                      'w-full rounded-lg px-2.5 py-1.5 pr-8 text-left transition-colors',
                      c.id === props.activeConversationId && view === 'chat' ? 'bg-sidebar-accent' : 'hover:bg-sidebar-accent/60',
                    )}
                  >
                    <span className="block truncate text-[12.5px] text-sidebar-foreground/80">{c.title}</span>
                    <span className="block text-[10.5px] text-sidebar-foreground/35">{formatRelative(c.createdAt)}</span>
                  </button>
                  <button
                    onClick={() => props.onDeleteConversation(c.id)}
                    className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded p-1 text-sidebar-foreground/40 hover:text-sidebar-foreground group-hover:block"
                    aria-label={`Delete conversation ${c.title}`}
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="space-y-0.5 border-t border-sidebar-border px-3 py-3">
        {config?.demo_available && (
          <button
            onClick={props.onTryDemo}
            disabled={props.demoLoading}
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] text-sidebar-foreground/70 transition hover:bg-sidebar-accent/60 hover:text-sidebar-foreground disabled:opacity-50"
          >
            <FlaskConical className="size-4" aria-hidden />
            <span className="flex-1 text-left">{props.demoLoading ? 'Loading demo…' : 'Try demo'}</span>
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-sidebar-foreground/60">5 PDFs</span>
          </button>
        )}
        <button
          onClick={props.onOpenSettings}
          className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] text-sidebar-foreground/70 transition hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
        >
          <Settings className="size-4" aria-hidden />
          <span className="flex-1 text-left">Settings</span>
        </button>
        <div className="flex items-center gap-2 px-2.5 pt-2 text-[11px] text-sidebar-foreground/45">
          <span className={cn('size-1.5 rounded-full', config?.llm_configured ? 'bg-emerald-400' : 'bg-amber-400')} />
          {config ? (config.llm_configured ? `AI answers · ${config.llm_model}` : 'Retrieval-only mode') : 'Connecting…'}
          <span className="ml-auto tabular-nums">{readyCount} ready</span>
        </div>
      </div>
    </aside>
  )
}
