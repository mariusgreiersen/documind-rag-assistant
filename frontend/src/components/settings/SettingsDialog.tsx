import { Monitor, Moon, Sun } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type { Preferences, Theme } from '@/hooks/usePreferences'
import type { AppConfig } from '@/types/api'

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  prefs: Preferences
  onChange: (patch: Partial<Preferences>) => void
  config: AppConfig | null
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 py-3">
      <div>
        <p className="text-[13.5px] font-medium">{label}</p>
        {hint && <p className="text-[12px] text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  )
}

export function SettingsDialog({ open, onOpenChange, prefs, onChange, config }: SettingsDialogProps) {
  const themes: { value: Theme; icon: typeof Sun; label: string }[] = [
    { value: 'light', icon: Sun, label: 'Light' },
    { value: 'dark', icon: Moon, label: 'Dark' },
    { value: 'system', icon: Monitor, label: 'System' },
  ]
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>Preferences are stored in this browser only.</DialogDescription>
        </DialogHeader>

        <div className="divide-y">
          <Field label="Appearance">
            <div className="flex rounded-lg border p-0.5">
              {themes.map(({ value, icon: Icon, label }) => (
                <button
                  key={value}
                  onClick={() => onChange({ theme: value })}
                  className={cn(
                    'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12.5px] transition',
                    prefs.theme === value ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Icon className="size-3.5" /> {label}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Passages per question" hint="Top-K passages retrieved for each question">
            <select value={prefs.topK} onChange={(e) => onChange({ topK: Number(e.target.value) })} className="h-8 rounded-lg border bg-card px-2 text-[13px]">
              {[3, 5, 8, 10].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Retrieval diagnostics" hint={config?.diagnostics_enabled ? 'Show scores, timings and grounding checks' : 'Disabled by the server'}>
            <Switch checked={prefs.showDiagnostics && !!config?.diagnostics_enabled} disabled={!config?.diagnostics_enabled} onCheckedChange={(v) => onChange({ showDiagnostics: v })} />
          </Field>
        </div>

        {config && (
          <div className="rounded-xl bg-muted/50 p-3.5 text-[12px]">
            <p className="mb-2 font-medium">Server configuration</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-muted-foreground">
              <dt>Answer generation</dt>
              <dd className="text-foreground">{config.llm_configured ? `${config.llm_provider} · ${config.llm_model}` : 'Not configured (retrieval-only)'}</dd>
              <dt>Embedding model</dt>
              <dd className="font-mono text-foreground">
                {config.embedding_model} ({config.embedding_dimension}d)
              </dd>
              <dt>Chunking</dt>
              <dd className="text-foreground">
                {config.chunk_size_tokens} tokens, {config.chunk_overlap_tokens} overlap (model limit {config.max_input_tokens})
              </dd>
              <dt>Relevance gate</dt>
              <dd className="text-foreground">cosine ≥ {config.min_relevance_score}</dd>
              <dt>Workspace</dt>
              <dd className="text-foreground">{config.read_only ? 'Read-only demo' : 'Local, single user'}</dd>
              <dt>Version</dt>
              <dd className="text-foreground">{config.version}</dd>
            </dl>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
