import { useCallback, useEffect, useState } from 'react'
import type { ChatResponse } from '@/types/api'

export interface UserTurn {
  id: string
  role: 'user'
  content: string
}

export interface AssistantTurn {
  id: string
  role: 'assistant'
  pending?: boolean
  response?: ChatResponse
  error?: string
}

export type Turn = UserTurn | AssistantTurn

export interface Conversation {
  id: string
  title: string
  createdAt: string
  turns: Turn[]
}

// Conversations live only in this browser (localStorage). The backend is stateless:
// each request carries a bounded slice of history for follow-up questions.
const KEY = 'documind.conversations.v1'
const MAX_CONVERSATIONS = 30

function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? (JSON.parse(raw) as Conversation[]) : []
    // Never restore a request that was in flight when the page closed.
    return parsed.map((c) => ({ ...c, turns: c.turns.filter((t) => !(t.role === 'assistant' && t.pending)) }))
  } catch {
    return []
  }
}

export const newId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36)

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>(load)
  const [activeId, setActiveId] = useState<string | null>(() => load()[0]?.id ?? null)

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(conversations.slice(0, MAX_CONVERSATIONS)))
    } catch {
      /* storage full or unavailable: conversations stay in memory */
    }
  }, [conversations])

  const active = conversations.find((c) => c.id === activeId) ?? null

  const startNew = useCallback(() => setActiveId(null), [])

  const ensureConversation = useCallback((firstQuestion: string): string => {
    const id = newId()
    const title = firstQuestion.length > 60 ? `${firstQuestion.slice(0, 57)}…` : firstQuestion
    setConversations((cs) => [{ id, title, createdAt: new Date().toISOString(), turns: [] }, ...cs])
    setActiveId(id)
    return id
  }, [])

  const updateTurns = useCallback((id: string, fn: (turns: Turn[]) => Turn[]) => {
    setConversations((cs) => cs.map((c) => (c.id === id ? { ...c, turns: fn(c.turns) } : c)))
  }, [])

  const remove = useCallback(
    (id: string) => {
      setConversations((cs) => cs.filter((c) => c.id !== id))
      if (activeId === id) setActiveId(null)
    },
    [activeId],
  )

  const clearActive = useCallback(() => {
    if (activeId) setConversations((cs) => cs.map((c) => (c.id === activeId ? { ...c, turns: [] } : c)))
  }, [activeId])

  return { conversations, active, activeId, setActiveId, startNew, ensureConversation, updateTurns, remove, clearActive }
}
