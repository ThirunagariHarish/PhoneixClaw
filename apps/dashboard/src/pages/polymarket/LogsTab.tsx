/**
 * LogsTab — Phase 15.7 (9th tab)
 * Displays agent health, activity log, and research logs for the Prediction Markets agent.
 */
import { useQuery, useMutation } from '@tanstack/react-query'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { RefreshCw } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PMAgentHealth {
  agent: string
  status: 'healthy' | 'degraded' | 'dead'
  last_seen_at: string | null
  scan_count: number | null
  bet_count: number | null
}

interface PMAgentActivity {
  id: string
  timestamp: string | null
  agent: string
  event_type: string
  message: string
  severity: 'info' | 'warning' | 'error'
}

interface PMResearchLog {
  id: string
  created_at: string | null
  categories: string[] | null
  query_count: number | null
  summary: string | null
  applied: boolean
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(iso: string | null): string | null {
  if (!iso) return null
  const diffSec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  return `${Math.floor(diffSec / 3600)}h ago`
}

function statusDotClass(status: string): string {
  if (status === 'healthy') return 'bg-emerald-400'
  if (status === 'degraded') return 'bg-yellow-400'
  return 'bg-red-400'
}

function rowBgClass(severity: string): string {
  if (severity === 'error') return 'bg-red-500/5'
  if (severity === 'warning') return 'bg-yellow-500/5'
  return ''
}

function rowTextClass(severity: string): string {
  if (severity === 'error') return 'text-red-400'
  if (severity === 'warning') return 'text-yellow-400'
  return ''
}

// ---------------------------------------------------------------------------
// LogsTab (exported)
// ---------------------------------------------------------------------------

export function LogsTab() {
  // Agent health — refreshes every 30s
  const { data: health = [], isLoading: healthLoading } = useQuery({
    queryKey: ['pm-agents-health'],
    queryFn: async () =>
      (await api.get<PMAgentHealth[]>('/api/polymarket/agents/health')).data,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  // Activity log — refreshes every 30s
  const { data: activity = [], isLoading: activityLoading } = useQuery({
    queryKey: ['pm-agents-activity'],
    queryFn: async () =>
      (await api.get<PMAgentActivity[]>('/api/polymarket/agents/activity')).data,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  // Research logs — refreshes every 60s
  const { data: research = [] } = useQuery({
    queryKey: ['pm-research'],
    queryFn: async () =>
      (await api.get<PMResearchLog[]>('/api/polymarket/research')).data,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  const triggerCycle = useMutation({
    mutationFn: () => api.post('/api/polymarket/agents/cycle'),
    onSuccess: () => toast.success('Agent cycle triggered'),
    onError: () => toast.error('Failed to trigger agent cycle'),
  })

  return (
    <div className="space-y-6">
      {/* ── Agent Health ──────────────────────────────── */}
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">Agent Health</h3>
          <Button
            size="sm"
            variant="outline"
            onClick={() => triggerCycle.mutate()}
            disabled={triggerCycle.isPending}
          >
            <RefreshCw
              className={cn('mr-1 h-3.5 w-3.5', triggerCycle.isPending && 'animate-spin')}
            />
            Trigger Cycle
          </Button>
        </div>

        {healthLoading && (
          <p className="text-xs text-muted-foreground">Loading agent status…</p>
        )}
        {!healthLoading && health.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No agent health data available. Agents may not have started yet.
          </p>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {health.map((h) => (
            <div
              key={h.agent}
              className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 p-3"
            >
              <span
                className={cn(
                  'mt-1 h-2.5 w-2.5 rounded-full shrink-0',
                  statusDotClass(h.status),
                )}
              />
              <div className="min-w-0 flex-1 text-xs">
                <p className="font-semibold text-sm capitalize">{h.agent.replace(/_/g, ' ')}</p>
                <p className="capitalize text-muted-foreground">{h.status}</p>
                {h.last_seen_at && (
                  <p className="text-muted-foreground">
                    Last seen: {timeAgo(h.last_seen_at) ?? '—'}
                  </p>
                )}
                {(h.scan_count !== null || h.bet_count !== null) && (
                  <div className="flex gap-3 mt-1 text-muted-foreground">
                    {h.scan_count !== null && (
                      <span>
                        Scans: <span className="text-foreground font-medium">{h.scan_count}</span>
                      </span>
                    )}
                    {h.bet_count !== null && (
                      <span>
                        Bets: <span className="text-foreground font-medium">{h.bet_count}</span>
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Activity Log ──────────────────────────────── */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold">Activity Log</h3>
        </div>

        {activityLoading && (
          <p className="px-4 py-4 text-xs text-muted-foreground">Loading activity…</p>
        )}
        {!activityLoading && activity.length === 0 && (
          <p className="px-4 py-4 text-xs text-muted-foreground">No activity recorded yet.</p>
        )}

        {activity.length > 0 && (
          <div className="overflow-auto max-h-72">
            <table className="w-full text-xs">
              <thead className="border-b border-border bg-muted/40 text-left uppercase text-muted-foreground sticky top-0">
                <tr>
                  <th className="px-3 py-2 whitespace-nowrap">Time</th>
                  <th className="px-3 py-2">Agent</th>
                  <th className="px-3 py-2">Event</th>
                  <th className="px-3 py-2">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {activity.map((a) => (
                  <tr
                    key={a.id}
                    className={cn('hover:bg-muted/20 transition-colors', rowBgClass(a.severity))}
                  >
                    <td className="px-3 py-1.5 whitespace-nowrap text-muted-foreground">
                      {a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}
                    </td>
                    <td className={cn('px-3 py-1.5 font-medium', rowTextClass(a.severity))}>
                      {a.agent}
                    </td>
                    <td className="px-3 py-1.5">{a.event_type}</td>
                    <td
                      className="px-3 py-1.5 max-w-xs truncate text-muted-foreground"
                      title={a.message}
                    >
                      {a.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Research Logs ──────────────────────────────── */}
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-sm font-semibold mb-3">Recent Research</h3>

        {research.length === 0 && (
          <p className="text-xs text-muted-foreground">No research logs recorded yet.</p>
        )}

        <div className="space-y-3">
          {research.slice(0, 5).map((r) => (
            <div
              key={r.id}
              className="rounded-lg border border-border/60 bg-muted/20 p-3 text-xs"
            >
              <div className="flex items-start justify-between gap-2 mb-1">
                <div className="flex flex-wrap gap-1">
                  {(r.categories ?? []).map((c) => (
                    <span
                      key={c}
                      className="rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-medium"
                    >
                      {c}
                    </span>
                  ))}
                  {(r.categories ?? []).length === 0 && (
                    <span className="text-muted-foreground">Uncategorised</span>
                  )}
                </div>
                <span className="text-muted-foreground shrink-0">
                  {r.created_at ? new Date(r.created_at).toLocaleDateString() : '—'}
                </span>
              </div>

              {r.summary && (
                <p className="text-muted-foreground leading-relaxed mt-1">{r.summary}</p>
              )}

              <div className="flex items-center justify-between mt-2">
                {r.query_count !== null && (
                  <span className="text-muted-foreground">
                    Queries: <span className="font-medium text-foreground">{r.query_count}</span>
                  </span>
                )}
                {r.applied && (
                  <span className="text-emerald-400 font-medium text-[11px]">Applied ✓</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
