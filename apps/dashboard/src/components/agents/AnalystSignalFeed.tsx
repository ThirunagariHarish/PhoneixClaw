/**
 * AnalystSignalFeed — live-updating feed of signals emitted by an analyst agent.
 * Fetches from /api/v2/analyst/{agent_id}/signals with polling.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { AnalystSignalCard, type AnalystSignal } from './AnalystSignalCard'
import { Loader2, RefreshCw, Filter } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

interface AnalystSignalFeedProps {
  agentId: string
  /** Poll interval in ms. Default: 15000 */
  refetchInterval?: number
  /** Maximum signals to show. Default: 20 */
  limit?: number
}

export function AnalystSignalFeed({
  agentId,
  refetchInterval = 15_000,
  limit = 20,
}: AnalystSignalFeedProps) {
  const [decisionFilter, setDecisionFilter] = useState<string>('all')

  const { data: signals = [], isLoading, isError, refetch, isFetching } = useQuery<AnalystSignal[]>({
    queryKey: ['analyst-signals', agentId, decisionFilter, limit],
    queryFn: async () => {
      const params: Record<string, string | number> = { limit, days: 7 }
      if (decisionFilter !== 'all') params.decision = decisionFilter
      const res = await api.get(`/api/v2/analyst/${agentId}/signals`, { params })
      return res.data
    },
    refetchInterval,
    enabled: Boolean(agentId),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Loading signals…</span>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="text-sm text-red-500 py-4 text-center">
        Failed to load signals.{' '}
        <button
          type="button"
          onClick={() => refetch()}
          className="underline hover:no-underline"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Filter className="h-3.5 w-3.5" />
          <span>Filter:</span>
        </div>
        <Select value={decisionFilter} onValueChange={setDecisionFilter}>
          <SelectTrigger className="h-7 w-32 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All decisions</SelectItem>
            <SelectItem value="executed">Executed</SelectItem>
            <SelectItem value="watchlist">Watchlist</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 ml-auto"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
        </Button>
        <span className="text-xs text-muted-foreground">{signals.length} signal{signals.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Signal list */}
      {signals.length === 0 ? (
        <div className="text-sm text-muted-foreground text-center py-8 border border-dashed border-border rounded-lg">
          No analyst signals found.
          {decisionFilter !== 'all' && (
            <button
              type="button"
              className="block mx-auto mt-1 text-xs underline hover:no-underline"
              onClick={() => setDecisionFilter('all')}
            >
              Clear filter
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {signals.map((signal) => (
            <AnalystSignalCard key={signal.id} signal={signal} />
          ))}
        </div>
      )}
    </div>
  )
}
