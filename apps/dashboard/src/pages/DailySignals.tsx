/**
 * Daily Signals page — 3-agent pipeline (Research → Technical → Risk) producing daily trade signals.
 * Phoenix v2.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SidePanel } from '@/components/ui/SidePanel'
import {
  TrendingUp,
  TrendingDown,
  Search,
  BarChart3,
  Shield,
  Zap,
  ChevronRight,
} from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { getMetricTooltip } from '@/lib/metricTooltips'

interface Signal {
  id: string
  time: string
  symbol: string
  direction: 'LONG' | 'SHORT'
  confidence: number
  source_agent: string
  entry_price: number
  stop_loss: number
  take_profit: number
  risk_reward: number
  status: 'NEW' | 'ACTIVE' | 'EXPIRED'
  research_note?: string
  technical_chart_ref?: string
  risk_analysis?: string
}

interface PipelineAgent {
  id: string
  name: string
  status: string
  last_run: string
  signals_produced: number
}

interface PipelineStatus {
  status: string
  instance_id: string | null
  agents: PipelineAgent[]
}

interface DailySummary {
  total_signals_today: number
  win_rate_7d: number
  avg_rr: number
  active_signals: number
  pipeline_health: string
}

const EMPTY_PIPELINE: PipelineStatus = {
  status: 'not_deployed',
  instance_id: null,
  agents: [],
}

export default function DailySignalsPage() {
  const [selectedInstance, setSelectedInstance] = useState<string>('')
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null)
  const queryClient = useQueryClient()

  const { data: signals = [], isLoading: signalsLoading } = useQuery<Signal[]>({
    queryKey: ['daily-signals'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/daily-signals')
        return res.data ?? []
      } catch {
        return []
      }
    },
    refetchInterval: 30000,
  })

  const { data: pipeline = EMPTY_PIPELINE } = useQuery<PipelineStatus>({
    queryKey: ['daily-signals-pipeline'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/daily-signals/pipeline')
        return res.data ?? EMPTY_PIPELINE
      } catch {
        return EMPTY_PIPELINE
      }
    },
  })

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data ?? [],
  })

  const summary: DailySummary = {
    total_signals_today: signals.length,
    win_rate_7d: 0,
    avg_rr: signals.length ? signals.reduce((a, s) => a + s.risk_reward, 0) / signals.length : 0,
    active_signals: signals.filter((s) => s.status === 'ACTIVE').length,
    pipeline_health: pipeline.status === 'deployed' ? 'healthy' : 'degraded',
  }

  const deployMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/daily-signals/pipeline/deploy', { instance_id: selectedInstance || 'inst-1' })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['daily-signals-pipeline'] }),
  })

  const formatTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Zap} title="Daily Signals" description="3-agent pipeline: Research → Technical → Risk" />

      {/* Daily Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
        <MetricCard title="Total Signals Today" value={summary.total_signals_today} tooltip={getMetricTooltip('Total Signals Today')} />
        <MetricCard title="Win Rate (7d)" value={`${summary.win_rate_7d}%`} trend="up" tooltip={getMetricTooltip('Win Rate')} />
        <MetricCard title="Avg R:R" value={summary.avg_rr.toFixed(1)} tooltip={getMetricTooltip('Avg R:R')} />
        <MetricCard title="Active Signals" value={summary.active_signals} tooltip={getMetricTooltip('Active Signals')} />
        <MetricCard
          title="Pipeline Health"
          value={summary.pipeline_health}
          trend={summary.pipeline_health === 'healthy' ? 'up' : 'down'}
          tooltip={getMetricTooltip('Pipeline Health')}
        />
      </div>

      {/* Pipeline Visualization + Instance Connection */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
        <div className="lg:col-span-2">
          <FlexCard title="Pipeline">
            <div className="flex flex-wrap items-center gap-4">
              {pipeline.agents.map((agent, i) => (
                <div key={agent.id} className="flex items-center gap-2">
                    <div className="flex flex-col items-center p-3 rounded-lg border bg-card min-w-[120px] sm:min-w-[140px]">
                    <div className="flex items-center gap-2 mb-1">
                      {agent.name === 'Research Analyst' && <Search className="h-4 w-4 text-muted-foreground" />}
                      {agent.name === 'Technical Analyst' && <BarChart3 className="h-4 w-4 text-muted-foreground" />}
                      {agent.name === 'Risk Analyzer' && <Shield className="h-4 w-4 text-muted-foreground" />}
                      <span className="text-xs sm:text-sm font-medium truncate">{agent.name}</span>
                    </div>
                    <StatusBadge status={agent.status} className="text-xs" />
                    <p className="text-xs text-muted-foreground mt-1">
                      Last: {formatTime(agent.last_run)}
                    </p>
                    <p className="text-xs text-muted-foreground">Signals: {agent.signals_produced}</p>
                  </div>
                  {i < pipeline.agents.length - 1 && (
                    <ChevronRight className="h-5 w-5 text-muted-foreground shrink-0" />
                  )}
                </div>
              ))}
            </div>
          </FlexCard>
        </div>
        <FlexCard title="Instance Connection" className="overflow-visible">
          <div className="space-y-4">
            <Select value={selectedInstance} onValueChange={setSelectedInstance}>
              <SelectTrigger className="w-full [&>span]:min-w-0 [&>span]:truncate">
                <SelectValue placeholder="Connect Instance" />
              </SelectTrigger>
              <SelectContent>
                {instances.map((inst) => (
                  <SelectItem key={inst.id} value={inst.id}>
                    {inst.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              className="w-full"
              onClick={() => deployMutation.mutate()}
              disabled={deployMutation.isPending}
            >
              <Zap className="h-4 w-4 mr-2" />
              Deploy Pipeline
            </Button>
            <div className="flex items-center gap-2 text-sm">
              <div
                className={`h-2 w-2 rounded-full ${
                  pipeline.status === 'deployed' ? 'bg-emerald-500' : 'bg-amber-500'
                }`}
              />
              <span className="text-muted-foreground">
                {pipeline.status === 'deployed' ? 'Deployed' : 'Not deployed'}
              </span>
            </div>
          </div>
        </FlexCard>
      </div>

      {/* Signals Feed */}
      <FlexCard title="Signals Feed" action={<span className="text-xs text-muted-foreground">{signals.length} signals</span>}>
        <div className="rounded-md border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Direction</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Entry</TableHead>
                <TableHead>Stop</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>R:R</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {signalsLoading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 10 }).map((_, j) => (
                      <TableCell key={j}>
                        <Skeleton className="h-5 w-full" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                signals.map((sig) => (
                  <TableRow
                    key={sig.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => setSelectedSignal(sig)}
                  >
                    <TableCell className="text-muted-foreground">{formatTime(sig.time)}</TableCell>
                    <TableCell className="font-mono font-semibold">{sig.symbol}</TableCell>
                    <TableCell>
                      <Badge
                        variant={sig.direction === 'LONG' ? 'default' : 'destructive'}
                        className="uppercase"
                      >
                        {sig.direction === 'LONG' ? (
                          <TrendingUp className="h-3 w-3 mr-1 inline" />
                        ) : (
                          <TrendingDown className="h-3 w-3 mr-1 inline" />
                        )}
                        {sig.direction}
                      </Badge>
                    </TableCell>
                    <TableCell>{(sig.confidence * 100).toFixed(0)}%</TableCell>
                    <TableCell className="text-muted-foreground truncate">{sig.source_agent}</TableCell>
                    <TableCell>${sig.entry_price.toFixed(2)}</TableCell>
                    <TableCell>${sig.stop_loss.toFixed(2)}</TableCell>
                    <TableCell>${sig.take_profit.toFixed(2)}</TableCell>
                    <TableCell>{sig.risk_reward.toFixed(1)}</TableCell>
                    <TableCell>
                      <StatusBadge status={sig.status} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </FlexCard>

      <SidePanel
        open={!!selectedSignal}
        onOpenChange={() => setSelectedSignal(null)}
        title={selectedSignal ? `${selectedSignal.symbol} ${selectedSignal.direction}` : ''}
      >
        {selectedSignal && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <span className="text-muted-foreground">Entry</span>
              <span>${selectedSignal.entry_price.toFixed(2)}</span>
              <span className="text-muted-foreground">Stop Loss</span>
              <span>${selectedSignal.stop_loss.toFixed(2)}</span>
              <span className="text-muted-foreground">Take Profit</span>
              <span>${selectedSignal.take_profit.toFixed(2)}</span>
              <span className="text-muted-foreground">R:R</span>
              <span>{selectedSignal.risk_reward.toFixed(1)}</span>
            </div>
            {selectedSignal.research_note && (
              <div>
                <h4 className="text-sm font-medium mb-2">Research Note</h4>
                <p className="text-sm text-muted-foreground">{selectedSignal.research_note}</p>
              </div>
            )}
            {selectedSignal.technical_chart_ref && (
              <div>
                <h4 className="text-sm font-medium mb-2">Technical Reference</h4>
                <p className="text-sm text-muted-foreground">{selectedSignal.technical_chart_ref}</p>
              </div>
            )}
            {selectedSignal.risk_analysis && (
              <div>
                <h4 className="text-sm font-medium mb-2">Risk Analysis</h4>
                <p className="text-sm text-muted-foreground">{selectedSignal.risk_analysis}</p>
              </div>
            )}
          </div>
        )}
      </SidePanel>
    </div>
  )
}
