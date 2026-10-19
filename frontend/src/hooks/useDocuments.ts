import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/services/api'
import type { DocumentInfo, WorkspaceLimits } from '@/types/api'

/** Document list with polling while any document is still processing. */
export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [limits, setLimits] = useState<WorkspaceLimits | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      const list = await api.listDocuments()
      setDocuments(list.documents)
      setLimits(list.limits)
      setError(null)
      return list.documents
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load documents.')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial fetch from the backend (state is only set after the request resolves).
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void refresh()
  }, [refresh])

  const processing = documents.some((d) => d.status === 'processing')
  useEffect(() => {
    if (!processing) return
    timer.current = window.setInterval(() => void refresh(), 1500)
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [processing, refresh])

  return { documents, limits, loading, error, refresh, setDocuments }
}
