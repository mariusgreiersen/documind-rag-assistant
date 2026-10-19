import { lazy, Suspense, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, ExternalLink, FileText, PanelRightClose, Quote } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DiagnosticsPanel } from '@/components/citations/DiagnosticsPanel'
import { api } from '@/services/api'
import { collapse } from '@/lib/format'
import type { ChatResponse, ViewerPassage } from '@/types/api'

// pdf.js is large; load it only when a document is opened.
const PdfPageView = lazy(() => import('@/components/citations/PdfPageView').then((m) => ({ default: m.PdfPageView })))

export interface ViewerState {
  documentId: string
  title: string
  filename: string
  page: number
  passages: ViewerPassage[]
  index: number
}

interface SourcePanelProps {
  viewer: ViewerState | null
  onChange: (viewer: ViewerState) => void
  onClose: () => void
  tab: 'source' | 'diagnostics'
  onTabChange: (tab: 'source' | 'diagnostics') => void
  diagnosticsFor: ChatResponse | null
  showDiagnostics: boolean
  onOpenSource: (response: ChatResponse, index: number) => void
}

export function SourcePanel({ viewer, onChange, onClose, tab, onTabChange, diagnosticsFor, showDiagnostics, onOpenSource }: SourcePanelProps) {
  const [pageCount, setPageCount] = useState<{ documentId: string; pages: number } | null>(null)
  const numPages = pageCount && pageCount.documentId === viewer?.documentId ? pageCount.pages : null
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const passage = viewer?.passages[viewer.index]
  const passageOnPage = passage && passage.document_id === viewer?.documentId && passage.page === viewer?.page

  const goToPassage = (index: number) => {
    if (!viewer) return
    const p = viewer.passages[index]
    onChange({ ...viewer, index, documentId: p.document_id, title: p.title, filename: p.filename, page: p.page })
  }

  return (
    <div className="flex h-full flex-col bg-card">
      <Tabs value={tab} onValueChange={(v) => onTabChange(v as 'source' | 'diagnostics')} className="flex min-h-0 flex-1 flex-col gap-0">
        <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b px-3">
          <TabsList>
            <TabsTrigger value="source">Source</TabsTrigger>
            {showDiagnostics && <TabsTrigger value="diagnostics">Diagnostics</TabsTrigger>}
          </TabsList>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close source panel">
            <PanelRightClose />
          </Button>
        </div>

        <TabsContent value="source" className="min-h-0 flex-1 overflow-y-auto">
          {!viewer ? (
            <div className="flex flex-col items-center gap-3 px-8 py-20 text-center">
              <span className="grid size-11 place-items-center rounded-full bg-accent text-accent-foreground">
                <Quote className="size-5" />
              </span>
              <p className="text-sm font-medium">Source viewer</p>
              <p className="text-[13px] leading-relaxed text-muted-foreground">
                Click a citation or a search result to open the original PDF page next to the extracted passage.
              </p>
            </div>
          ) : (
            <div className="space-y-4 p-4">
              {viewer.passages.length > 1 && (
                <div className="flex items-center justify-between rounded-lg bg-muted/60 px-2 py-1.5">
                  <Button variant="ghost" size="icon-xs" disabled={viewer.index === 0} onClick={() => goToPassage(viewer.index - 1)} aria-label="Previous passage">
                    <ChevronLeft />
                  </Button>
                  <span className="text-[12px] text-muted-foreground">
                    Passage <span className="font-medium text-foreground">{passage?.label}</span> · {viewer.index + 1} of {viewer.passages.length}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    disabled={viewer.index === viewer.passages.length - 1}
                    onClick={() => goToPassage(viewer.index + 1)}
                    aria-label="Next passage"
                  >
                    <ChevronRight />
                  </Button>
                </div>
              )}

              <div className="flex items-start gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-red-50 text-red-600 ring-1 ring-red-600/10 dark:bg-red-400/10 dark:text-red-300">
                  <FileText className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[14px] font-semibold leading-snug">{viewer.title}</h2>
                  <p className="truncate text-[12px] text-muted-foreground">{viewer.filename}</p>
                </div>
              </div>

              {passage && (
                <div className="rounded-xl border border-primary/20 bg-accent/50 p-3.5">
                  <div className="mb-2 flex items-center justify-between gap-2 text-[11.5px]">
                    <span className="font-medium text-accent-foreground">
                      {passage.label} Extracted passage · page {passage.page}
                    </span>
                    {passage.score !== undefined && <span className="font-mono text-muted-foreground">cos {passage.score.toFixed(3)}</span>}
                  </div>
                  <p className={`text-[13px] leading-relaxed ${expandedId === passage.chunk_id ? '' : 'line-clamp-6'}`}>{collapse(passage.text)}</p>
                  {passage.text.length > 420 && (
                    <button
                      onClick={() => setExpandedId(expandedId === passage.chunk_id ? null : passage.chunk_id)}
                      className="mt-1 text-[12px] font-medium text-primary hover:underline"
                    >
                      {expandedId === passage.chunk_id ? 'Show less' : 'Show full passage'}
                    </button>
                  )}
                  <p className="mt-2 truncate font-mono text-[10.5px] text-muted-foreground" title={passage.chunk_id}>
                    {passage.chunk_id}
                    {passage.char_start !== undefined && ` · chars ${passage.char_start}–${passage.char_end}`}
                  </p>
                </div>
              )}

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                  <Button variant="outline" size="icon-sm" disabled={viewer.page <= 1} onClick={() => onChange({ ...viewer, page: viewer.page - 1 })} aria-label="Previous page">
                    <ChevronLeft />
                  </Button>
                  <span className="min-w-[92px] text-center text-[12.5px] tabular-nums">
                    Page {viewer.page}
                    {numPages ? ` of ${numPages}` : ''}
                  </span>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={numPages !== null && viewer.page >= numPages}
                    onClick={() => onChange({ ...viewer, page: viewer.page + 1 })}
                    aria-label="Next page"
                  >
                    <ChevronRight />
                  </Button>
                </div>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="icon-sm" asChild aria-label="Open PDF in a new tab">
                    <a href={`${api.fileUrl(viewer.documentId)}#page=${viewer.page}`} target="_blank" rel="noreferrer">
                      <ExternalLink />
                    </a>
                  </Button>
                  <Button variant="ghost" size="icon-sm" asChild aria-label="Download PDF">
                    <a href={api.fileUrl(viewer.documentId)} download={viewer.filename}>
                      <Download />
                    </a>
                  </Button>
                </div>
              </div>

              <Suspense fallback={<div className="aspect-[1/1.414] w-full animate-pulse rounded-md bg-muted/60" />}>
                <PdfPageView
                  fileUrl={api.fileUrl(viewer.documentId)}
                  page={viewer.page}
                  highlight={passageOnPage ? passage?.text : undefined}
                  onNumPages={(pages) => setPageCount({ documentId: viewer.documentId, pages })}
                />
              </Suspense>
              {passageOnPage && (
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  Highlighting marks text lines that appear in the extracted passage. It is approximate; the extracted passage above is the exact cited text.
                </p>
              )}
            </div>
          )}
        </TabsContent>

        {showDiagnostics && (
          <TabsContent value="diagnostics" className="min-h-0 flex-1 overflow-y-auto">
            <DiagnosticsPanel response={diagnosticsFor} onOpenSource={(i) => diagnosticsFor && onOpenSource(diagnosticsFor, i)} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
