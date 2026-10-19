import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'

export interface Preferences {
  theme: Theme
  topK: number
  showDiagnostics: boolean
}

const KEY = 'documind.preferences.v1'
const DEFAULTS: Preferences = { theme: 'system', topK: 5, showDiagnostics: true }

function load(): Preferences {
  try {
    return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<Preferences>) }
  } catch {
    return DEFAULTS
  }
}

export function usePreferences() {
  const [prefs, setPrefs] = useState<Preferences>(load)

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs))
    } catch {
      /* ignore */
    }
  }, [prefs])

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const dark = prefs.theme === 'dark' || (prefs.theme === 'system' && media.matches)
      document.documentElement.classList.toggle('dark', dark)
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [prefs.theme])

  const update = (patch: Partial<Preferences>) => setPrefs((p) => ({ ...p, ...patch }))
  return { prefs, update }
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const listener = () => setMatches(media.matches)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [query])
  return matches
}
