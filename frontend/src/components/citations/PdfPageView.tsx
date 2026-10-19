import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { escapeHtml, normalizeForMatch } from '@/lib/format'

// Must be configured in the module that renders react-pdf components.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

interface PdfPageViewProps {
  fileUrl: string
  page: number
  /** Passage to highlight on this page, if any. */
  highlight?: string
  onNumPages: (n: number) => void
}

/**
 * Renders one PDF page with a selectable text layer.
 *
 * Highlighting is approximate: pdf.js exposes text as positioned items (usually
 * one per line), and an item is marked when its text occurs inside the cited
 * passage. Items shorter than 8 characters are never marked, to avoid false
 * matches on common words. Text is HTML-escaped before it is inserted, because
 * the custom renderer returns HTML and PDF text is untrusted.
 */
export function PdfPageView({ fileUrl, page, highlight, onNumPages }: PdfPageViewProps) {
  const container = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(400)

  useEffect(() => {
    const el = container.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.floor(entry.contentRect.width))))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const target = useMemo(() => (highlight ? normalizeForMatch(highlight) : ''), [highlight])
  const renderText = useCallback(
    ({ str }: { str: string }) => {
      const safe = escapeHtml(str)
      const norm = normalizeForMatch(str)
      return target && norm.length >= 8 && target.includes(norm) ? `<mark>${safe}</mark>` : safe
    },
    [target],
  )

  const file = useMemo(() => ({ url: fileUrl }), [fileUrl])

  return (
    <div ref={container} className="pdf-page w-full">
      <Document
        file={file}
        onLoadSuccess={(pdf) => onNumPages(pdf.numPages)}
        loading={<Placeholder />}
        error={
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
            <AlertTriangle className="size-5" /> The PDF preview could not be loaded.
          </div>
        }
      >
        <Page
          key={`${fileUrl}-${page}`}
          pageNumber={page}
          width={width}
          renderAnnotationLayer={false}
          customTextRenderer={renderText}
          loading={<Placeholder />}
          className="overflow-hidden rounded-md shadow-sm ring-1 ring-black/5 dark:ring-white/10"
        />
      </Document>
    </div>
  )
}

function Placeholder() {
  return (
    <div className="grid aspect-[1/1.414] w-full place-items-center rounded-md bg-muted/60">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  )
}
