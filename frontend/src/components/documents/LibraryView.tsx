import { useState } from 'react'
import { FileText, FileUp, MessageSquare, MoreHorizontal, Search, SquareArrowOutUpRight, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { StatusBadge } from '@/components/documents/StatusBadge'
import { formatBytes, formatDate } from '@/lib/format'
import type { AppConfig, DocumentInfo, WorkspaceLimits } from '@/types/api'

interface LibraryViewProps {
  config: AppConfig | null
  documents: DocumentInfo[]
  limits: WorkspaceLimits | null
  onUpload: () => void
  onOpen: (doc: DocumentInfo) => void
  onAsk: (doc: DocumentInfo) => void
  onSearchWithin: (doc: DocumentInfo) => void
  onDelete: (doc: DocumentInfo) => Promise<void>
}

export function LibraryView({ config, documents, limits, onUpload, onOpen, onAsk, onSearchWithin, onDelete }: LibraryViewProps) {
  const [pending, setPending] = useState<DocumentInfo | null>(null)
  const [deleting, setDeleting] = useState(false)
  const readOnly = config?.read_only ?? false

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Document library</h1>
            <p className="mt-1 text-[13.5px] text-muted-foreground">
              {documents.length} of {limits?.max_documents ?? '—'} documents · single-user local workspace
            </p>
          </div>
          <Button onClick={onUpload} disabled={readOnly}>
            <FileUp /> Upload
          </Button>
        </div>

        {documents.length === 0 ? (
          <div className="mt-10 rounded-2xl border border-dashed px-6 py-14 text-center">
            <p className="font-medium">Your documents, one intelligent workspace.</p>
            <p className="mt-1 text-[13px] text-muted-foreground">Upload text-based PDFs to index them for search and grounded answers.</p>
          </div>
        ) : (
          <div className="mt-6 overflow-x-auto rounded-xl border bg-card shadow-xs">
            <table className="w-full min-w-[680px] table-fixed text-[13px]">
              <colgroup>
                <col />
                <col className="w-14" />
                <col className="w-16" />
                <col className="w-18" />
                <col className="w-28" />
                <col className="w-28" />
                <col className="w-12" />
              </colgroup>
              <thead className="border-b bg-muted/40 text-left text-[11.5px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Document</th>
                  <th className="px-3 py-2.5 font-medium">Type</th>
                  <th className="px-3 py-2.5 text-right font-medium">Pages</th>
                  <th className="px-3 py-2.5 text-right font-medium">Chunks</th>
                  <th className="px-3 py-2.5 font-medium">Uploaded</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-3">
                      <button onClick={() => onOpen(doc)} className="flex w-full min-w-0 items-center gap-3 text-left" disabled={doc.status === 'failed'}>
                        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-red-50 text-red-600 dark:bg-red-400/10 dark:text-red-300">
                          <FileText className="size-4" />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{doc.title}</span>
                          <span className="block truncate text-[11.5px] text-muted-foreground">
                            {doc.filename} · {formatBytes(doc.size_bytes)}
                            {doc.is_demo && ' · demo'}
                          </span>
                          {doc.error && <span className="block text-[11.5px] text-destructive">{doc.error}</span>}
                        </span>
                      </button>
                    </td>
                    <td className="px-3 py-3 text-muted-foreground">PDF</td>
                    <td className="px-3 py-3 text-right tabular-nums">{doc.page_count}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{doc.status === 'ready' ? doc.chunk_count : '—'}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-muted-foreground">{formatDate(doc.created_at)}</td>
                    <td className="px-3 py-3">
                      <StatusBadge status={doc.status} />
                    </td>
                    <td className="px-3 py-3 text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${doc.title}`}>
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-48">
                          <DropdownMenuItem disabled={doc.status === 'failed'} onClick={() => onOpen(doc)}>
                            <SquareArrowOutUpRight /> Open document
                          </DropdownMenuItem>
                          <DropdownMenuItem disabled={doc.status !== 'ready'} onClick={() => onAsk(doc)}>
                            <MessageSquare /> Ask questions
                          </DropdownMenuItem>
                          <DropdownMenuItem disabled={doc.status !== 'ready'} onClick={() => onSearchWithin(doc)}>
                            <Search /> Search within
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem variant="destructive" disabled={readOnly} onClick={() => setPending(doc)}>
                            <Trash2 /> Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {config && (
          <p className="mt-4 text-[12px] text-muted-foreground">
            Indexed with <span className="font-mono">{config.embedding_model}</span> · {config.chunk_size_tokens}-token chunks with {config.chunk_overlap_tokens}-token overlap ·
            chunks never cross page boundaries.
          </p>
        )}
      </div>

      <Dialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete document?</DialogTitle>
            <DialogDescription>
              “{pending?.title}” will be removed together with its {pending?.chunk_count} indexed chunks and the stored PDF. Its passages will no longer appear in search or answers.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleting}
              onClick={async () => {
                if (!pending) return
                setDeleting(true)
                try {
                  await onDelete(pending)
                  setPending(null)
                } finally {
                  setDeleting(false)
                }
              }}
            >
              <Trash2 /> Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
