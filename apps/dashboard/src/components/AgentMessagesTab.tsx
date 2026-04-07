/**
 * P3: Raw channel messages tab. Polls /api/v2/agents/{id}/channel-messages.
 */
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface Msg {
  id: string
  channel: string
  author: string
  content: string
  message_type: string
  tickers: string[]
  posted_at: string | null
}

export function AgentMessagesTab({ agentId }: { agentId: string }) {
  const { data, isLoading } = useQuery<{ messages: Msg[]; count: number }>({
    queryKey: ['channel-messages', agentId],
    queryFn: async () =>
      (await api.get(`/api/v2/agents/${agentId}/channel-messages?limit=200`)).data,
    refetchInterval: 15000,
  })

  const messages = data?.messages ?? []

  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading…</div>
  if (messages.length === 0)
    return (
      <Card>
        <CardContent className="p-8 text-center text-muted-foreground text-sm">
          No channel messages yet. Make sure this agent has at least one Discord/Reddit
          connector attached via the connectors page.
        </CardContent>
      </Card>
    )

  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">{messages.length} messages (newest first)</div>
      {messages.map((m) => (
        <Card key={m.id}>
          <CardContent className="p-3">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-sm">{m.author || 'unknown'}</span>
                <Badge variant="outline" className="text-xs">
                  #{m.channel || 'general'}
                </Badge>
                {m.tickers?.map((t) => (
                  <Badge key={t} className="text-xs">
                    ${t}
                  </Badge>
                ))}
              </div>
              <span className="text-xs text-muted-foreground">
                {m.posted_at ? new Date(m.posted_at).toLocaleString() : ''}
              </span>
            </div>
            <div className="text-sm whitespace-pre-wrap">{m.content}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
