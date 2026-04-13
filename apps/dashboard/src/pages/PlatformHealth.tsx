/**
 * Platform Health — microservice health, feature store, model registry,
 * prediction accuracy, and broker gateway status at a glance.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
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
import { Server, CheckCircle2, XCircle, Clock, AlertTriangle, Shield } from 'lucide-react'
import { cn } from '@/lib/utils'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ServiceStatus {
  status: string
  http_status?: number
  url?: string
  error?: string
  uptime_seconds?: number
  version?: string
}

interface PlatformHealthResponse {
  overall: string
  services: Record<string, ServiceStatus>
}

interface ModelBundle {
  id: string
  agent_id: string
  version: number
  primary_model?: string
  accuracy?: number
  auc_roc?: number
  sharpe_ratio?: number
  status: string
  created_at?: string
  deployed_at?: string
}

interface BrokerStatusResponse {
  authenticated?: boolean
  paper_mode?: boolean
  broker?: string
  error?: string
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STATUS_LABELS: Record<string, string> = {
  ok: 'Healthy',
  degraded: 'Degraded',
  timeout: 'Timeout',
  unreachable: 'Unreachable',
}

const SERVICE_DISPLAY: Record<string, string> = {
  feature_pipeline: 'Feature Pipeline',
  inference_service: 'Inference Service',
  broker_gateway: 'Broker Gateway',
  discord_ingestion: 'Discord Ingestion',
  agent_orchestrator: 'Agent Orchestrator',
  prediction_monitor: 'Prediction Monitor',
  backtesting: 'Backtesting',
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === 'ok'
      ? 'bg-emerald-500'
      : status === 'degraded'
        ? 'bg-amber-500'
        : 'bg-red-500'
  return <span className={cn('inline-block h-2.5 w-2.5 rounded-full shrink-0', color)} />
}

function relativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '--'
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 0) return 'just now'
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/* ------------------------------------------------------------------ */
/*  Service Health Card                                                */
/* ------------------------------------------------------------------ */

