/**
 * P3: Raw channel messages tab. Polls /api/v2/agents/{id}/channel-messages.
 * Includes inline "Link Connector" flow so users can attach a connector to an
 * existing agent without leaving the page.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Plug, RefreshCw } from 'lucide-react'

interface Msg {
  id: string
  channel: string
  author: string
  content: string
  message_type: string
  tickers: string[]
  posted_at: string | null
}

interface Connector {
  id: string
  name: string
  platform: string
  status: string
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
  const qc = useQueryClient()
  const [linking, setLinking] = useState(false)
  const [selectedConnector, setSelectedConnector] = useState<string>('')
  const [linkError, setLinkError] = useState<string | null>(null)
  const [linkSuccess, setLinkSuccess] = useState(false)
  // R-004: track the success-banner timer so it can be cleared on unmount
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const backfillAttemptedRef = useRef<boolean>(false)
  useEffect(() => () => { if (successTimerRef.current) clearTimeout(successTimerRef.current) }, [])

  const { data: agentData } = useQuery<AgentDetail>({
    queryKey: ['agent', agentId],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}`)).data,
  })

  const { data, isLoading, refetch, isFetching } = useQuery<{
    messages: Msg[]
    count: number
    connector_ids?: string[]
    has_connectors?: boolean
  }>({
    queryKey: ['channel-messages', agentId],
    queryFn: async () =>
      (await api.get(`/api/v2/agents/${agentId}/channel-messages?limit=200`)).data,
    refetchInterval: 15000,
  })

  const { data: connectorsData } = useQuery<Connector[]>({
    queryKey: ['connectors-list'],
    queryFn: async () => (await api.get('/api/v2/connectors')).data,
    enabled: linking,
    staleTime: 0,  // always refetch when link panel opens so newly-added connectors appear
  })

  const linkMut = useMutation({
    mutationFn: async (connectorId: string) => {
      await api.post(`/api/v2/connectors/${connectorId}/agents`, { agent_id: agentId })
    },
    onSuccess: () => {
      setLinkSuccess(true)
      setLinking(false)
      setLinkError(null)
      qc.invalidateQueries({ queryKey: ['channel-messages', agentId] })
      qc.invalidateQueries({ queryKey: ['agent', agentId] })
      successTimerRef.current = setTimeout(() => setLinkSuccess(false), 4000)
    },
    onError: (e: unknown) => {
      // Extract the server's detail message rather than the raw axios error
      // to avoid leaking internal stack traces or DB errors to the UI.
      const axiosErr = e as { response?: { data?: { detail?: string } }; message?: string }
      const msg = axiosErr?.response?.data?.detail ?? axiosErr?.message ?? 'Failed to link connector'
      setLinkError(String(msg).slice(0, 200))
    },
  })

  const backfillMut = useMutation({
    mutationFn: async () => {
      await api.post(`/api/v2/agents/${agentId}/channel-messages/backfill?limit=100`)
    },
    onSuccess: () => {
      refetch()
    },
  })

  const messages = data?.messages ?? []
  const resolvedConnectorCount = Array.isArray(data?.connector_ids) ? data.connector_ids.length : 0
  const hasConnectors =
    data?.has_connectors === true ||
    resolvedConnectorCount > 0 ||
    feedLooksConfigured(agentData)

  // Auto-trigger backfill once when connectors exist but no messages are present
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
                : 'No channel messages yet. Link a Discord/Reddit connector to start seeing the feed.'}
          </div>

          {!linking ? (
            <div className="flex justify-center gap-2 flex-wrap">
              {!hasConnectors && (
                <Button variant="outline" size="sm" onClick={() => setLinking(true)}>
                  <Plug className="h-4 w-4 mr-1.5" /> Link Connector
                </Button>
              )}
              {hasConnectors && (
                <Button variant="outline" size="sm" onClick={() => setLinking(true)}>
                  <Plug className="h-4 w-4 mr-1.5" /> Link another connector
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
                <RefreshCw className={`h-4 w-4 mr-1.5 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
              </Button>
            </div>
          ) : (
            <div className="space-y-3 max-w-xs mx-auto">
              <select
                title="Select connector to link"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={selectedConnector}
                onChange={(e) => setSelectedConnector(e.target.value)}
              >
                <option value="">— select connector —</option>
                {(connectorsData ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.platform})
                  </option>
                ))}
              </select>
              {linkError && <p className="text-xs text-destructive">{linkError}</p>}
              <div className="flex gap-2 justify-center">
                <Button
                  size="sm"
                  disabled={!selectedConnector || linkMut.isPending}
                  onClick={() => linkMut.mutate(selectedConnector)}
                >
                  {linkMut.isPending ? 'Linking…' : 'Confirm Link'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => { setLinking(false); setLinkError(null) }}>
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {linkSuccess && (
            <p className="text-xs text-green-500">Connector linked — messages will appear shortly.</p>
          )}
        </CardContent>
      </Card>
    )

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{messages.length} messages (newest first)</span>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setLinking(!linking)}>
            <Plug className="h-3.5 w-3.5 mr-1" /> Link connector
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
          </Button>
        </div>
      </div>

      {linking && (
        <Card className="border-dashed">
          <CardContent className="p-4 space-y-3">
            <p className="text-xs text-muted-foreground">Link an additional connector to this agent:</p>
            <div className="flex gap-2 flex-wrap">
              <select
                title="Select connector to link"
                className="flex-1 min-w-[180px] rounded-md border border-input bg-background px-3 py-1.5 text-sm"
                value={selectedConnector}
                onChange={(e) => setSelectedConnector(e.target.value)}
              >
                <option value="">— select connector —</option>
                {(connectorsData ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.platform})
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                disabled={!selectedConnector || linkMut.isPending}
                onClick={() => linkMut.mutate(selectedConnector)}
              >
                {linkMut.isPending ? 'Linking…' : 'Link'}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => { setLinking(false); setLinkError(null) }}>
                Cancel
              </Button>
            </div>
            {linkError && <p className="text-xs text-destructive">{linkError}</p>}
            {linkSuccess && <p className="text-xs text-green-500">Linked successfully.</p>}
          </CardContent>
        </Card>
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
