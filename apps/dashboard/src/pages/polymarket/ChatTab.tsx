/**
 * ChatTab — Phase 15.7 (8th tab)
 * Conversational interface to the Prediction Markets agent.
 * Supports SSE streaming responses, persistent history, and context market selection.
 */
import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from 'sonner'
import { Send, Trash2 } from 'lucide-react'
import type { PMTopBet } from './TopBetsPanel'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PMChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string | null
}

// ---------------------------------------------------------------------------
// ChatTab (exported)
// ---------------------------------------------------------------------------

export function ChatTab() {
  const qc = useQueryClient()
  const [input, setInput] = useState('')
  const [localMessages, setLocalMessages] = useState<PMChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [contextMarketId, setContextMarketId] = useState<string>('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const historyLoaded = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  // Load chat history
  const { data: history = [] } = useQuery({
    queryKey: ['pm-chat-history'],
    queryFn: async () =>
      (await api.get<PMChatMessage[]>('/api/polymarket/chat/history')).data,
    staleTime: 0,
  })

  // Top bets for context selector (reuse cached query)
  const { data: topBets = [] } = useQuery({
    queryKey: ['pm-top-bets', 'all'],
    queryFn: async () =>
      (await api.get<PMTopBet[]>('/api/polymarket/top-bets')).data,
    staleTime: 60_000,
  })

  // Seed local state from history once
  useEffect(() => {
    if (!historyLoaded.current && history.length > 0) {
      setLocalMessages(history)
      historyLoaded.current = true
    }
  }, [history])

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [localMessages])

  // Cancel any in-flight SSE stream on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const clearHistory = useMutation({
    mutationFn: () => api.delete('/api/polymarket/chat/history'),
    onSuccess: () => {
      setLocalMessages([])
      historyLoaded.current = false
      qc.invalidateQueries({ queryKey: ['pm-chat-history'] })
      toast.success('Chat history cleared')
    },
    onError: () => toast.error('Failed to clear history'),
  })

  async function sendMessage() {
    const trimmed = input.trim()
    if (!trimmed || streaming) return

    // Append user message immediately
    const userMsg: PMChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: trimmed,
      created_at: new Date().toISOString(),
    }
    setLocalMessages((prev) => [...prev, userMsg])
    setInput('')
    setStreaming(true)

    // Reserve slot for assistant's streaming response
    const assistantId = crypto.randomUUID()
    setLocalMessages((prev) => [
      ...prev,
      { id: assistantId, role: 'assistant', content: '', created_at: new Date().toISOString() },
    ])

    // Abort any previous in-flight stream, then arm a fresh controller
    abortRef.current?.abort()
    abortRef.current = new AbortController()

    try {
      // Use the same base URL and token key as the centralised axios client
      const baseURL = api.defaults.baseURL ?? ''
      const token = localStorage.getItem('phoenix-v2-token')
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const body: Record<string, unknown> = { message: trimmed }
      if (contextMarketId) body.context_market_id = contextMarketId

      const response = await fetch(`${baseURL}/api/polymarket/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal: abortRef.current.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      if (!response.body) {
        // Non-streaming fallback: parse JSON directly
        const json = (await response.json()) as { response?: string; content?: string }
        const text = json.response ?? json.content ?? ''
        setLocalMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, content: text } : m)),
        )
      } else {
        // SSE streaming
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        try {
          // eslint-disable-next-line no-constant-condition
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() ?? ''

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue
              const raw = line.slice(6).trim()
              if (!raw || raw === '[DONE]') continue
              try {
                const parsed = JSON.parse(raw) as { chunk?: string; done?: boolean }
                if (parsed.chunk) {
                  setLocalMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, content: m.content + parsed.chunk }
                        : m,
                    ),
                  )
                }
                if (parsed.done) break
              } catch {
                // skip malformed SSE lines
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof Error && err.name === 'AbortError') {
            // user navigated away — silently stop
            return
          }
          // re-throw so the outer catch shows a toast for real failures
          throw err
        }
      }
    } catch (err) {
      toast.error('Chat error: ' + (err instanceof Error ? err.message : 'unknown'))
      // Remove the empty assistant placeholder on failure
      setLocalMessages((prev) => prev.filter((m) => m.id !== assistantId))
    } finally {
      setStreaming(false)
      qc.invalidateQueries({ queryKey: ['pm-chat-history'] })
    }
  }

  return (
    <div className="flex flex-col h-[620px] rounded-xl border border-border bg-card overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-muted/20 shrink-0">
        <span className="text-xs text-muted-foreground shrink-0">Context:</span>
        <select
          value={contextMarketId}
          onChange={(e) => setContextMarketId(e.target.value)}
          className="flex-1 max-w-xs rounded-md border border-border bg-background px-2 py-1 text-xs"
        >
          <option value="">— no market context —</option>
          {topBets.map((b) => (
            <option key={b.id} value={b.id}>
              {b.question.length > 60 ? b.question.slice(0, 60) + '…' : b.question}
            </option>
          ))}
        </select>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => clearHistory.mutate()}
          disabled={clearHistory.isPending || streaming}
          className="ml-auto gap-1 text-muted-foreground hover:text-destructive"
          title="Clear chat history"
        >
          <Trash2 className="h-4 w-4" />
          <span className="hidden sm:inline">Clear</span>
        </Button>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {localMessages.length === 0 && !streaming && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">
              Ask anything about Prediction Markets, top bets, or strategy…
            </p>
          </div>
        )}
        {localMessages.map((m) => (
          <div
            key={m.id}
            className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
          >
            <div
              className={cn(
                'max-w-[78%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
                m.role === 'user'
                  ? 'bg-primary text-primary-foreground rounded-br-sm'
                  : 'bg-muted text-foreground rounded-bl-sm',
              )}
            >
              {m.content || (
                // Animated typing dots while streaming
                <span className="inline-flex gap-1 items-center py-0.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce" />
                  <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:0.15s]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:0.3s]" />
                </span>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="flex items-center gap-2 px-4 py-3 border-t border-border shrink-0">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void sendMessage()
            }
          }}
          placeholder="Ask about markets, strategies, positions…"
          disabled={streaming}
          className="flex-1"
        />
        <Button
          onClick={() => void sendMessage()}
          disabled={!input.trim() || streaming}
          size="sm"
          className="shrink-0"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
