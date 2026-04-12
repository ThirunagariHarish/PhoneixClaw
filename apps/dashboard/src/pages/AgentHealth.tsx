/**
 * Agent Health Monitor -- real-time agent health overview with error log.
 * Top metrics, health cards grid, and recent error log table.
 */
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { HeartPulse, Play, Pause, RotateCcw, ExternalLink, ChevronDown, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AgentData {
  id: string
  name: string
  type: string
  status: string
  worker_status?: string
  created_at: string
  last_heartbeat?: string | null
  started_at?: string | null
  daily_pnl?: number
  total_trades?: number
  today_trades?: number
  error_count_24h?: number
  error_message?: string | null
  config?: Record<string, unknown>
}

interface SystemLog {
  id: string | number
  timestamp: string
  agent_name?: string
  agent_id?: string
  level: string
  error_type?: string
  message: string
  stack_trace?: string | null
}

type HealthLevel = 'healthy' | 'warning' | 'error'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function relativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return 'Never'
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 0) return 'just now'
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function formatUptime(startedAt: string | null | undefined): string {
  if (!startedAt) return '--'
  const diff = Date.now() - new Date(startedAt).getTime()
  if (diff < 0) return '0m'
  const days = Math.floor(diff / 86400000)
  const hours = Math.floor((diff % 86400000) / 3600000)
  const minutes = Math.floor((diff % 3600000) / 60000)
  if (days > 0) return `${days}d ${hours}h ${minutes}m`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

function computeHealth(agent: AgentData): HealthLevel {
  const status = agent.status?.toLowerCase()
  if (['error', 'failed', 'crashed', 'stopped'].includes(status)) return 'error'
  if (status !== 'running' && status !== 'active') return 'warning'

  // Check heartbeat freshness (>5 min = warning)
  if (agent.last_heartbeat) {
    const age = Date.now() - new Date(agent.last_heartbeat).getTime()
    if (age > 5 * 60 * 1000) return 'warning'
  } else {
    // Running but no heartbeat at all
    return 'warning'
  }

  return 'healthy'
}

function healthBarColor(level: HealthLevel): string {
  switch (level) {
    case 'healthy': return 'bg-emerald-500'
    case 'warning': return 'bg-amber-500'
    case 'error': return 'bg-red-500'
  }
}

function pnlColor(v: number | null | undefined): string {
  if (v == null || v === 0) return ''
  return v > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
}

/* ------------------------------------------------------------------ */
/*  HLT1: Uptime Timeline — 24h sparkline                             */
/* ------------------------------------------------------------------ */

function UptimeTimeline({ agent }: { agent: AgentData }) {
  // Generate 24 segments for the last 24 hours based on agent state
  const segments = 24
  const now = Date.now()
  const startedAt = agent.started_at ? new Date(agent.started_at).getTime() : null
  const health = computeHealth(agent)

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">24h Uptime</span>
        <span className="text-[10px] text-muted-foreground">Now</span>
      </div>
      <div className="flex gap-0.5 h-3">
        {Array.from({ length: segments }).map((_, i) => {
          const segStart = now - (segments - i) * 3600000
          const segEnd = segStart + 3600000
          // Determine if the agent was running during this segment
          let segColor = 'bg-muted'
          if (startedAt && segEnd > startedAt) {
            if (health === 'error') {
              // Show red for the last segment if currently errored
              segColor = i === segments - 1 ? 'bg-red-500' : 'bg-emerald-500'
            } else if (health === 'warning' && i === segments - 1) {
              segColor = 'bg-amber-500'
            } else {
              segColor = 'bg-emerald-500'
            }
          }
          // If agent wasn't started yet, show gray
          if (startedAt && segStart < startedAt) {
            segColor = 'bg-muted'
          }
          return (
            <div
              key={i}
              className={cn('flex-1 rounded-sm', segColor)}
              title={`${new Date(segStart).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })} - ${new Date(segEnd).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`}
            />
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Agent Health Card                                                  */
/* ------------------------------------------------------------------ */

function AgentHealthCard({
  agent,
  onRestart,
  onPause,
  onToggleAutoRestart,
}: {
  agent: AgentData
  onRestart: (id: string) => void
  onPause: (id: string) => void
  onToggleAutoRestart: (id: string, enabled: boolean, maxRetries: number) => void
}) {
  const navigate = useNavigate()
  const health = computeHealth(agent)
  const heartbeatStr = relativeTime(agent.last_heartbeat)
  const heartbeatStale = agent.last_heartbeat
    ? (Date.now() - new Date(agent.last_heartbeat).getTime()) > 5 * 60 * 1000
    : true
  const isRunning = ['running', 'active'].includes(agent.status?.toLowerCase())

  return (
    <Card className="relative overflow-hidden">
      {/* Health bar at top */}
      <div className={cn('h-1', healthBarColor(health))} />
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-semibold text-sm truncate">{agent.name}</p>
            <p className="text-xs text-muted-foreground truncate">{agent.type}</p>
          </div>
          <StatusBadge status={agent.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <span className="text-muted-foreground">Uptime</span>
          <span className="text-right font-mono">{formatUptime(agent.started_at ?? agent.created_at)}</span>

          <span className="text-muted-foreground">Last Heartbeat</span>
          <span className={cn('text-right font-mono', heartbeatStale && 'text-red-500 font-semibold')}>
            {heartbeatStr}
          </span>

          <span className="text-muted-foreground">Today Trades</span>
          <span className="text-right font-mono">{agent.today_trades ?? agent.total_trades ?? 0}</span>

          <span className="text-muted-foreground">Today P&L</span>
          <span className={cn('text-right font-mono', pnlColor(agent.daily_pnl))}>
            {agent.daily_pnl != null ? `$${agent.daily_pnl.toFixed(2)}` : '--'}
          </span>

          <span className="text-muted-foreground">Errors (24h)</span>
          <span className="text-right">
            {(agent.error_count_24h ?? 0) > 0 ? (
              <Badge variant="destructive" className="text-[10px] px-1.5 py-0">
                {agent.error_count_24h}
              </Badge>
            ) : (
              <span className="font-mono">0</span>
            )}
          </span>
        </div>

        {/* HLT1: Uptime Timeline */}
        <UptimeTimeline agent={agent} />

        {/* HLT2: Auto-Recovery Policy */}
        {(() => {
          const cfg = agent.config ?? {}
          const autoRestart = Boolean(cfg.auto_restart_enabled)
          const maxRetries = typeof cfg.auto_restart_max_retries === 'number' ? cfg.auto_restart_max_retries : 3
          return (
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Label htmlFor={`ar-${agent.id}`} className="text-[11px] text-muted-foreground cursor-pointer">
                  Auto-restart on failure
                </Label>
              </div>
              <div className="flex items-center gap-2">
                {autoRestart && (
                  <select
                    value={maxRetries}
                    onChange={(e) => onToggleAutoRestart(agent.id, true, parseInt(e.target.value))}
                    className="h-6 text-[10px] bg-muted border border-border rounded px-1 text-foreground"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {[1, 2, 3, 5, 10].map((n) => (
                      <option key={n} value={n}>{n} retries</option>
                    ))}
                  </select>
                )}
                <Switch
                  id={`ar-${agent.id}`}
                  checked={autoRestart}
                  onCheckedChange={(checked) => onToggleAutoRestart(agent.id, checked, maxRetries)}
                />
              </div>
            </div>
          )
        })()}

        {/* Actions */}
        <div className="flex items-center gap-1.5 pt-1 border-t">
          {isRunning ? (
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => onPause(agent.id)}>
              <Pause className="h-3 w-3 mr-1" /> Pause
            </Button>
          ) : (
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => onRestart(agent.id)}>
              <Play className="h-3 w-3 mr-1" /> Start
            </Button>
          )}
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => onRestart(agent.id)}>
            <RotateCcw className="h-3 w-3 mr-1" /> Restart
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs ml-auto"
            onClick={() => navigate(`/agents/${agent.id}`)}
          >
            View <ExternalLink className="h-3 w-3 ml-1" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/*  Expandable error row                                               */
/* ------------------------------------------------------------------ */

function ErrorRow({ log }: { log: SystemLog }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <TableRow className="cursor-pointer hover:bg-muted/50" onClick={() => setOpen((o) => !o)}>
        <TableCell className="text-xs tabular-nums whitespace-nowrap">
          {new Date(log.timestamp).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
          })}
        </TableCell>
        <TableCell className="text-xs font-mono">{log.agent_name ?? log.agent_id ?? '--'}</TableCell>
        <TableCell>
          <Badge variant="destructive" className="text-[10px]">{log.error_type ?? log.level}</Badge>
        </TableCell>
        <TableCell className="text-xs max-w-[300px] truncate">{log.message}</TableCell>
        <TableCell className="text-right">
          {log.stack_trace && (
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}>
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
            </Button>
          )}
        </TableCell>
      </TableRow>
      {open && log.stack_trace && (
        <TableRow>
          <TableCell colSpan={5} className="bg-muted/30 p-0">
            <pre className="text-[11px] text-muted-foreground p-3 overflow-x-auto whitespace-pre-wrap max-h-48 font-mono">
              {log.stack_trace}
            </pre>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function AgentHealthPage() {
  const qc = useQueryClient()
  const [errorFilter, setErrorFilter] = useState('')

  // Fetch agents
  const { data: agents = [], isLoading: agentsLoading } = useQuery<AgentData[]>({
    queryKey: ['agent-health-agents'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/agents')
        return res.data ?? []
      } catch {
        return []
      }
    },
    refetchInterval: 30_000,
  })

  // Fetch error logs
  const { data: errorLogs = [], isLoading: logsLoading } = useQuery<SystemLog[]>({
    queryKey: ['agent-health-errors'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/system-logs', {
          params: { source: 'agent', level: 'ERROR', limit: 50 },
        })
        return res.data ?? []
      } catch {
        return []
      }
    },
    refetchInterval: 30_000,
  })

  // Agent actions
  const restartMutation = useMutation({
    mutationFn: (agentId: string) => api.post(`/api/v2/agents/${agentId}/restart`),
    onSuccess: () => {
      toast.success('Agent restart requested')
      qc.invalidateQueries({ queryKey: ['agent-health-agents'] })
    },
    onError: () => toast.error('Failed to restart agent'),
  })

  const pauseMutation = useMutation({
    mutationFn: (agentId: string) => api.post(`/api/v2/agents/${agentId}/pause`),
    onSuccess: () => {
      toast.success('Agent paused')
      qc.invalidateQueries({ queryKey: ['agent-health-agents'] })
    },
    onError: () => toast.error('Failed to pause agent'),
  })

  // HLT2: Auto-recovery config mutation
  const autoRestartMutation = useMutation({
    mutationFn: async ({ agentId, enabled, maxRetries }: { agentId: string; enabled: boolean; maxRetries: number }) => {
      await api.patch(`/api/v2/agents/${agentId}/config`, {
        auto_restart_enabled: enabled,
        auto_restart_max_retries: maxRetries,
      })
    },
    onSuccess: () => {
      toast.success('Auto-recovery policy updated')
      qc.invalidateQueries({ queryKey: ['agent-health-agents'] })
    },
    onError: () => toast.error('Failed to update auto-recovery policy'),
  })

  // Compute health metrics
  const metrics = useMemo(() => {
    let healthy = 0
    let warning = 0
    let error = 0
    for (const a of agents) {
      const h = computeHealth(a)
      if (h === 'healthy') healthy++
      else if (h === 'warning') warning++
      else error++
    }
    return { total: agents.length, healthy, warning, error }
  }, [agents])

  // Filter error logs
  const filteredLogs = useMemo(() => {
    if (!errorFilter) return errorLogs
    const q = errorFilter.toLowerCase()
    return errorLogs.filter((l) =>
      (l.agent_name ?? l.agent_id ?? '').toLowerCase().includes(q) ||
      l.message.toLowerCase().includes(q)
    )
  }, [errorLogs, errorFilter])

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={HeartPulse} title="Agent Health" description="Real-time agent health monitoring and error tracking" />

      {/* Top metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
        <MetricCard title="Total Agents" value={metrics.total} />
        <MetricCard title="Healthy" value={metrics.healthy} trend={metrics.healthy > 0 ? 'up' : 'neutral'} />
        <MetricCard
          title="Warning"
          value={metrics.warning}
          trend={metrics.warning > 0 ? 'down' : 'neutral'}
          subtitle="Stale heartbeat or idle"
        />
        <MetricCard
          title="Error"
          value={metrics.error}
          trend={metrics.error > 0 ? 'down' : 'neutral'}
          subtitle="Crashed or stopped"
        />
      </div>

      {/* Agent health cards grid */}
      <div>
        <h2 className="text-base font-semibold mb-3">Agent Status</h2>
        {agentsLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="overflow-hidden">
                <div className="h-1 bg-muted" />
                <CardContent className="p-4 space-y-3">
                  <Skeleton className="h-5 w-3/4" />
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-16 w-full" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : agents.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <HeartPulse className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground">No agents found.</p>
              <p className="text-sm text-muted-foreground mt-1">Create an agent to see health data here.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {agents.map((agent) => (
              <AgentHealthCard
                key={agent.id}
                agent={agent}
                onRestart={(id) => restartMutation.mutate(id)}
                onPause={(id) => pauseMutation.mutate(id)}
                onToggleAutoRestart={(id, enabled, maxRetries) => autoRestartMutation.mutate({ agentId: id, enabled, maxRetries })}
              />
            ))}
          </div>
        )}
      </div>

      {/* Error log */}
      <div>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            Recent Errors
            {errorLogs.length > 0 && (
              <Badge variant="destructive" className="text-[10px] ml-1">{errorLogs.length}</Badge>
            )}
          </h2>
          <Input
            placeholder="Filter by agent or message..."
            value={errorFilter}
            onChange={(e) => setErrorFilter(e.target.value)}
            className="w-full sm:w-64"
          />
        </div>

        <div className="rounded-xl border border-border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Message</TableHead>
                <TableHead className="text-right w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {logsLoading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 5 }).map((__, j) => (
                      <TableCell key={j}><Skeleton className="h-5 w-full" /></TableCell>
                    ))}
                  </TableRow>
                ))
              ) : filteredLogs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    {errorFilter ? 'No matching errors.' : 'No recent errors. All agents healthy.'}
                  </TableCell>
                </TableRow>
              ) : (
                filteredLogs.map((log) => (
                  <ErrorRow key={log.id} log={log} />
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}
