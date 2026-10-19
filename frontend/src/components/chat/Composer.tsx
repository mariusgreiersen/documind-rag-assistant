import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ComposerProps {
  onSubmit: (text: string) => void
  disabled: boolean
  busy: boolean
  placeholder: string
  scopeLabel: string
  maxLength?: number
}

export function Composer({ onSubmit, disabled, busy, placeholder, scopeLabel, maxLength = 1000 }: ComposerProps) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [text])

  const submit = () => {
    const value = text.trim()
    if (!value || disabled || busy) return
    onSubmit(value)
    setText('')
  }

  return (
    <div className="rounded-2xl border bg-card shadow-sm transition focus-within:border-primary/40 focus-within:shadow-md focus-within:ring-3 focus-within:ring-primary/10">
      <textarea
        ref={ref}
        value={text}
        maxLength={maxLength}
        rows={1}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder={placeholder}
        aria-label="Question"
        className="block w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[14.5px] outline-none placeholder:text-muted-foreground/70 disabled:cursor-not-allowed"
      />
      <div className="flex items-center justify-between gap-3 px-3 pb-2.5 pt-1">
        <span className="truncate text-[11.5px] text-muted-foreground">{scopeLabel}</span>
        <div className="flex items-center gap-2">
          {text.length > maxLength * 0.8 && (
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {text.length}/{maxLength}
            </span>
          )}
          <button
            onClick={submit}
            disabled={disabled || busy || !text.trim()}
            className={cn(
              'grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm transition hover:brightness-110',
              'disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none',
            )}
            aria-label="Send question"
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
          </button>
        </div>
      </div>
    </div>
  )
}
