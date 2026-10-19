import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Eraser, Info, Menu, PanelRight, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Sidebar, type View } from '@/components/layout/Sidebar'
import { ChatView } from '@/components/chat/ChatView'
import { SearchView } from '@/components/search/SearchView'
import { LibraryView } from '@/components/documents/LibraryView'
import { UploadDialog } from '@/components/documents/UploadDialog'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { SourcePanel, type ViewerState } from '@/components/citations/SourcePanel'
import { newId, useConversations, type Turn } from '@/hooks/useConversations'
import { useDocuments } from '@/hooks/useDocuments'
import { useMediaQuery, usePreferences } from '@/hooks/usePreferences'
import { ApiError, api } from '@/services/api'
import { citationToPassage, resultToPassage } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { AppConfig, ChatResponse, DocumentInfo, HistoryMessage, SearchResult, ViewerPassage } from '@/types/api'

const MAX_HISTORY_MESSAGES = 6

function historyFrom(turns: Turn[]): HistoryMessage[] {
  const messages: HistoryMessage[] = []
  for (const t of turns) {
    if (t.role === 'user') messages.push({ role: 'user', content: t.content })
    else if (t.response?.answer && t.response.status !== 'insufficient_evidence') messages.push({ role: 'assistant', content: t.response.answer })
  }
  return messages.slice(-MAX_HISTORY_MESSAGES)
}

