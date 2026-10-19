import { cn } from '@/lib/utils'

export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn('grid size-8 place-items-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 shadow-sm shadow-indigo-950/40', className)}>
      <svg viewBox="0 0 24 24" className="size-[18px] text-white" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M6 3h8l4 4v14H6z" />
        <path d="M14 3v4h4" />
        <circle cx="11.5" cy="13.5" r="2.5" />
        <path d="m13.5 15.5 2 2" />
      </svg>
    </span>
  )
}

export function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark />
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-sidebar-foreground">DocuMind</div>
        <div className="text-[11px] text-sidebar-foreground/50">Grounded document answers</div>
      </div>
    </div>
  )
}
