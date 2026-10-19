import type { Citation, SearchResult, ViewerPassage } from '@/types/api'

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return formatDate(iso)
}

export const collapse = (text: string) => text.replace(/\s+/g, ' ').trim()

export function citationToPassage(c: Citation): ViewerPassage {
  return { ...c, label: `[${c.number}]` }
}

export function resultToPassage(r: SearchResult, label?: string): ViewerPassage {
  return { ...r, label: label ?? `#${r.rank}` }
}

/** Escape text for insertion as HTML (pdf.js text-layer renderer returns HTML strings). */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch] as string)
}

export function normalizeForMatch(text: string): string {
  return text.toLowerCase().replace(/\s+/g, ' ').trim()
}

/** Replace [n] markers that correspond to real citations with links the renderer turns into chips. */
export function linkCitations(answer: string, numbers: Set<number>): string {
  return answer.replace(/\[(\d+)\]/g, (match, n: string) => (numbers.has(Number(n)) ? `[${n}](#cite-${n})` : match))
}
