/**
 * Risk & Compliance — Real-time risk monitoring from the Risk Guardian agent.
 * Phoenix v3.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { MetricCard } from '@/components/ui/MetricCard'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Shield, AlertTriangle, Lock, BarChart3, Activity } from 'lucide-react'
import { cn } from '@/lib/utils'
import { KillSwitchButton, KillSwitchHistory } from '@/components/KillSwitch'
import {
  AreaChart as RechartsAreaChart,
  Area as RechartsArea,
  XAxis as RechartsXAxis,
  YAxis as RechartsYAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer as RechartsResponsiveContainer,
} from 'recharts'
import type { ComponentType } from 'react'

const ResponsiveContainer = RechartsResponsiveContainer as unknown as ComponentType<any>
const AreaChart = RechartsAreaChart as unknown as ComponentType<any>
const Area = RechartsArea as unknown as ComponentType<any>
const XAxis = RechartsXAxis as unknown as ComponentType<any>
const YAxis = RechartsYAxis as unknown as ComponentType<any>
const Tooltip = RechartsTooltip as unknown as ComponentType<any>

type CircuitState = 'NORMAL' | 'WARNING' | 'TRIPPED' | 'COOLDOWN' | 'TRIGGERED'

const EMPTY_CIRCUIT = {
  state: 'NORMAL' as CircuitState,
  dailyLossPct: 0,
  thresholdPct: -5,
  confidence: 0,
  consecutiveLosses: 0,
  triggeredAt: null as string | null,
  reason: null as string | null,
}

const EMPTY_POSITION_LIMITS = {
  sectors: [] as Array<{ name: string; exposure: number; max: number }>,
  tickerConcentration: [] as Array<{ ticker: string; pct: number }>,
  marginUsagePct: 0,
}

const EMPTY_HEDGING = {
  blackSwanStatus: 'INACTIVE',
  protectivePuts: [] as Array<{ symbol: string; strike: number; cost: number; qty: number }>,
  hedgeCostPct: 0,
  portfolioBeta: 0,
}

const circuitBadgeClass: Record<string, string> = {
  NORMAL: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/50',
  WARNING: 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-500/50',
  TRIPPED: 'bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/50',
  TRIGGERED: 'bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/50',
  COOLDOWN: 'bg-slate-500/20 text-slate-700 dark:text-slate-400 border-slate-500/50',
}

function corrColor(val: number): string {
  if (val >= 0.7) return 'bg-red-500 text-white'
  if (val >= 0.4) return 'bg-amber-400'
  if (val >= -0.4) return 'bg-slate-200 dark:bg-slate-700'
  if (val >= -0.7) return 'bg-blue-400'
  return 'bg-blue-600 text-white'
}

export default function RiskCompliancePage() {
  const [selectedInstance, setSelectedInstance] = useState<string>('')
  const [agentPanelOpen, setAgentPanelOpen] = useState(false)
  const [maxDailyLoss, setMaxDailyLoss] = useState(5)
  const [maxSectorExposure, setMaxSectorExposure] = useState(40)
  const queryClient = useQueryClient()

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data ?? [],
  })

  const { data: status = {
    var: 0,
    dailyPnlPct: 0,
    marginUsagePct: 0,
    circuitBreaker: 'NORMAL' as CircuitState,
  } } = useQuery({
    queryKey: ['risk-status'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/status')
        return res.data
      } catch {
        return { var: 0, dailyPnlPct: 0, marginUsagePct: 0, circuitBreaker: 'NORMAL' }
      }
    },
  })

  const { data: circuit = EMPTY_CIRCUIT } = useQuery({
    queryKey: ['risk-circuit'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/status')
        return res.data?.circuit ?? EMPTY_CIRCUIT
      } catch {
        return EMPTY_CIRCUIT
      }
    },
  })

  const { data: positionLimits = EMPTY_POSITION_LIMITS } = useQuery({
    queryKey: ['risk-position-limits'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/position-limits')
        return res.data ?? EMPTY_POSITION_LIMITS
      } catch {
        return EMPTY_POSITION_LIMITS
      }
    },
  })

  const { data: riskChecks = [] } = useQuery({
    queryKey: ['risk-checks'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/checks')
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: compliance = [] } = useQuery({
    queryKey: ['risk-compliance'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/compliance')
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: hedging = EMPTY_HEDGING } = useQuery({
    queryKey: ['risk-hedging'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/hedging')
        return res.data ?? EMPTY_HEDGING
      } catch {
        return EMPTY_HEDGING
      }
    },
  })

  // R4: Margin data
  const { data: marginData = { marginUsed: 0, marginAvailable: 0, marginUsagePct: 0, buyingPower: 0, source: 'unavailable' } } = useQuery({
    queryKey: ['risk-margin'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/margin')
        return res.data ?? { marginUsed: 0, marginAvailable: 0, marginUsagePct: 0, buyingPower: 0, source: 'unavailable' }
      } catch {
        return { marginUsed: 0, marginAvailable: 0, marginUsagePct: 0, buyingPower: 0, source: 'unavailable' }
      }
    },
  })

  // R6: Drawdown data
  const { data: drawdownData = { drawdown: [], maxDrawdownPct: 0, currentDrawdownPct: 0 } } = useQuery({
    queryKey: ['risk-drawdown'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/drawdown')
        return res.data ?? { drawdown: [], maxDrawdownPct: 0, currentDrawdownPct: 0 }
      } catch {
        return { drawdown: [], maxDrawdownPct: 0, currentDrawdownPct: 0 }
      }
    },
  })

  // R7: Correlation matrix
  const { data: corrData = { tickers: [], matrix: [] } } = useQuery({
    queryKey: ['risk-correlation'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/risk/correlation')
        return res.data ?? { tickers: [], matrix: [] }
      } catch {
        return { tickers: [], matrix: [] }
      }
    },
  })

  const createAgentMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/risk/agent/create', {
        instance_id: selectedInstance || 'inst-1',
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['risk-status'] }),
  })

  const resetCircuitMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/risk/circuit-breaker/reset')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['risk-status', 'risk-circuit'] }),
  })

  // R3: Persist risk config
  const saveConfigMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/risk/config', {
        max_daily_loss_pct: maxDailyLoss,
        max_sector_exposure_pct: maxSectorExposure,
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['risk-status', 'risk-position-limits'] }),
  })

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })

  const circuitState = (status.circuitBreaker ?? circuit.state ?? 'NORMAL') as CircuitState
  const checkItems = Array.isArray(riskChecks) ? riskChecks : []
  const complianceItems = Array.isArray(compliance) ? compliance : []
  const sectors = positionLimits.sectors ?? EMPTY_POSITION_LIMITS.sectors
  const tickerConc = positionLimits.tickerConcentration ?? EMPTY_POSITION_LIMITS.tickerConcentration
  const drawdownSeries = Array.isArray(drawdownData.drawdown) ? drawdownData.drawdown : []
  const corrTickers = Array.isArray(corrData.tickers) ? corrData.tickers : []
  const corrMatrix = Array.isArray(corrData.matrix) ? corrData.matrix : []

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Shield} title="Risk & Compliance" description="Real-time risk monitoring and position limits" />

      {/* Emergency Kill Switch */}
      <KillSwitchButton variant="card" />

      {/* Kill Switch History */}
      <FlexCard title="Kill Switch History" action={<AlertTriangle className="h-4 w-4 text-red-500" />}>
        <KillSwitchHistory />
      </FlexCard>

      {/* Top Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <MetricCard
          title="Portfolio VaR"
          value={`$${(status.var ?? 0).toLocaleString()}`}
          subtitle="95% 1-day"
        />
        <MetricCard
          title="Daily P&L"
          value={`$${(status.dailyPnl ?? 0).toLocaleString()}`}
          trend={(status.dailyPnl ?? 0) >= 0 ? 'up' : 'down'}
        />
        <MetricCard
          title="Margin Usage"
          value={`${marginData.marginUsagePct ?? 0}%`}
          subtitle={marginData.source !== 'unavailable' ? `Source: ${marginData.source}` : 'Broker data pending'}
        />
        <div className="flex flex-col justify-center">
          <p className="text-sm font-medium text-muted-foreground mb-1">Circuit Breaker</p>
          <Badge
            variant="outline"
            className={cn('text-lg px-4 py-2 font-bold w-fit', circuitBadgeClass[circuitState] ?? circuitBadgeClass.NORMAL)}
          >
            {circuitState}
          </Badge>
        </div>
      </div>

      {/* Agent Config Panel */}
      {agentPanelOpen && (
        <FlexCard title="Agent Config" className="border-primary/20">
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">Instance</label>
              <Select value={selectedInstance} onValueChange={setSelectedInstance}>
                <SelectTrigger className="mt-1">
                  <SelectValue placeholder="Select instance" />
                </SelectTrigger>
                <SelectContent>
                  {instances.map((inst) => (
                    <SelectItem key={inst.id} value={inst.id}>
                      {inst.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              className="w-full"
              onClick={() => createAgentMutation.mutate()}
              disabled={createAgentMutation.isPending}
            >
              Deploy Risk Guardian
            </Button>
            <div>
              <label className="text-sm font-medium">Max daily loss: {maxDailyLoss}%</label>
              <input
                type="range"
                min="1"
                max="10"
                value={maxDailyLoss}
                onChange={(e) => setMaxDailyLoss(Number(e.target.value))}
                className="w-full mt-1"
              />
            </div>
            <div>
              <label className="text-sm font-medium">Max sector exposure: {maxSectorExposure}%</label>
              <input
                type="range"
                min="20"
                max="50"
                value={maxSectorExposure}
                onChange={(e) => setMaxSectorExposure(Number(e.target.value))}
                className="w-full mt-1"
              />
            </div>
            {/* R3: Save config button */}
            <Button
              variant="outline"
              className="w-full"
              onClick={() => saveConfigMutation.mutate()}
              disabled={saveConfigMutation.isPending}
            >
              {saveConfigMutation.isPending ? 'Saving...' : 'Save Risk Config'}
            </Button>
          </div>
        </FlexCard>
      )}

      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => setAgentPanelOpen(!agentPanelOpen)}>
          <Shield className="h-4 w-4 mr-2" />
          Agent Config
        </Button>
      </div>

      {/* Sub-tabs */}
      <Tabs defaultValue="circuit" className="space-y-4">
        <TabsList className="flex flex-wrap gap-1">
          <TabsTrigger value="circuit" className="gap-1">
            <Activity className="h-4 w-4" />
            Circuit Breaker
          </TabsTrigger>
          <TabsTrigger value="limits" className="gap-1">
            <BarChart3 className="h-4 w-4" />
            Position Limits
          </TabsTrigger>
          <TabsTrigger value="drawdown" className="gap-1">
            <Activity className="h-4 w-4" />
            Drawdown
          </TabsTrigger>
          <TabsTrigger value="correlation" className="gap-1">
            <BarChart3 className="h-4 w-4" />
            Correlation
          </TabsTrigger>
          <TabsTrigger value="checks" className="gap-1">
            <Shield className="h-4 w-4" />
            Risk Checks
          </TabsTrigger>
          <TabsTrigger value="compliance" className="gap-1">
            <Lock className="h-4 w-4" />
            Compliance
          </TabsTrigger>
          <TabsTrigger value="hedging" className="gap-1">
            <AlertTriangle className="h-4 w-4" />
            Hedging
          </TabsTrigger>
        </TabsList>

        <TabsContent value="circuit" className="space-y-4">
          <FlexCard title="Circuit Breaker" action={<Activity className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="font-medium">State</span>
                <Badge variant="outline" className={circuitBadgeClass[circuitState] ?? circuitBadgeClass.NORMAL}>{circuitState}</Badge>
              </div>
              {circuit.triggeredAt && (
                <div className="text-sm text-muted-foreground">
                  Triggered at: {formatTime(circuit.triggeredAt)} {circuit.reason && `-- ${circuit.reason}`}
                </div>
              )}
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Daily loss vs threshold</p>
                <div className="h-4 rounded-full bg-muted overflow-hidden flex">
                  <div
                    className="bg-red-500 h-full"
                    style={{
                      width: `${Math.min(100, Math.abs((circuit.dailyLoss ?? circuit.dailyLossPct ?? 0) / (circuit.thresholdPct ?? -5)) * 100)}%`,
                    }}
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {(circuit.dailyLoss ?? circuit.dailyLossPct ?? 0).toFixed(1)}% / {(circuit.thresholdPct ?? -5)}%
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Confidence</p>
                  <p className="font-semibold">{((circuit.confidence ?? 0) * 100).toFixed(0)}%</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Consecutive losses</p>
                  <p className="font-semibold">{circuit.consecutiveLosses ?? 0}</p>
                </div>
              </div>
              <Button
                variant="outline"
                onClick={() => resetCircuitMutation.mutate()}
                disabled={resetCircuitMutation.isPending || circuitState === 'NORMAL'}
              >
                Reset Circuit Breaker
              </Button>
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="limits" className="space-y-4">
          <FlexCard title="Position Limits" action={<BarChart3 className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              {/* R2: Sector exposure bars */}
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Per-sector exposure vs max</p>
                <div className="space-y-2">
                  {sectors.map((s: { name: string; exposure: number; max: number; breached?: boolean }) => (
                    <div key={s.name} className="flex items-center gap-2">
                      <span className="w-20 sm:w-24 text-sm truncate">{s.name}</span>
                      <div className="flex-1 h-3 rounded bg-muted overflow-hidden">
                        <div
                          className={cn(
                            'h-full rounded',
                            s.exposure / s.max > 0.9 ? 'bg-red-500' : s.exposure / s.max > 0.7 ? 'bg-amber-500' : 'bg-emerald-500'
                          )}
                          style={{ width: `${Math.min(100, (s.exposure / s.max) * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs w-16">{s.exposure}% / {s.max}%</span>
                      {s.breached && <Badge variant="destructive" className="text-xs">Breached</Badge>}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Per-ticker concentration</p>
                <div className="space-y-2">
                  {tickerConc.map((t: { ticker: string; pct: number; breached?: boolean }) => (
                    <div key={t.ticker} className="flex items-center gap-2">
                      <span className="w-12 font-mono">{t.ticker}</span>
                      <div className="flex-1 h-3 rounded bg-muted overflow-hidden">
                        <div className="h-full rounded bg-primary" style={{ width: `${Math.min(100, t.pct * 5)}%` }} />
                      </div>
                      <span className="text-xs">{t.pct}%</span>
                      {t.breached && <Badge variant="destructive" className="text-xs">Over</Badge>}
                    </div>
                  ))}
                </div>
              </div>
              {/* R4: Margin usage */}
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Margin Usage</p>
                <div className="h-4 rounded-full bg-muted overflow-hidden">
                  <div
                    className={cn(
                      'h-full rounded-full',
                      marginData.marginUsagePct > 80 ? 'bg-red-500' : marginData.marginUsagePct > 50 ? 'bg-amber-500' : 'bg-primary'
                    )}
                    style={{ width: `${marginData.marginUsagePct ?? 0}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-muted-foreground mt-1">
                  <span>{marginData.marginUsagePct ?? 0}% used</span>
                  <span>
                    {marginData.source !== 'unavailable'
                      ? `$${(marginData.marginUsed ?? 0).toLocaleString()} / $${(marginData.marginAvailable ?? 0).toLocaleString()}`
                      : 'Broker margin data not available'}
                  </span>
                </div>
                {marginData.buyingPower > 0 && (
                  <p className="text-xs text-muted-foreground mt-1">Buying power: ${marginData.buyingPower.toLocaleString()}</p>
                )}
              </div>
            </div>
          </FlexCard>
        </TabsContent>

        {/* R6: Drawdown chart */}
        <TabsContent value="drawdown" className="space-y-4">
          <FlexCard title="Drawdown Analysis">
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <p className="text-sm text-muted-foreground">Max Drawdown</p>
                <p className="text-xl font-bold text-red-600">{drawdownData.maxDrawdownPct ?? 0}%</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Current Drawdown</p>
                <p className="text-xl font-bold text-amber-600">{drawdownData.currentDrawdownPct ?? 0}%</p>
              </div>
            </div>
            {drawdownSeries.length > 0 ? (
              <div className="h-[300px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={drawdownSeries}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Area type="monotone" dataKey="drawdownPct" name="Drawdown %" stroke="#ef4444" fill="#ef4444" fillOpacity={0.3} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No drawdown data available. Drawdown is computed from closed trades.</p>
            )}
          </FlexCard>
        </TabsContent>

        {/* R7: Correlation matrix */}
        <TabsContent value="correlation" className="space-y-4">
          <FlexCard title="Position Correlation Matrix">
            {corrTickers.length >= 2 && corrMatrix.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="border-collapse text-xs">
                  <thead>
                    <tr>
                      <th className="p-2"></th>
                      {corrTickers.map((t: string) => (
                        <th key={t} className="p-2 font-mono font-bold">{t}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {corrTickers.map((t1: string, i: number) => (
                      <tr key={t1}>
                        <td className="p-2 font-mono font-bold">{t1}</td>
                        {corrMatrix[i]?.map((val: number, j: number) => (
                          <td
                            key={j}
                            className={cn('p-2 text-center min-w-[48px]', corrColor(val))}
                            title={`${t1} vs ${corrTickers[j]}: ${val.toFixed(3)}`}
                          >
                            {val.toFixed(2)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="flex items-center gap-4 mt-3 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500 inline-block" /> High positive</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-amber-400 inline-block" /> Moderate</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-slate-300 inline-block" /> Low</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-blue-500 inline-block" /> Negative</span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {corrData.message ?? 'Need at least 2 open positions for correlation analysis.'}
              </p>
            )}
          </FlexCard>
        </TabsContent>

        <TabsContent value="checks" className="space-y-4">
          <FlexCard title="Risk Checks" action={<Shield className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-2">
              {checkItems.map((c: { ts: string; symbol: string; checkType: string; result: string; reason: string; timestamp?: string; message?: string; level?: string }, i: number) => (
                <div key={i} className="flex flex-col sm:flex-row sm:items-center justify-between p-3 rounded-lg border text-sm gap-2">
                  <div className="flex flex-wrap gap-2 sm:gap-4">
                    <span className="text-muted-foreground">{formatTime(c.ts ?? c.timestamp ?? '')}</span>
                    <span className="font-mono">{c.symbol ?? ''}</span>
                    <span className="text-muted-foreground truncate">{c.checkType ?? c.level ?? ''}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      variant={
                        (c.result ?? c.level) === 'PASS' ? 'default' : (c.result ?? c.level) === 'WARNING' ? 'secondary' : 'destructive'
                      }
                    >
                      {c.result ?? c.level ?? 'INFO'}
                    </Badge>
                    <span className="text-muted-foreground truncate">{c.reason ?? c.message ?? ''}</span>
                  </div>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="compliance" className="space-y-4">
          <FlexCard title="Compliance" action={<Lock className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              {complianceItems.map((a: { id?: string; type: string; message: string; severity: string }, i: number) => (
                <div key={a.id ?? i} className="p-4 rounded-lg border flex items-start gap-3">
                  <AlertTriangle className={cn(
                    'h-5 w-5 shrink-0',
                    a.severity === 'high' ? 'text-red-500' : a.severity === 'medium' ? 'text-amber-500' : 'text-muted-foreground'
                  )} />
                  <div>
                    <Badge variant="outline" className="mb-1">{a.type.replace('_', ' ')}</Badge>
                    <p className="text-sm">{a.message}</p>
                    <p className="text-xs text-muted-foreground mt-1">Severity: {a.severity}</p>
                  </div>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="hedging" className="space-y-4">
          <FlexCard title="Hedging" action={<AlertTriangle className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Black swan hedge status</span>
                <Badge variant={hedging.blackSwanStatus === 'ACTIVE' ? 'default' : 'secondary'}>
                  {hedging.blackSwanStatus}
                </Badge>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Protective puts</p>
                <div className="space-y-2">
                  {(hedging.protectivePuts ?? []).map((p: { symbol?: string; ticker?: string; strike: number; cost?: number; entry_price?: number; qty?: number }, i: number) => (
                    <div key={i} className="p-3 rounded-lg border flex justify-between">
                      <span>{p.symbol ?? p.ticker} ${p.strike} {p.qty ? `x ${p.qty}` : ''}</span>
                      <span className="text-muted-foreground">Cost: ${p.cost ?? p.entry_price ?? 0}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Hedge cost</p>
                  <p className="font-semibold">{(hedging.hedgeCostPct ?? 0).toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Portfolio beta</p>
                  <p className="font-semibold">{hedging.portfolioBeta ?? 0}</p>
                </div>
              </div>
            </div>
          </FlexCard>
        </TabsContent>
      </Tabs>
    </div>
  )
}
