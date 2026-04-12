/**
 * Macro-Pulse — Macro economic intelligence from the Macro-Pulse agent.
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
import {
  LineChart as RechartsLineChart,
  Line as RechartsLine,
  AreaChart as RechartsAreaChart,
  Area as RechartsArea,
  XAxis as RechartsXAxis,
  YAxis as RechartsYAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer as RechartsResponsiveContainer,
  BarChart as RechartsBarChart,
  Bar as RechartsBar,
} from 'recharts'
import type { ComponentType } from 'react'
import { Bot, Calendar, AlertTriangle, Lightbulb } from 'lucide-react'

const ResponsiveContainer = RechartsResponsiveContainer as unknown as ComponentType<any>
const LineChart = RechartsLineChart as unknown as ComponentType<any>
const AreaChart = RechartsAreaChart as unknown as ComponentType<any>
const Area = RechartsArea as unknown as ComponentType<any>
const XAxis = RechartsXAxis as unknown as ComponentType<any>
const YAxis = RechartsYAxis as unknown as ComponentType<any>
const Tooltip = RechartsTooltip as unknown as ComponentType<any>
const Line = RechartsLine as unknown as ComponentType<any>
const BarChart = RechartsBarChart as unknown as ComponentType<any>
const Bar = RechartsBar as unknown as ComponentType<any>

type Severity = 'Critical' | 'High' | 'Medium' | 'Low'

const EMPTY_CPI_DATA: Array<{ month: string; value: number }> = []

const regimeColors: Record<string, string> = {
  'RISK-ON': 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/50',
  'RISK_ON': 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/50',
  'RISK-OFF': 'bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/50',
  'RISK_OFF': 'bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/50',
  'TRANSITION': 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-500/50',
  NEUTRAL: 'bg-slate-500/20 text-slate-700 dark:text-slate-400 border-slate-500/50',
  UNKNOWN: 'bg-slate-500/20 text-slate-700 dark:text-slate-400 border-slate-500/50',
  HAWKISH: 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-500/50',
  DOVISH: 'bg-blue-500/20 text-blue-700 dark:text-blue-400 border-blue-500/50',
}

function trendArrow(trend?: 'up' | 'down' | 'neutral') {
  if (trend === 'up') return '^ '
  if (trend === 'down') return 'v '
  return ''
}

export default function MacroPulsePage() {
  const [selectedInstance, setSelectedInstance] = useState<string>('')
  const [agentPanelOpen, setAgentPanelOpen] = useState(false)
  const [refreshInterval, setRefreshInterval] = useState('30')
  const queryClient = useQueryClient()

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data ?? [],
  })

  const { data: cpiData = EMPTY_CPI_DATA } = useQuery({
    queryKey: ['macro-pulse-cpi'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/cpi')
        return res.data ?? EMPTY_CPI_DATA
      } catch {
        return EMPTY_CPI_DATA
      }
    },
  })

  const { data: regime = { regime: 'NEUTRAL' as string, confidence: 0, updated_at: new Date().toISOString() } } = useQuery({
    queryKey: ['macro-pulse-regime'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/regime')
        return res.data
      } catch {
        return { regime: 'NEUTRAL' as string, confidence: 0, updated_at: new Date().toISOString() }
      }
    },
    refetchInterval: Number(refreshInterval) * 1000,
  })

  const { data: calendar = [] } = useQuery({
    queryKey: ['macro-pulse-calendar'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/calendar')
        return res.data
      } catch {
        return []
      }
    },
  })

  const { data: indicators = [] } = useQuery({
    queryKey: ['macro-pulse-indicators'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/indicators')
        return res.data
      } catch {
        return []
      }
    },
  })

  const { data: geopolitical = [] } = useQuery({
    queryKey: ['macro-pulse-geopolitical'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/geopolitical')
        return res.data
      } catch {
        return []
      }
    },
  })

  const { data: implications = [] } = useQuery({
    queryKey: ['macro-pulse-implications'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/implications')
        return res.data
      } catch {
        return []
      }
    },
  })

  // M2: Sparkline data for VIX, 10Y, DXY
  const { data: sparklines = {} } = useQuery({
    queryKey: ['macro-pulse-sparklines'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/sparklines')
        return res.data ?? {}
      } catch {
        return {}
      }
    },
  })

  // M6: Yield curve data
  const { data: yieldCurve = { curve: [], spread_history: [] } } = useQuery({
    queryKey: ['macro-pulse-yield-curve'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/yield-curve')
        return res.data ?? { curve: [], spread_history: [] }
      } catch {
        return { curve: [], spread_history: [] }
      }
    },
  })

  // M5: FRED data
  const { data: fredData = { gdp: [], unemployment: [], cpi: [] } } = useQuery({
    queryKey: ['macro-pulse-fred'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/macro-pulse/fred-indicators')
        return res.data ?? { gdp: [], unemployment: [], cpi: [] }
      } catch {
        return { gdp: [], unemployment: [], cpi: [] }
      }
    },
  })

  const createAgentMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/macro-pulse/agent/create', {
        instance_id: selectedInstance || 'inst-1',
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['macro-pulse-regime'] }),
  })

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  const mockCalendar = calendar.length
    ? calendar
    : []

  const mockIndicators = indicators.length
    ? indicators
    : []

  const mockGeopolitical = geopolitical.length
    ? geopolitical
    : []

  const mockImplications = implications.length
    ? implications
    : []

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Calendar} title="Macro-Pulse" description="Macro economic intelligence and regime view" />
      {/* Top Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Badge
            variant="outline"
            className={`text-lg px-4 py-2 font-bold ${regimeColors[regime.regime] || regimeColors.NEUTRAL}`}
          >
            {(regime.regime || 'UNKNOWN').replace('_', '-')}
          </Badge>
          <span className="text-sm text-muted-foreground">
            {(regime.confidence ?? 0) * 100}% confidence
          </span>
          <span className="text-xs text-muted-foreground">
            Updated {formatTime(regime.updated_at ?? new Date().toISOString())}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setAgentPanelOpen(!agentPanelOpen)}>
            <Bot className="h-4 w-4 mr-2" />
            Agent Config
          </Button>
          <Button size="sm">
            <Bot className="h-4 w-4 mr-2" />
            Create Agent
          </Button>
        </div>
      </div>

      {/* Agent Config Panel (sidebar/modal) */}
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
              Create Macro-Pulse Agent
            </Button>
            <div className="flex items-center gap-2 text-sm">
              <div className="h-2 w-2 rounded-full bg-emerald-500" />
              <span className="text-muted-foreground">Status: Running</span>
            </div>
            <div>
              <label className="text-sm font-medium">Refresh (sec)</label>
              <Select value={refreshInterval} onValueChange={setRefreshInterval}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="15">15</SelectItem>
                  <SelectItem value="30">30</SelectItem>
                  <SelectItem value="60">60</SelectItem>
                  <SelectItem value="300">300</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </FlexCard>
      )}

      {/* Sub-tabs */}
      <Tabs defaultValue="regime" className="space-y-4">
        <TabsList className="flex flex-wrap h-auto gap-1 w-full lg:w-auto">
          <TabsTrigger value="regime">Regime Overview</TabsTrigger>
          <TabsTrigger value="calendar">Fed Calendar</TabsTrigger>
          <TabsTrigger value="indicators">Economic Indicators</TabsTrigger>
          <TabsTrigger value="yieldcurve">Yield Curve</TabsTrigger>
          <TabsTrigger value="fred">FRED Data</TabsTrigger>
          <TabsTrigger value="geopolitical">Geopolitical Risks</TabsTrigger>
          <TabsTrigger value="implications">Trade Implications</TabsTrigger>
        </TabsList>

        <TabsContent value="regime" className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
            <FlexCard
              title="Current Regime"
              className={
                regime.regime === 'RISK_ON' ? 'border-emerald-500/30 bg-emerald-500/5' :
                regime.regime === 'RISK_OFF' ? 'border-red-500/30 bg-red-500/5' :
                'border-amber-500/30 bg-amber-500/5'
              }
            >
              <p className={`text-lg font-semibold ${
                regime.regime === 'RISK_ON' ? 'text-emerald-600 dark:text-emerald-400' :
                regime.regime === 'RISK_OFF' ? 'text-red-600 dark:text-red-400' :
                'text-amber-600 dark:text-amber-400'
              }`}>
                {regime.regime === 'RISK_ON' ? 'Risk-On' : regime.regime === 'RISK_OFF' ? 'Risk-Off' : 'Transition'}
              </p>
              <p className="text-sm text-muted-foreground">
                {regime.regime === 'RISK_ON' ? 'Equities favored, momentum positive' :
                 regime.regime === 'RISK_OFF' ? 'Defensive positioning, volatility elevated' :
                 'Mixed signals, regime transitioning'}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {Math.round((regime.confidence ?? 0) * 100)}% confidence
              </p>
            </FlexCard>
            <FlexCard
              title="VIX Level"
              className={
                (regime.vix ?? 0) < 20 ? 'border-emerald-500/30 bg-emerald-500/5' :
                (regime.vix ?? 0) < 30 ? 'border-amber-500/30 bg-amber-500/5' :
                'border-red-500/30 bg-red-500/5'
              }
            >
              <p className={`text-lg font-semibold ${
                (regime.vix ?? 0) < 20 ? 'text-emerald-600 dark:text-emerald-400' :
                (regime.vix ?? 0) < 30 ? 'text-amber-600 dark:text-amber-400' :
                'text-red-600 dark:text-red-400'
              }`}>
                {regime.vix ?? 'N/A'}
              </p>
              <p className="text-sm text-muted-foreground">
                {(regime.vix ?? 0) < 15 ? 'Low volatility -- complacency' :
                 (regime.vix ?? 0) < 20 ? 'Normal volatility' :
                 (regime.vix ?? 0) < 30 ? 'Elevated volatility -- caution' :
                 'Fear / crisis levels'}
              </p>
            </FlexCard>
            <FlexCard title="SPY Level" className="border-blue-500/30 bg-blue-500/5">
              <p className="text-lg font-semibold text-blue-600 dark:text-blue-400">
                ${regime.spy ?? 'N/A'}
              </p>
              <p className="text-sm text-muted-foreground">S&P 500 proxy</p>
            </FlexCard>
            <FlexCard title="Regime Score" className="border-slate-500/30 bg-slate-500/5">
              <p className={`text-lg font-semibold ${
                (regime.score ?? 0) > 0 ? 'text-emerald-600 dark:text-emerald-400' :
                (regime.score ?? 0) < 0 ? 'text-red-600 dark:text-red-400' :
                'text-slate-600 dark:text-slate-400'
              }`}>
                {(regime.score ?? 0) > 0 ? '+' : ''}{regime.score ?? 0}
              </p>
              <p className="text-sm text-muted-foreground">
                Composite score (positive = risk-on, negative = risk-off)
              </p>
            </FlexCard>
            {(regime.signals ?? []).length > 0 && (
              <FlexCard title="Regime Signals" className="border-slate-500/30 bg-slate-500/5 sm:col-span-2">
                <ul className="text-sm space-y-1">
                  {(regime.signals ?? []).map((s: { indicator: string; signal: string; value: number }, i: number) => (
                    <li key={i} className="flex justify-between">
                      <span className="font-medium">{s.indicator}</span>
                      <span className="text-muted-foreground">{s.signal} ({s.value})</span>
                    </li>
                  ))}
                </ul>
              </FlexCard>
            )}
          </div>

          {/* M2: VIX, 10Y, DXY sparklines */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 sm:gap-4">
            {(['VIX', '10Y', 'DXY'] as const).map((key) => {
              const points = (sparklines as any)[key] ?? []
              return (
                <FlexCard key={key} title={`${key} (30d)`}>
                  {points.length > 0 ? (
                    <div className="h-[120px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={points}>
                          <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(d: string) => d.slice(5)} />
                          <YAxis tick={{ fontSize: 10 }} domain={['auto', 'auto']} />
                          <Tooltip />
                          <Line type="monotone" dataKey="value" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">Loading...</p>
                  )}
                </FlexCard>
              )
            })}
          </div>
        </TabsContent>

        <TabsContent value="calendar" className="space-y-4">
          <FlexCard title="Fed Calendar" action={<Calendar className="h-4 w-4 text-muted-foreground" />}>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
              {mockCalendar.map((ev: { id: string; date: string; event: string; impact: string; forecast?: string | null; actual?: string | null; surprise?: string | null; prior?: string | null }) => (
                <div
                  key={ev.id}
                  className="p-4 rounded-lg border bg-card hover:bg-muted/30 transition-colors"
                >
                  <p className="font-mono text-sm text-muted-foreground">{ev.date}</p>
                  <p className="font-semibold mt-1">{ev.event}</p>
                  <Badge
                    variant={ev.impact === 'HIGH' ? 'destructive' : ev.impact === 'MEDIUM' ? 'default' : 'secondary'}
                    className="mt-2"
                  >
                    {ev.impact}
                  </Badge>
                  {/* M7: Consensus vs actual */}
                  <div className="mt-2 grid grid-cols-2 gap-1 text-xs">
                    {ev.forecast != null && (
                      <>
                        <span className="text-muted-foreground">Forecast:</span>
                        <span>{ev.forecast}</span>
                      </>
                    )}
                    {ev.actual != null && (
                      <>
                        <span className="text-muted-foreground">Actual:</span>
                        <span className="font-semibold">{ev.actual}</span>
                      </>
                    )}
                    {ev.surprise != null && (
                      <>
                        <span className="text-muted-foreground">Surprise:</span>
                        <span className={Number(ev.surprise) > 0 ? 'text-emerald-600' : 'text-red-600'}>{ev.surprise}</span>
                      </>
                    )}
                    {ev.prior != null && (
                      <>
                        <span className="text-muted-foreground">Prior:</span>
                        <span>{ev.prior}</span>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="indicators" className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 sm:gap-4">
            {mockIndicators.map((ind: { name: string; value: string; trend?: 'up' | 'down' | 'neutral' }) => (
              <MetricCard
                key={ind.name}
                title={ind.name}
                value={`${trendArrow(ind.trend)}${ind.value}`}
                trend={ind.trend}
              />
            ))}
          </div>
          <FlexCard title="CPI (YoY %)">
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={cpiData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} domain={[2.5, 4]} />
                  <Tooltip />
                  <Line type="monotone" dataKey="value" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </FlexCard>
        </TabsContent>

        {/* M6: Yield Curve tab */}
        <TabsContent value="yieldcurve" className="space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
            <FlexCard title="Yield Curve (Current)">
              {(yieldCurve.curve ?? []).length > 0 ? (
                <div className="h-[300px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={yieldCurve.curve}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="maturity" tick={{ fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 12 }} />
                      <Tooltip formatter={(v: number) => `${v.toFixed(3)}%`} />
                      <Bar dataKey="yield_pct" name="Yield %" fill="hsl(var(--primary))" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No yield curve data available</p>
              )}
            </FlexCard>

            <FlexCard title="Spread History (10Y - 3M)">
              {(yieldCurve.spread_history ?? []).length > 0 ? (
                <div className="h-[300px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={yieldCurve.spread_history}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Area type="monotone" dataKey="spread" name="Spread" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No spread data available</p>
              )}
            </FlexCard>
          </div>
        </TabsContent>

        {/* M5: FRED Data tab */}
        <TabsContent value="fred" className="space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
            <FlexCard title="GDP Growth (FRED)">
              {(fredData.gdp ?? []).length > 0 ? (
                <div className="h-[200px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={fredData.gdp}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(d: string) => d.slice(0, 7)} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">FRED API key required for GDP data</p>
              )}
            </FlexCard>

            <FlexCard title="Unemployment Rate (FRED)">
              {(fredData.unemployment ?? []).length > 0 ? (
                <div className="h-[200px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={fredData.unemployment}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(d: string) => d.slice(0, 7)} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Line type="monotone" dataKey="value" stroke="#ef4444" strokeWidth={2} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">FRED API key required for unemployment data</p>
              )}
            </FlexCard>

            <FlexCard title="CPI YoY % (FRED)">
              {(fredData.cpi ?? []).length > 0 ? (
                <div className="h-[200px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={fredData.cpi}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(d: string) => d.slice(0, 7)} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Line type="monotone" dataKey="value" stroke="#f59e0b" strokeWidth={2} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">FRED API key required for CPI data</p>
              )}
            </FlexCard>
          </div>
        </TabsContent>

        <TabsContent value="geopolitical" className="space-y-4">
          <FlexCard title="Geopolitical Risks" action={<AlertTriangle className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              {mockGeopolitical.map(
                (r: {
                  id: string
                  title: string
                  severity: Severity
                  sectors: string[]
                  impact: string
                }) => (
                  <div key={r.id} className="p-4 rounded-lg border">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <p className="font-semibold">{r.title}</p>
                      <Badge
                        variant={
                          r.severity === 'Critical'
                            ? 'destructive'
                            : r.severity === 'High'
                              ? 'default'
                              : 'secondary'
                        }
                      >
                        {r.severity}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">
                      Sectors: {r.sectors.join(', ')}
                    </p>
                    <p className="text-sm mt-2">Impact: {r.impact}</p>
                  </div>
                )
              )}
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="implications" className="space-y-4">
          <FlexCard title="Trade Implications" action={<Lightbulb className="h-4 w-4 text-muted-foreground" />}>
            <ul className="space-y-3">
              {mockImplications.map((imp: string, i: number) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="text-primary mt-0.5">*</span>
                  <span>{imp}</span>
                </li>
              ))}
            </ul>
          </FlexCard>
        </TabsContent>
      </Tabs>
    </div>
  )
}
