import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DocumentStatus } from '@/types/api'

const STYLES: Record<DocumentStatus, { label: string; className: string }> = {
  ready: { label: 'Ready', className: 'text-emerald-700 bg-emerald-50 ring-emerald-600/15 dark:text-emerald-300 dark:bg-emerald-400/10 dark:ring-emerald-400/20' },
  processing: { label: 'Processing', className: 'text-indigo-700 bg-indigo-50 ring-indigo-600/15 dark:text-indigo-300 dark:bg-indigo-400/10 dark:ring-indigo-400/20' },
  failed: { label: 'Failed', className: 'text-red-700 bg-red-50 ring-red-600/15 dark:text-red-300 dark:bg-red-400/10 dark:ring-red-400/20' },
}

export function StatusBadge({ status, className }: { status: DocumentStatus; className?: string }) {
  const style = STYLES[status]
  const Icon = status === 'ready' ? CheckCircle2 : status === 'processing' ? Loader2 : AlertCircle
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset', style.className, className)}>
      <Icon className={cn('size-3', status === 'processing' && 'animate-spin')} aria-hidden />
      {style.label}
    </span>
  )
}

/** Compact dot used in the dark sidebar. */
export function StatusDot({ status }: { status: DocumentStatus }) {
  if (status === 'processing') return <Loader2 className="size-3 shrink-0 animate-spin text-indigo-300" aria-label="Processing" />
  return (
    <span
      className={cn('size-1.5 shrink-0 rounded-full', status === 'ready' ? 'bg-emerald-400' : 'bg-red-400')}
      aria-label={status === 'ready' ? 'Ready' : 'Failed'}
    />
  )
}
