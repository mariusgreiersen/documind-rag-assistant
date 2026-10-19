import { useCallback, useRef, useState } from 'react'
import { CheckCircle2, FileUp, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, api } from '@/services/api'
import { formatBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DocumentInfo, WorkspaceLimits } from '@/types/api'

type ItemState =
  | { kind: 'uploading' }
  | { kind: 'processing'; doc: DocumentInfo }
  | { kind: 'ready'; doc: DocumentInfo }
  | { kind: 'failed'; message: string; duplicateOf?: string; file: File }

interface Item {
  key: string
  name: string
  size: number
  state: ItemState
}

interface UploadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  limits: WorkspaceLimits | null
  documents: DocumentInfo[]
  onUploaded: () => void
}

export function UploadDialog({ open, onOpenChange, limits, documents, onUploaded }: UploadDialogProps) {
  const [items, setItems] = useState<Item[]>([])
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  // Reflect real backend status for files that are still being indexed.
  const resolved = items.map((item) => {
    if (item.state.kind !== 'processing') return item
    const current = documents.find((d) => d.id === (item.state as { doc: DocumentInfo }).doc.id)
    if (current?.status === 'ready') return { ...item, state: { kind: 'ready', doc: current } as ItemState }
    if (current?.status === 'failed') return { ...item, state: { kind: 'failed', message: current.error ?? 'Indexing failed.', file: new File([], item.name) } as ItemState }
    return item
  })

  const setState = (key: string, state: ItemState) => setItems((xs) => xs.map((x) => (x.key === key ? { ...x, state } : x)))

  const uploadOne = useCallback(
    async (file: File, key: string, replace = false) => {
      setState(key, { kind: 'uploading' })
      try {
        const doc = await api.upload(file, replace)
        setState(key, { kind: 'processing', doc })
        onUploaded()
      } catch (e) {
        const err = e instanceof ApiError ? e : null
        setState(key, {
          kind: 'failed',
          message: err?.message ?? 'Upload failed.',
          duplicateOf: err?.code === 'duplicate_document' ? String(err.details.document_id ?? '') : undefined,
          file,
        })
      }
    },
    [onUploaded],
  )

  const addFiles = (files: FileList | File[]) => {
    const list = Array.from(files)
    const next = list.map((f, i) => ({ key: `${Date.now()}-${i}-${f.name}`, name: f.name, size: f.size, state: { kind: 'uploading' } as ItemState }))
    setItems((xs) => [...next, ...xs])
    // Upload sequentially: indexing is serialised on the server anyway.
    void (async () => {
      for (const [i, f] of list.entries()) await uploadOne(f, next[i].key)
    })()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Upload documents</DialogTitle>
          <DialogDescription>
            Text-based PDFs up to {limits?.max_upload_mb ?? 10} MB and {limits?.max_pages ?? 50} pages each, {limits?.max_documents ?? 10} documents per workspace. Scanned
            PDFs are not supported (no OCR).
          </DialogDescription>
        </DialogHeader>

        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            addFiles(e.dataTransfer.files)
          }}
          className={cn(
            'flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-9 text-center transition-colors',
            dragging ? 'border-primary bg-accent' : 'border-border hover:border-primary/50 hover:bg-muted/50',
          )}
        >
          <span className="grid size-10 place-items-center rounded-full bg-accent text-accent-foreground">
            <FileUp className="size-5" aria-hidden />
          </span>
          <span className="text-sm font-medium">Drop PDFs here or click to browse</span>
          <span className="text-xs text-muted-foreground">Files are validated by content, not by extension</span>
        </button>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) addFiles(e.target.files)
            e.target.value = ''
          }}
        />

        {resolved.length > 0 && (
          <ul className="max-h-64 space-y-2 overflow-y-auto">
            {resolved.map((item) => (
              <li key={item.key} className="flex items-start gap-3 rounded-lg border bg-card px-3 py-2.5">
                <ItemIcon state={item.state} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{item.name}</div>
                  <div className={cn('text-xs', item.state.kind === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>
                    {describe(item)}
                  </div>
                </div>
                {item.state.kind === 'failed' && item.state.duplicateOf && (
                  <Button size="xs" variant="outline" onClick={() => void uploadOne((item.state as { file: File }).file, item.key, true)}>
                    <RefreshCw /> Replace
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}

function ItemIcon({ state }: { state: ItemState }) {
  if (state.kind === 'ready') return <CheckCircle2 className="mt-0.5 size-4 text-emerald-600 dark:text-emerald-400" aria-label="Ready" />
  if (state.kind === 'failed') return <XCircle className="mt-0.5 size-4 text-destructive" aria-label="Failed" />
  return <Loader2 className="mt-0.5 size-4 animate-spin text-primary" aria-label="In progress" />
}

function describe(item: Item): string {
  const s = item.state
  switch (s.kind) {
    case 'uploading':
      return `Uploading and validating · ${formatBytes(item.size)}`
    case 'processing':
      return `Validated · ${s.doc.page_count} pages · chunking and embedding…`
    case 'ready':
      return `Ready · ${s.doc.page_count} pages · ${s.doc.chunk_count} chunks indexed`
    case 'failed':
      return s.message
  }
}
