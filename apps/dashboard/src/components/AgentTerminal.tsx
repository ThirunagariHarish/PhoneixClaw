/**
 * P14: Simple WebSocket terminal to an agent's workdir.
 *
 * Avoids the xterm.js dependency — uses a scrollable pre + controlled input.
 * Backend is apps/api/src/routes/agent_terminal.py (admin-only, gated behind
 * ENABLE_AGENT_TERMINAL=1).
 */
import { useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Terminal as TerminalIcon } from 'lucide-react'

interface Props {
  agentId: string
}

export function AgentTerminal({ agentId }: Props) {
  const [lines, setLines] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const outRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const token = localStorage.getItem('phoenix_token') || ''
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = import.meta.env.VITE_API_HOST || window.location.host
    const url = `${proto}://${host}/api/v2/agents/${agentId}/terminal?token=${encodeURIComponent(token)}`

    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (e) {
      setLines((l) => [...l, `[error] ${(e as Error).message}`])
      return
    }
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => {
      setLines((l) => [...l, '[disconnected — terminal disabled or admin-only]'])
      setConnected(false)
    }
    ws.onmessage = (ev) => {
      setLines((l) => {
        const next = [...l, String(ev.data)]
        if (next.length > 500) return next.slice(-500)
        return next
      })
    }

    return () => {
      try {
        ws.close()
      } catch {
        // ignore
      }
    }
  }, [agentId])

  useEffect(() => {
    if (outRef.current) outRef.current.scrollTop = outRef.current.scrollHeight
  }, [lines])

  const send = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(input + '\n')
      setLines((l) => [...l, `$ ${input}`])
      setInput('')
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <TerminalIcon className="w-4 h-4" />
          Agent Shell
          <span
            className={`text-xs px-2 py-0.5 rounded ${
              connected ? 'bg-emerald-500/20 text-emerald-500' : 'bg-rose-500/20 text-rose-500'
            }`}
          >
            {connected ? 'connected' : 'offline'}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          ref={outRef}
          className="bg-zinc-950 text-zinc-100 text-xs font-mono p-3 rounded h-[400px] overflow-y-auto whitespace-pre-wrap"
        >
          {lines.length === 0 ? (
            <span className="text-zinc-500">
              Waiting for connection… (requires admin role + ENABLE_AGENT_TERMINAL=1)
            </span>
          ) : (
            lines.join('')
          )}
        </div>
        <div className="mt-2 flex gap-2">
          <Input
            placeholder="type a command…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') send()
            }}
            disabled={!connected}
            className="font-mono text-xs"
          />
        </div>
      </CardContent>
    </Card>
  )
}