function ServiceCard({ name, svc }: { name: string; svc: ServiceStatus }) {
  return (
    <Card className="relative overflow-hidden">
      <div
        className={cn(
          'h-1',
          svc.status === 'ok' ? 'bg-emerald-500' : svc.status === 'degraded' ? 'bg-amber-500' : 'bg-red-500',
        )}
      />
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <StatusDot status={svc.status} />
            <p className="font-semibold text-sm truncate">{SERVICE_DISPLAY[name] ?? name}</p>
          </div>
          <Badge
            variant={svc.status === 'ok' ? 'secondary' : 'destructive'}
            className="text-[10px] shrink-0"
          >
            {STATUS_LABELS[svc.status] ?? svc.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {svc.version && (
            <>
              <span className="text-muted-foreground">Version</span>
              <span className="text-right font-mono">{svc.version}</span>
            </>
          )}
          {svc.uptime_seconds != null && (
            <>
              <span className="text-muted-foreground">Uptime</span>
              <span className="text-right font-mono">
                {svc.uptime_seconds > 86400
                  ? `${Math.floor(svc.uptime_seconds / 86400)}d`
                  : svc.uptime_seconds > 3600
                    ? `${Math.floor(svc.uptime_seconds / 3600)}h`
                    : `${Math.floor(svc.uptime_seconds / 60)}m`}
              </span>
            </>
          )}
          {svc.http_status != null && (
            <>
              <span className="text-muted-foreground">HTTP</span>
              <span className="text-right font-mono">{svc.http_status}</span>
            </>
          )}
          {svc.error && (
            <>
              <span className="text-muted-foreground">Error</span>
              <span className="text-right text-red-500 truncate" title={svc.error}>
                {svc.error.slice(0, 60)}
              </span>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function PlatformHealthPage() {
  // Platform health
  const { data: health, isLoading: healthLoading } = useQuery<PlatformHealthResponse>({
    queryKey: ['platform-health'],
    queryFn: async () => {
      const res = await api.get('/api/v2/platform/health')
      return res.data
    },
    refetchInterval: 15_000,
  })

  // Model bundles (all agents — use the list endpoint)
  const { data: bundles = [], isLoading: bundlesLoading } = useQuery<ModelBundle[]>({
    queryKey: ['platform-model-bundles'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/agents')
        const agents: { id: string }[] = res.data ?? []
        const all: ModelBundle[] = []
        for (const agent of agents.slice(0, 10)) {
          try {
            const bRes = await api.get(`/api/v2/model-bundles/${agent.id}`)
            if (Array.isArray(bRes.data)) all.push(...bRes.data)
          } catch {
            // agent has no bundles
          }
        }
        return all.sort((a, b) => (b.version ?? 0) - (a.version ?? 0))
      } catch {
        return []
      }
    },
    refetchInterval: 60_000,
  })

  // Broker status
  const { data: brokerStatus, isLoading: brokerLoading } = useQuery<BrokerStatusResponse>({
    queryKey: ['platform-broker-status'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/platform/broker/status')
        return res.data
      } catch {
        return { authenticated: false, error: 'Unreachable' }
      }
    },
    refetchInterval: 30_000,
  })

  // Derived metrics
  const metrics = useMemo(() => {
    if (!health?.services) return { total: 0, healthy: 0, degraded: 0, down: 0 }
    const svcs = Object.values(health.services)
    return {
      total: svcs.length,
      healthy: svcs.filter((s) => s.status === 'ok').length,
      degraded: svcs.filter((s) => s.status === 'degraded').length,
      down: svcs.filter((s) => s.status !== 'ok' && s.status !== 'degraded').length,
    }
  }, [health])

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Server} title="Platform Health" description="Microservice health, models, and broker status" />

      {/* Top metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
        <MetricCard title="Total Services" value={metrics.total} icon={Server} />
        <MetricCard
          title="Healthy"
          value={metrics.healthy}
          icon={CheckCircle2}
          trend={metrics.healthy === metrics.total ? 'up' : 'neutral'}
        />
        <MetricCard
          title="Degraded"
          value={metrics.degraded}
          icon={AlertTriangle}
          trend={metrics.degraded > 0 ? 'down' : 'neutral'}
        />
        <MetricCard
          title="Down"
          value={metrics.down}
          icon={XCircle}
          trend={metrics.down > 0 ? 'down' : 'neutral'}
        />
      </div>

      {/* Service health cards */}
      <div>
        <h2 className="text-base font-semibold mb-3">Service Status</h2>
        {healthLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Card key={i} className="overflow-hidden">
                <div className="h-1 bg-muted" />
                <CardContent className="p-4 space-y-3">
                  <Skeleton className="h-5 w-3/4" />
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-8 w-full" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : health?.services ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {Object.entries(health.services).map(([name, svc]) => (
              <ServiceCard key={name} name={name} svc={svc} />
            ))}
          </div>
        ) : (
          <Card>
            <CardContent className="py-12 text-center">
              <Server className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground">Unable to fetch platform health.</p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Broker Gateway Status */}
      <div>
        <h2 className="text-base font-semibold mb-3 flex items-center gap-2">
          <Shield className="h-4 w-4" /> Broker Gateway
        </h2>
        {brokerLoading ? (
          <Card>
            <CardContent className="p-4 space-y-2">
              <Skeleton className="h-5 w-1/3" />
              <Skeleton className="h-4 w-1/4" />
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-4">
              <div className="flex items-center gap-4 flex-wrap">
                <div className="flex items-center gap-2">
                  <StatusDot status={brokerStatus?.authenticated ? 'ok' : 'unreachable'} />
                  <span className="text-sm font-medium">
                    {brokerStatus?.authenticated ? 'Authenticated' : 'Not Authenticated'}
                  </span>
                </div>
                {brokerStatus?.paper_mode != null && (
                  <Badge variant="outline" className="text-xs">
                    {brokerStatus.paper_mode ? 'Paper Mode' : 'Live Mode'}
                  </Badge>
                )}
                {brokerStatus?.broker && (
                  <Badge variant="secondary" className="text-xs">
                    {brokerStatus.broker}
                  </Badge>
                )}
                {brokerStatus?.error && (
                  <span className="text-xs text-red-500">{brokerStatus.error}</span>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Model Registry */}
      <div>
        <h2 className="text-base font-semibold mb-3 flex items-center gap-2">
          <Clock className="h-4 w-4" /> Model Registry
        </h2>
        <div className="rounded-xl border border-border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Accuracy</TableHead>
                <TableHead>Sharpe</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Deployed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bundlesLoading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 7 }).map((__, j) => (
                      <TableCell key={j}><Skeleton className="h-5 w-full" /></TableCell>
                    ))}
                  </TableRow>
                ))
              ) : bundles.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                    No model bundles registered yet.
                  </TableCell>
                </TableRow>
              ) : (
                bundles.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="text-xs font-mono truncate max-w-[140px]" title={b.agent_id}>
                      {b.agent_id.slice(0, 8)}...
                    </TableCell>
                    <TableCell className="text-xs font-mono">v{b.version}</TableCell>
                    <TableCell className="text-xs">{b.primary_model ?? '--'}</TableCell>
                    <TableCell className="text-xs font-mono">
                      {b.accuracy != null ? `${(b.accuracy * 100).toFixed(1)}%` : '--'}
                    </TableCell>
                    <TableCell className="text-xs font-mono">
                      {b.sharpe_ratio != null ? b.sharpe_ratio.toFixed(2) : '--'}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={b.status === 'approved' ? 'secondary' : b.status === 'retired' ? 'outline' : 'default'}
                        className="text-[10px]"
                      >
                        {b.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {relativeTime(b.deployed_at)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}
