/**
 * Daily Signals page — 3-agent pipeline (Research > Technical > Risk) producing daily trade signals.
 * Phoenix v2.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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
  ChevronLeft,
  Calendar,
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getMetricTooltip } from '@/lib/metricTooltips'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
} from 'recharts'

interface Signal {
  id: string
  time: string
  symbol: string
  direction: 'LONG' | 'SHORT' | string
  confidence: number
  source_agent: string
  entry_price: number
  stop_loss: number | null
  take_profit: number | null
  risk_reward: number | null
  status: string
  reasoning?: string
  research_note?: string
  technical_chart_ref?: string
  risk_analysis?: string
  pnl?: number | null
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

interface Analytics {
  win_rate_by_agent: Array<{ agent: string; total: number; wins: number; win_rate: number; avg_return: number }>
  avg_return: number
  avg_rr: number
  total_signals: number
}

const EMPTY_PIPELINE: PipelineStatus = {
  status: 'not_deployed',
  instance_id: null,
  agents: [],
}

const EMPTY_SUMMARY: DailySummary = {
  total_signals_today: 0,
  win_rate_7d: 0,
  avg_rr: 0,
  active_signals: 0,
  pipeline_health: 'degraded',
}

const EMPTY_ANALYTICS: Analytics = {
  win_rate_by_agent: [],
  avg_return: 0,
  avg_rr: 0,
  total_signals: 0,
}

function formatDateParam(d: Date): string {
  return d.toISOString().split('T')[0]
}

function formatDisplayDate(d: Date): string {
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

export default function DailySignalsPage() {
  const [selectedInstance, setSelectedInstance] = useState<string>('')
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null)
  const [tradeDialogSignal, setTradeDialogSignal] = useState<Signal | null>(null)
  const [selectedDate, setSelectedDate] = useState<Date>(new Date())
  const { data: signals = [], isLoading: signalsLoading } = useQuery<Signal[]>({
    queryKey: ['daily-signals', formatDateParam(selectedDate)],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/daily-signals', {
          params: { target_date: formatDateParam(selectedDate) },
        })
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

  const { data: summary = EMPTY_SUMMARY } = useQuery<DailySummary>({
    queryKey: ['daily-signals-summary'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/daily-signals/summary')
        return res.data ?? EMPTY_SUMMARY
      } catch {
        return EMPTY_SUMMARY
      }
    },
    refetchInterval: 60000,
  })

  const { data: analytics = EMPTY_ANALYTICS } = useQuery<Analytics>({
    queryKey: ['daily-signals-analytics'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/daily-signals/analytics')
        return res.data ?? EMPTY_ANALYTICS
      } catch {
        return EMPTY_ANALYTICS
      }
    },
    refetchInterval: 60000,
  })

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data ?? [],
  })

  const formatTime = (iso: string | null | undefined) => {
    if (!iso) return 'N/A'
    const d = new Date(iso)
    return isNaN(d.getTime()) ? 'N/A' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  const navigateDate = (offset: number) => {
    const newDate = new Date(selectedDate)
    newDate.setDate(newDate.getDate() + offset)
    // Don't go into the future
    if (newDate <= new Date()) {
      setSelectedDate(newDate)
    }
  }

  const isToday = formatDateParam(selectedDate) === formatDateParam(new Date())

  // DS7: Build confidence histogram data
  const confidenceHistogram = (() => {
    const buckets = [
      { range: '0-20%', min: 0, max: 0.2, count: 0 },
      { range: '20-40%', min: 0.2, max: 0.4, count: 0 },
      { range: '40-60%', min: 0.4, max: 0.6, count: 0 },
      { range: '60-80%', min: 0.6, max: 0.8, count: 0 },
      { range: '80-100%', min: 0.8, max: 1.01, count: 0 },
    ]
    for (const sig of signals) {
      const conf = sig.confidence ?? 0
      for (const bucket of buckets) {
        if (conf >= bucket.min && conf < bucket.max) {
          bucket.count++
          break
        }
      }
    }
    return buckets.map(b => ({ range: b.range, count: b.count }))
  })()

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Zap} title="Daily Signals" description="3-agent pipeline: Research > Technical > Risk" />

      {/* DS3: Date Navigation */}
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon" onClick={() => navigateDate(-1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md border bg-card">
          <Calendar className="h-4 w-4 text-muted-foreground" />
          <input
            type="date"
            value={formatDateParam(selectedDate)}
            max={formatDateParam(new Date())}
            onChange={(e) => {
              const d = new Date(e.target.value + 'T00:00:00')
              if (!isNaN(d.getTime())) setSelectedDate(d)
            }}
            className="bg-transparent border-none text-sm font-medium focus:outline-none"
          />
        </div>
        <Button variant="outline" size="icon" onClick={() => navigateDate(1)} disabled={isToday}>
          <ChevronRight className="h-4 w-4" />
        </Button>
        {!isToday && (
          <Button variant="ghost" size="sm" onClick={() => setSelectedDate(new Date())}>
            Today
          </Button>
        )}
      </div>

      {/* Daily Summary Cards — DS1: real win rate from backend */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
        <MetricCard title="Total Signals Today" value={summary.total_signals_today} tooltip={getMetricTooltip('Total Signals Today')} />
        <MetricCard
          title="Win Rate (7d)"
          value={`${(summary.win_rate_7d ?? 0).toFixed(1)}%`}
          trend={summary.win_rate_7d > 50 ? 'up' : summary.win_rate_7d > 0 ? 'neutral' : 'down'}
          tooltip={getMetricTooltip('Win Rate')}
        />
        <MetricCard title="Avg R:R" value={(summary.avg_rr ?? 0).toFixed(1)} tooltip={getMetricTooltip('Avg R:R')} />
        <MetricCard title="Active Signals" value={summary.active_signals} tooltip={getMetricTooltip('Active Signals')} />
        <MetricCard
          title="Pipeline Health"
          value={summary.pipeline_health}
          trend={summary.pipeline_health === 'healthy' ? 'up' : 'down'}
          tooltip={getMetricTooltip('Pipeline Health')}
        />
      </div>

      {/* DS5: Signal Performance Dashboard */}
      {(analytics.win_rate_by_agent.length > 0 || analytics.total_signals > 0) && (
        <FlexCard title="Signal Performance (7d)" action={<span className="text-xs text-muted-foreground">{analytics.total_signals} closed trades</span>}>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <MetricCard title="Overall Avg Return" value={`${(analytics.avg_return ?? 0).toFixed(2)}%`} />
            <MetricCard title="Overall Avg R:R" value={(analytics.avg_rr ?? 0).toFixed(2)} />
            <MetricCard title="Total Signals" value={analytics.total_signals} />
          </div>
          {analytics.win_rate_by_agent.length > 0 && (
            <div className="rounded-md border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Agent</TableHead>
                    <TableHead>Total</TableHead>
                    <TableHead>Wins</TableHead>
                    <TableHead>Win Rate</TableHead>
                    <TableHead>Avg Return</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {analytics.win_rate_by_agent.map((row) => (
                    <TableRow key={row.agent}>
                      <TableCell className="font-medium">{row.agent}</TableCell>
                      <TableCell>{row.total}</TableCell>
                      <TableCell>{row.wins}</TableCell>
                      <TableCell>
                        <Badge variant={row.win_rate >= 50 ? 'default' : 'destructive'}>
                          {row.win_rate.toFixed(1)}%
                        </Badge>
                      </TableCell>
                      <TableCell className={row.avg_return >= 0 ? 'text-emerald-600' : 'text-red-600'}>
                        {row.avg_return >= 0 ? '+' : ''}{row.avg_return.toFixed(2)}%
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </FlexCard>
      )}

      {/* Pipeline Visualization + Instance Connection */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
        <div className="lg:col-span-2">
          <FlexCard title="Pipeline">
            <div className="flex flex-wrap items-center gap-4">
              {(pipeline.agents || []).map((agent, i) => (
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
                    <p className="text-xs text-muted-foreground">Signals: {agent.signals_produced ?? 0}</p>
                  </div>
                  {i < (pipeline.agents || []).length - 1 && (
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
                {(instances || []).map((inst) => (
                  <SelectItem key={inst.id} value={inst.id}>
                    {inst.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* DS4: Deploy button disabled with "Coming soon" tooltip */}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="w-full inline-block">
                    <Button
                      className="w-full"
                      disabled
                    >
                      <Zap className="h-4 w-4 mr-2" />
                      Deploy Pipeline
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Coming soon -- pipeline auto-deploy is under development</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
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

      {/* DS7: Confidence Histogram */}
      {signals.length > 0 && (
        <FlexCard title="Signal Confidence Distribution" action={<span className="text-xs text-muted-foreground">{signals.length} signals</span>}>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={confidenceHistogram}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="range" tick={{ fontSize: 12 }} className="fill-muted-foreground" />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} className="fill-muted-foreground" />
                <RechartsTooltip
                  contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }}
                  labelStyle={{ color: 'hsl(var(--foreground))' }}
                />
                <Bar dataKey="count" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </FlexCard>
      )}

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
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {signalsLoading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 11 }).map((_, j) => (
                      <TableCell key={j}>
                        <Skeleton className="h-5 w-full" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : signals.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={11} className="text-center text-muted-foreground py-8">
                    No signals for {formatDisplayDate(selectedDate)}
                  </TableCell>
                </TableRow>
              ) : (
                (signals || []).map((sig) => (
                  <TableRow
                    key={sig.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => setSelectedSignal(sig)}
                  >
                    <TableCell className="text-muted-foreground">{formatTime(sig.time)}</TableCell>
                    <TableCell className="font-mono font-semibold">{sig.symbol ?? 'N/A'}</TableCell>
                    <TableCell>
                      <Badge
                        variant={sig.direction === 'LONG' || sig.direction === 'BUY' ? 'default' : 'destructive'}
                        className="uppercase"
                      >
                        {sig.direction === 'LONG' || sig.direction === 'BUY' ? (
                          <TrendingUp className="h-3 w-3 mr-1 inline" />
                        ) : (
                          <TrendingDown className="h-3 w-3 mr-1 inline" />
                        )}
                        {sig.direction ?? 'N/A'}
                      </Badge>
                    </TableCell>
                    <TableCell>{((sig.confidence ?? 0) * 100).toFixed(0)}%</TableCell>
                    <TableCell className="text-muted-foreground truncate max-w-[120px]">{sig.source_agent ?? 'N/A'}</TableCell>
                    <TableCell>${(sig.entry_price ?? 0).toFixed(2)}</TableCell>
                    <TableCell>{sig.stop_loss != null ? `$${sig.stop_loss.toFixed(2)}` : '--'}</TableCell>
                    <TableCell>{sig.take_profit != null ? `$${sig.take_profit.toFixed(2)}` : '--'}</TableCell>
                    <TableCell>{sig.risk_reward != null ? sig.risk_reward.toFixed(1) : '--'}</TableCell>
                    <TableCell>
                      <StatusBadge status={sig.status ?? 'NEW'} />
                    </TableCell>
                    {/* DS6: One-click trade button */}
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation()
                          setTradeDialogSignal(sig)
                        }}
                      >
                        Trade
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </FlexCard>

      {/* Signal detail side panel */}
      <SidePanel
        open={!!selectedSignal}
        onOpenChange={() => setSelectedSignal(null)}
        title={selectedSignal ? `${selectedSignal.symbol} ${selectedSignal.direction}` : ''}
      >
        {selectedSignal && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <span className="text-muted-foreground">Entry</span>
              <span>${(selectedSignal.entry_price ?? 0).toFixed(2)}</span>
              <span className="text-muted-foreground">Stop Loss</span>
              <span>{selectedSignal.stop_loss != null ? `$${selectedSignal.stop_loss.toFixed(2)}` : '--'}</span>
              <span className="text-muted-foreground">Take Profit</span>
              <span>{selectedSignal.take_profit != null ? `$${selectedSignal.take_profit.toFixed(2)}` : '--'}</span>
              <span className="text-muted-foreground">R:R</span>
              <span>{selectedSignal.risk_reward != null ? selectedSignal.risk_reward.toFixed(1) : '--'}</span>
              {selectedSignal.pnl != null && (
                <>
                  <span className="text-muted-foreground">P&L</span>
                  <span className={selectedSignal.pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}>
                    ${selectedSignal.pnl.toFixed(2)}
                  </span>
                </>
              )}
            </div>
            {selectedSignal.reasoning && (
              <div>
                <h4 className="text-sm font-medium mb-2">Agent Reasoning</h4>
                <p className="text-sm text-muted-foreground">{selectedSignal.reasoning}</p>
              </div>
            )}
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

      {/* DS6: Trade Dialog */}
      <TradeDialog
        signal={tradeDialogSignal}
        onClose={() => setTradeDialogSignal(null)}
      />
    </div>
  )
}

/** DS6: One-click trade dialog pre-filled with signal data */
function TradeDialog({ signal, onClose }: { signal: Signal | null; onClose: () => void }) {
  const [quantity, setQuantity] = useState(1)

  if (!signal) return null

  return (
    <Dialog open={!!signal} onOpenChange={() => onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Trade {signal.symbol} {signal.direction}</DialogTitle>
          <DialogDescription>
            Review and confirm trade parameters from signal
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4 py-4">
          <div>
            <Label className="text-sm text-muted-foreground">Entry Price</Label>
            <Input value={`$${(signal.entry_price ?? 0).toFixed(2)}`} readOnly className="mt-1" />
          </div>
          <div>
            <Label className="text-sm text-muted-foreground">Direction</Label>
            <Input value={signal.direction ?? 'N/A'} readOnly className="mt-1" />
          </div>
          <div>
            <Label className="text-sm text-muted-foreground">Stop Loss</Label>
            <Input
              value={signal.stop_loss != null ? `$${signal.stop_loss.toFixed(2)}` : 'Not set'}
              readOnly
              className="mt-1"
            />
          </div>
          <div>
            <Label className="text-sm text-muted-foreground">Take Profit</Label>
            <Input
              value={signal.take_profit != null ? `$${signal.take_profit.toFixed(2)}` : 'Not set'}
              readOnly
              className="mt-1"
            />
          </div>
          <div>
            <Label className="text-sm text-muted-foreground">Quantity</Label>
            <Input
              type="number"
              min={1}
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
              className="mt-1"
            />
          </div>
          <div>
            <Label className="text-sm text-muted-foreground">Confidence</Label>
            <Input value={`${((signal.confidence ?? 0) * 100).toFixed(0)}%`} readOnly className="mt-1" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-block">
                  <Button disabled>
                    Confirm Trade
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>Coming soon -- one-click execution is under development</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
