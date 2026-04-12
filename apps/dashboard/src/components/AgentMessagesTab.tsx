/**
 * P3: Raw channel messages tab. Polls /api/v2/agents/{id}/channel-messages.
 * Auto-backfills on first load when connectors exist but no messages yet.
 * Shows decision status icons (traded/watchlisted/rejected/paper) per message.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, XCircle, Eye, FlaskConical } from 'lucide-react'

interface Msg {
  id: string
  channel: string
  author: string
  content: string
  message_type: string
  tickers: string[]
  posted_at: string | null
  platform_message_id?: string
}

interface Decision {
  decision: string
  ticker: string
  confidence?: number | null
  rejection_reason?: string | null
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

function DecisionBadge({ decision }: { decision: Decision }) {
  const d = decision.decision
  if (d === 'executed')
    return (
      <Badge className="text-[10px] gap-1 bg-emerald-600/20 text-emerald-400 border-emerald-600/40 hover:bg-emerald-600/30">
        <CheckCircle2 className="h-3 w-3" /> Traded
      </Badge>
    )
  if (d === 'watchlist')
    return (
      <Badge className="text-[10px] gap-1 bg-amber-600/20 text-amber-400 border-amber-600/40 hover:bg-amber-600/30">
        <Eye className="h-3 w-3" /> Watchlisted
      </Badge>
    )
  if (d === 'rejected')
    return (
      <Badge className="text-[10px] gap-1 bg-red-600/20 text-red-400 border-red-600/40 hover:bg-red-600/30">
        <XCircle className="h-3 w-3" /> Rejected
      </Badge>
    )
  if (d === 'paper')
    return (
      <Badge className="text-[10px] gap-1 bg-blue-600/20 text-blue-400 border-blue-600/40 hover:bg-blue-600/30">
        <FlaskConical className="h-3 w-3" /> Paper
      </Badge>
    )
  return null
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
    since?: string
    decisions?: Record<string, Decision>
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
  const decisions = data?.decisions ?? {}
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
                ? 'No messages today for this agent\'s connector(s). The feed resets daily and only shows today\'s activity.'
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
        <span className="text-xs text-muted-foreground">
          {messages.length} message{messages.length !== 1 ? 's' : ''} today
          {data?.since ? ` (since ${new Date(data.since).toLocaleString()})` : ' (newest first)'}
        </span>
        {ingestion && (
          <span className={`text-xs ${ingestion.running ? (ingestion.summary?.includes('stopped') ? 'text-amber-500' : 'text-emerald-500') : 'text-rose-500'}`}>
            {ingestion.summary || (ingestion.running ? 'Ingesting' : 'Ingestion stopped')}
          </span>
        )}
      </div>

      {backfillWarning && (
        <p className="text-xs text-amber-500 px-1">{backfillWarning}</p>
      )}

      {messages.map((m) => {
        const dec = m.platform_message_id ? decisions[m.platform_message_id] : undefined
        return (
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
                  {dec && <DecisionBadge decision={dec} />}
                </div>
                <span className="text-xs text-muted-foreground">
                  {m.posted_at ? new Date(m.posted_at).toLocaleString() : ''}
                </span>
              </div>
              <div className="text-sm whitespace-pre-wrap">{m.content}</div>
              {dec?.rejection_reason && (
                <p className="text-[10px] text-muted-foreground mt-1">Reason: {dec.rejection_reason}</p>
              )}
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