export default function App() {
  const { prefs, update: updatePrefs } = usePreferences()
  const desktop = useMediaQuery('(min-width: 1024px)')
  const wide = useMediaQuery('(min-width: 1280px)')
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)
  const { documents, limits, refresh } = useDocuments()
  const convs = useConversations()

  const [view, setView] = useState<View>('chat')
  const [busy, setBusy] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [demoLoading, setDemoLoading] = useState(false)
  const [toast, setToast] = useState<{ kind: 'info' | 'error'; text: string } | null>(null)
  const [mobileNav, setMobileNav] = useState(false)

  const [panelOpen, setPanelOpen] = useState(true)
  const [panelTab, setPanelTab] = useState<'source' | 'diagnostics'>('source')
  const [viewer, setViewer] = useState<ViewerState | null>(null)
  const [diagnosticsFor, setDiagnosticsFor] = useState<ChatResponse | null>(null)

  const loadConfig = useCallback(() => {
    api
      .config()
      .then((c) => {
        setConfig(c)
        setConfigError(null)
      })
      .catch((e: unknown) => setConfigError(e instanceof Error ? e.message : 'Cannot reach the server.'))
  }, [])
  useEffect(loadConfig, [loadConfig])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 5000)
    return () => window.clearTimeout(t)
  }, [toast])

  // Only ready documents can be in scope; deleted or failed ones drop out automatically.
  const [rawSelected, setSelected] = useState<Set<string>>(new Set())
  const selected = useMemo(() => {
    const ready = new Set(documents.filter((d) => d.status === 'ready').map((d) => d.id))
    return new Set([...rawSelected].filter((id) => ready.has(id)))
  }, [rawSelected, documents])

  const showDiagnostics = prefs.showDiagnostics && (config?.diagnostics_enabled ?? false)
  const readyCount = documents.filter((d) => d.status === 'ready').length
  const scopeLabel = selected.size
    ? `Searching ${selected.size} selected document${selected.size === 1 ? '' : 's'}`
    : `Searching all ${readyCount} ready document${readyCount === 1 ? '' : 's'}`

  const openViewer = (passages: ViewerPassage[], index: number) => {
    const p = passages[index]
    setViewer({ documentId: p.document_id, title: p.title, filename: p.filename, page: p.page, passages, index })
    setPanelTab('source')
    setPanelOpen(true)
  }

  const openCitation = (response: ChatResponse, n: number) => {
    const passages = response.citations.map(citationToPassage)
    openViewer(passages, Math.max(0, response.citations.findIndex((c) => c.number === n)))
  }
  const openSource = (response: ChatResponse, index: number) =>
    openViewer(
      response.sources.map((s) => resultToPassage(s, s.ref_id)),
      index,
    )
  const openSearchResult = (results: SearchResult[], index: number) => openViewer(results.map((r) => resultToPassage(r)), index)
  const openDocument = (doc: DocumentInfo) => {
    if (doc.status === 'failed') return
    setViewer({ documentId: doc.id, title: doc.title, filename: doc.filename, page: 1, passages: [], index: 0 })
    setPanelTab('source')
    setPanelOpen(true)
    setMobileNav(false)
  }

  const ask = async (question: string) => {
    if (busy) return
    setView('chat')
    const previous = convs.active?.turns ?? []
    const convId = convs.active?.id ?? convs.ensureConversation(question)
    const userTurn: Turn = { id: newId(), role: 'user', content: question }
    const pendingId = newId()
    convs.updateTurns(convId, (ts) => [...ts, userTurn, { id: pendingId, role: 'assistant', pending: true }])
    setBusy(true)
    try {
      const res = await api.ask(question, prefs.topK, [...selected], historyFrom(previous))
      convs.updateTurns(convId, (ts) => ts.map((t) => (t.id === pendingId ? { id: pendingId, role: 'assistant', response: res } : t)))
      setDiagnosticsFor(res)
      if (panelOpen && desktop && res.citations.length) openCitation(res, res.citations[0].number)
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Something went wrong. Please try again.'
      convs.updateTurns(convId, (ts) => ts.map((t) => (t.id === pendingId ? { id: pendingId, role: 'assistant', error: message } : t)))
    } finally {
      setBusy(false)
    }
  }

  const loadDemo = async () => {
    setDemoLoading(true)
    try {
      const res = await api.loadDemo()
      await refresh()
      setView('chat')
      convs.startNew()
      setToast({ kind: 'info', text: res.loaded.length ? `Indexed ${res.loaded.length} demo documents.` : 'The demo documents are already in your workspace.' })
    } catch (e) {
      setToast({ kind: 'error', text: e instanceof ApiError ? e.message : 'Could not load the demo documents.' })
    } finally {
      setDemoLoading(false)
      setMobileNav(false)
    }
  }

  const deleteDocument = async (doc: DocumentInfo) => {
    try {
      await api.deleteDocument(doc.id)
      if (viewer?.documentId === doc.id) setViewer(null)
      await refresh()
      setToast({ kind: 'info', text: `Deleted “${doc.title}”.` })
    } catch (e) {
      setToast({ kind: 'error', text: e instanceof ApiError ? e.message : 'Delete failed.' })
    }
  }

  const focusDocument = (doc: DocumentInfo, target: View) => {
    setSelected(new Set([doc.id]))
    if (target === 'chat') convs.startNew()
    setView(target)
  }

  const title = useMemo(() => {
    if (view === 'search') return 'Semantic search'
    if (view === 'library') return 'Document library'
    return convs.active?.title ?? 'New conversation'
  }, [view, convs.active])

  const sidebar = (
    <Sidebar
      config={config}
      documents={documents}
      selectedIds={selected}
      onToggleDocument={(id) =>
        setSelected(() => {
          const next = new Set(selected)
          if (next.has(id)) next.delete(id)
          else next.add(id)
          return next
        })
      }
      onClearSelection={() => setSelected(new Set())}
      onOpenDocument={openDocument}
      conversations={convs.conversations}
      activeConversationId={convs.activeId}
      onSelectConversation={(id) => {
        convs.setActiveId(id)
        setView('chat')
        setMobileNav(false)
      }}
      onDeleteConversation={convs.remove}
      onNewChat={() => {
        convs.startNew()
        setView('chat')
        setMobileNav(false)
      }}
      onUpload={() => {
        setUploadOpen(true)
        setMobileNav(false)
      }}
      onTryDemo={() => void loadDemo()}
      demoLoading={demoLoading}
      onOpenSettings={() => setSettingsOpen(true)}
      view={view}
      onViewChange={(v) => {
        setView(v)
        setMobileNav(false)
      }}
    />
  )

  const panel = (
    <SourcePanel
      viewer={viewer}
      onChange={setViewer}
      onClose={() => setPanelOpen(false)}
      tab={panelTab}
      onTabChange={setPanelTab}
      diagnosticsFor={diagnosticsFor}
      showDiagnostics={showDiagnostics}
      onOpenSource={openSource}
    />
  )

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-dvh overflow-hidden bg-background">
        {desktop && <div className="w-[272px] shrink-0">{sidebar}</div>}

        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-3 backdrop-blur sm:px-4">
            {!desktop && (
              <Button variant="ghost" size="icon-sm" onClick={() => setMobileNav(true)} aria-label="Open navigation">
                <Menu />
              </Button>
            )}
            <h1 className="min-w-0 flex-1 truncate text-[14px] font-medium">{title}</h1>
            {view === 'chat' && convs.active && convs.active.turns.length > 0 && (
              <Button variant="ghost" size="sm" onClick={convs.clearActive} className="text-muted-foreground">
                <Eraser /> <span className="hidden sm:inline">Clear</span>
              </Button>
            )}
            <span
              className={cn(
                'hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] sm:inline-flex',
                config?.llm_configured ? 'text-muted-foreground' : 'border-amber-500/30 bg-amber-50 text-amber-800 dark:bg-amber-400/10 dark:text-amber-300',
              )}
            >
              <span className={cn('size-1.5 rounded-full', config?.llm_configured ? 'bg-emerald-500' : 'bg-amber-500')} />
              {config?.llm_configured ? 'AI answers on' : 'Retrieval-only'}
            </span>
            <Button
              variant={panelOpen && desktop ? 'secondary' : 'ghost'}
              size="icon-sm"
              onClick={() => setPanelOpen((o) => !o)}
              aria-label={panelOpen ? 'Hide source panel' : 'Show source panel'}
              aria-pressed={panelOpen}
            >
              <PanelRight />
            </Button>
          </header>

          {configError && (
            <div className="flex items-center gap-2 border-b border-destructive/20 bg-destructive/5 px-4 py-2 text-[13px] text-destructive">
              <AlertTriangle className="size-4" /> {configError}
              <Button size="xs" variant="outline" className="ml-auto" onClick={loadConfig}>
                Retry
              </Button>
            </div>
          )}

          <div className="min-h-0 flex-1">
            {view === 'chat' && (
              <ChatView
                config={config}
                documents={documents}
                conversation={convs.active}
                busy={busy}
                scopeLabel={scopeLabel}
                onAsk={(q) => void ask(q)}
                onUpload={() => setUploadOpen(true)}
                onTryDemo={() => void loadDemo()}
                demoLoading={demoLoading}
                onOpenCitation={openCitation}
                onOpenSource={openSource}
                onOpenDiagnostics={(r) => {
                  setDiagnosticsFor(r)
                  setPanelTab('diagnostics')
                  setPanelOpen(true)
                }}
                showDiagnostics={showDiagnostics}
              />
            )}
            {view === 'search' && (
              <SearchView documents={documents} selectedIds={selected} scopeLabel={scopeLabel} topK={prefs.topK} onOpenResult={openSearchResult} />
            )}
            {view === 'library' && (
              <LibraryView
                config={config}
                documents={documents}
                limits={limits}
                onUpload={() => setUploadOpen(true)}
                onOpen={openDocument}
                onAsk={(d) => focusDocument(d, 'chat')}
                onSearchWithin={(d) => focusDocument(d, 'search')}
                onDelete={deleteDocument}
              />
            )}
          </div>
        </main>

        {desktop && panelOpen && <div className={cn('shrink-0 border-l', wide ? 'w-[460px]' : 'w-[400px]')}>{panel}</div>}
      </div>

      {!desktop && (
        <>
          <Sheet open={mobileNav} onOpenChange={setMobileNav}>
            <SheetContent side="left" className="w-[290px] border-0 bg-sidebar p-0" showCloseButton={false}>
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              {sidebar}
            </SheetContent>
          </Sheet>
          <Sheet open={panelOpen && (viewer !== null || panelTab === 'diagnostics')} onOpenChange={setPanelOpen}>
            <SheetContent side="right" className="w-full p-0 sm:max-w-md" showCloseButton={false}>
              <SheetTitle className="sr-only">Source viewer</SheetTitle>
              {panel}
            </SheetContent>
          </Sheet>
        </>
      )}

      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} limits={limits} documents={documents} onUploaded={() => void refresh()} />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} prefs={prefs} onChange={updatePrefs} config={config} />

      {toast && (
        <div
          role="status"
          className={cn(
            'fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-xl border px-4 py-2.5 text-[13px] shadow-lg',
            toast.kind === 'error' ? 'border-destructive/30 bg-card text-destructive' : 'bg-card',
          )}
        >
          {toast.kind === 'error' ? <AlertTriangle className="size-4" /> : <Info className="size-4 text-primary" />}
          {toast.text}
          <button onClick={() => setToast(null)} aria-label="Dismiss" className="ml-1 text-muted-foreground hover:text-foreground">
            <X className="size-3.5" />
          </button>
        </div>
      )}
    </TooltipProvider>
  )
}
