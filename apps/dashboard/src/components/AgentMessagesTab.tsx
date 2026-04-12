/**
 * P3: Raw channel messages tab. Polls /api/v2/agents/{id}/channel-messages.
 * Auto-backfills on first load when connectors exist but no messages yet.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
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

interface AgentDetail {
  id: string
  config?: {
    connector_ids?: unknown[]
    selected_channel?: { channel_id?: string }
  }
}

function feedLooksConfigured(agent: AgentDetail | undefined): boolean {
  if (!agent?.config) return false
  const ids = agent.config.connector_ids
  if (Array.isArray(ids) && ids.length > 0) return true
  const ch = agent.config.selected_channel
  if (ch && typeof ch === 'object' && ch.channel_id != null && String(ch.channel_id).trim() !== '')
    return true
  return false
}

export function AgentMessagesTab({ agentId }: { agentId: string }) {
  const backfillAttemptedRef = useRef<boolean>(false)
  const [backfillWarning, setBackfillWarning] = useState<string | null>(null)

  const { data: agentData } = useQuery<AgentDetail>({
    queryKey: ['agent', agentId],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}`)).data,
  })

  const { data, isLoading } = useQuery<{
    messages: Msg[]
    count: number
    connector_ids?: string[]
    has_connectors?: boolean
    ingestion?: { running?: boolean; summary?: string } | null
    error?: string
  }>({
    queryKey: ['channel-messages', agentId],
    queryFn: async () =>
      (await api.get(`/api/v2/agents/${agentId}/channel-messages?limit=200`)).data,
    refetchInterval: 15000,
  })

  const backfillMut = useMutation({
    mutationFn: async () =>
      (await api.post(`/api/v2/agents/${agentId}/channel-messages/backfill?limit=100`)).data,
    onSuccess: (result: { backfilled?: number; errors?: string[] | null; error?: string }) => {
      if (result?.error || (Array.isArray(result?.errors) && result.errors.length > 0) || result?.backfilled === 0) {
        const detail = result?.error
          || result?.errors?.join('; ')
          || 'Backfill returned 0 messages.'
        const isDbError = detail.includes('ProgrammingError') || detail.includes('UndefinedTable') || detail.includes('sqlalchemy')
        const prefix = isDbError
          ? 'Database error (table may be missing)'
          : 'Backfill issue'
        setBackfillWarning(
          `${prefix}: ${detail.slice(0, 250)}`
        )
      }
    },
    onError: () => {
      setBackfillWarning('Backfill request failed. The API may be unreachable.')
    },
  })

  const messages = data?.messages ?? []
  const resolvedConnectorCount = Array.isArray(data?.connector_ids) ? data.connector_ids.length : 0
  const hasConnectors =
    data?.has_connectors === true ||
    resolvedConnectorCount > 0 ||
    feedLooksConfigured(agentData)
  const ingestion = data?.ingestion
  const dbError = data?.error

  useEffect(() => {
    if (!isLoading && hasConnectors && messages.length === 0 && !backfillAttemptedRef.current) {
      backfillAttemptedRef.current = true
      backfillMut.mutate()
    }
  }, [isLoading, hasConnectors, messages.length, backfillMut.mutate]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading…</div>

  if (messages.length === 0)
    return (
      <Card>
        <CardContent className="p-8 text-center space-y-4">
          <div className="text-muted-foreground text-sm">
            {backfillMut.isPending && hasConnectors
              ? 'Fetching latest messages from Discord…'
              : hasConnectors
                ? 'No messages yet for this agent\'s connector(s). The ingestion service may still be catching up, or the channel may be quiet.'
                : 'No channel messages yet. A Discord connector must be linked to this agent during setup.'}
          </div>
          {ingestion && !ingestion.running && (
            <p className="text-xs text-rose-500">Ingestion service is not running. Messages cannot be received until it starts.</p>
          )}
          {ingestion?.running && ingestion.summary && ingestion.summary.includes('stopped') && (
            <p className="text-xs text-amber-500">Warning: {ingestion.summary}</p>
          )}
          {ingestion?.running && ingestion.summary && ingestion.summary.includes('No ingestion') && (
            <p className="text-xs text-amber-500">{ingestion.summary}. Try refreshing ingestion via the scheduler.</p>
          )}
          {dbError && (
            <p className="text-xs text-rose-500">Database error: {dbError}. Run database migrations to fix.</p>
          )}
          {backfillWarning && (
            <p className="text-xs text-amber-500">{backfillWarning}</p>
          )}
        </CardContent>
      </Card>
    )

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{messages.length} messages (newest first)</span>
        {ingestion && (
          <span className={`text-xs ${ingestion.running ? (ingestion.summary?.includes('stopped') ? 'text-amber-500' : 'text-emerald-500') : 'text-rose-500'}`}>
            {ingestion.summary || (ingestion.running ? 'Ingesting' : 'Ingestion stopped')}
          </span>
        )}
      </div>

      {backfillWarning && (
        <p className="text-xs text-amber-500 px-1">{backfillWarning}</p>
      )}

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
