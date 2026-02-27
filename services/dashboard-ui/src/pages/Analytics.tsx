import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Loader2, XCircle, BarChart3, TrendingUp, TrendingDown,
  Target, Activity, DollarSign, Clock,
} from 'lucide-react'

interface DailyMetric {
  date: string
  total_trades: number
  executed_trades: number
  rejected_trades: number
  errored_trades: number
  closed_positions: number
  total_pnl: number
  winning_trades: number
  losing_trades: number
  avg_win_pct: number
  avg_loss_pct: number
  max_drawdown: number
  avg_execution_latency_ms: number
  avg_slippage_pct: number
  avg_buffer_used: number
  open_positions_eod: number
  portfolio_value: number
  buying_power: number
}

interface Trade {
  id: string
  ticker: string
  side: string
  pnl?: number
  created_at: string
  closed_at?: string
  status: string
}

type TimeRange = 7 | 30 | 90

const TIME_RANGES: { label: string; value: TimeRange }[] = [
  { label: '7d', value: 7 },
  { label: '30d', value: 30 },
  { label: '90d', value: 90 },
]

const TOOLTIP_STYLE = {
  backgroundColor: 'hsl(var(--card))',
  border: '1px solid hsl(var(--border))',
  borderRadius: '8px',
  color: 'hsl(var(--card-foreground))',
}

const TICK_FILL = 'hsl(var(--muted-foreground))'
const TICK_PROPS = { fill: TICK_FILL, fontSize: 12 }
const GREEN = 'hsl(142, 71%, 45%)'
const RED = 'hsl(0, 84%, 60%)'
const DAYS_OF_WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function fmt(n: number, decimals = 2): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toFixed(decimals)
}

function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`
}

function computeSharpe(dailyPnls: number[]): number {
  if (dailyPnls.length < 2) return 0
  const mean = dailyPnls.reduce((a, b) => a + b, 0) / dailyPnls.length
  const variance = dailyPnls.reduce((s, v) => s + (v - mean) ** 2, 0) / (dailyPnls.length - 1)
  const std = Math.sqrt(variance)
  if (std === 0) return 0
  return (mean / std) * Math.sqrt(252)
}

function computeStreaks(metrics: DailyMetric[]): { date: string; streak: number }[] {
  const result: { date: string; streak: number }[] = []
  let current = 0
  for (const m of metrics) {
    if (m.total_pnl > 0) current = current > 0 ? current + 1 : 1
    else if (m.total_pnl < 0) current = current < 0 ? current - 1 : -1
    else current = 0
    result.push({ date: m.date, streak: current })
  }
  return result
}

function computeHistogram(values: number[], bins = 12): { range: string; count: number }[] {
  if (values.length === 0) return []
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) return [{ range: fmt(min), count: values.length }]
  const width = (max - min) / bins
  const buckets = Array.from({ length: bins }, (_, i) => ({
    lo: min + i * width,
    hi: min + (i + 1) * width,
    count: 0,
  }))
  for (const v of values) {
    const idx = Math.min(Math.floor((v - min) / width), bins - 1)
    buckets[idx].count++
  }
  return buckets.map((b) => ({
    range: `${fmt(b.lo, 0)}`,
    count: b.count,
  }))
}

function KpiCard({
  label, value, sub, icon: Icon, trend,
}: {
  label: string
  value: string
  sub?: string
  icon: React.ElementType
  trend?: 'up' | 'down' | 'neutral'
}) {
  const color =
    trend === 'up' ? 'text-green-500' :
    trend === 'down' ? 'text-red-500' :
    'text-muted-foreground'

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className={`text-2xl font-bold ${color}`}>{value}</p>
            {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
          </div>
          <div className="rounded-md bg-muted p-2.5">
            <Icon className="h-5 w-5 text-muted-foreground" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default function Analytics() {
  const [days, setDays] = useState<TimeRange>(30)

  const {
    data: metrics,
    isLoading: metricsLoading,
    isError: metricsError,
    refetch: refetchMetrics,
  } = useQuery<DailyMetric[]>({
    queryKey: ['analytics-metrics', days],
    queryFn: () => axios.get(`/api/v1/metrics/daily?days=${days}`).then((r) => r.data),
    retry: 1,
  })

  const {
    data: trades,
    isLoading: tradesLoading,
    isError: tradesError,
  } = useQuery<Trade[]>({
    queryKey: ['analytics-trades'],
    queryFn: () => axios.get('/api/v1/trades?limit=200').then((r) => r.data),
    retry: 1,
  })

  const isLoading = metricsLoading || tradesLoading
  const isError = metricsError || tradesError
  const safeMetrics = metrics ?? []
  const safeTrades = trades ?? []

  // ── KPI calculations ──
  const kpis = useMemo(() => {
    const totalPnl = safeMetrics.reduce((s, m) => s + (m.total_pnl ?? 0), 0)
    const totalWins = safeMetrics.reduce((s, m) => s + (m.winning_trades ?? 0), 0)
    const totalLosses = safeMetrics.reduce((s, m) => s + (m.losing_trades ?? 0), 0)
    const winRate = totalWins + totalLosses > 0 ? (totalWins / (totalWins + totalLosses)) * 100 : 0
    const dailyPnls = safeMetrics.map((m) => m.total_pnl ?? 0)
    const sharpe = computeSharpe(dailyPnls)
    const maxDd = safeMetrics.length > 0
      ? Math.max(...safeMetrics.map((m) => Math.abs(m.max_drawdown ?? 0)))
      : 0
    const grossWins = safeMetrics.reduce(
      (s, m) => s + (m.total_pnl > 0 ? m.total_pnl : 0), 0,
    )
    const grossLosses = safeMetrics.reduce(
      (s, m) => s + (m.total_pnl < 0 ? Math.abs(m.total_pnl) : 0), 0,
    )
    const profitFactor = grossLosses > 0 ? grossWins / grossLosses : grossWins > 0 ? Infinity : 0

    return { totalPnl, winRate, sharpe, maxDd, profitFactor }
  }, [safeMetrics])

  // ── Cumulative P&L ──
  const cumulativePnl = useMemo(() => {
    let cum = 0
    return safeMetrics.map((m) => {
      cum += m.total_pnl ?? 0
      return { date: m.date, cumulative: cum, daily: m.total_pnl ?? 0 }
    })
  }, [safeMetrics])

  // ── Win rate trend ──
  const winRateData = useMemo(
    () =>
      safeMetrics.map((m) => ({
        date: m.date,
        winRate:
          m.winning_trades && m.total_trades
            ? Math.round((m.winning_trades / m.total_trades) * 100)
            : 0,
      })),
    [safeMetrics],
  )

  // ── Performance by ticker ──
  const tickerPerf = useMemo(() => {
    const map = new Map<string, number>()
    for (const t of safeTrades) {
      if (t.ticker && t.pnl != null) {
        map.set(t.ticker, (map.get(t.ticker) ?? 0) + t.pnl)
      }
    }
    return Array.from(map.entries())
      .map(([ticker, pnl]) => ({ ticker, pnl }))
      .sort((a, b) => b.pnl - a.pnl)
  }, [safeTrades])

  // ── Trade distribution by day of week ──
  const dowDistribution = useMemo(() => {
    const counts = Array(7).fill(0) as number[]
    for (const m of safeMetrics) {
      const d = new Date(m.date).getDay()
      counts[d] += m.total_trades ?? 0
    }
    return DAYS_OF_WEEK.map((day, i) => ({ day, trades: counts[i] }))
  }, [safeMetrics])

  // ── Risk metrics over time ──
  const riskData = useMemo(
    () =>
      safeMetrics.map((m) => ({
        date: m.date,
        drawdown: Math.abs(m.max_drawdown ?? 0),
        slippage: m.avg_slippage_pct ?? 0,
      })),
    [safeMetrics],
  )

  // ── Win/loss streaks ──
  const streakData = useMemo(() => computeStreaks(safeMetrics), [safeMetrics])

  // ── P&L distribution histogram ──
  const pnlHistogram = useMemo(
    () => computeHistogram(safeMetrics.map((m) => m.total_pnl ?? 0)),
    [safeMetrics],
  )

  // ── Loading state ──
  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  // ── Error state ──
  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <XCircle className="h-10 w-10 text-destructive mb-3" />
        <p className="text-lg font-medium">Failed to load analytics</p>
        <Button variant="outline" className="mt-4" onClick={() => refetchMetrics()}>
          Retry
        </Button>
      </div>
    )
  }

  // ── Empty state ──
  if (safeMetrics.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <BarChart3 className="h-10 w-10 text-muted-foreground/40 mb-3" />
        <p className="text-lg font-medium">No analytics data yet</p>
        <p className="text-sm text-muted-foreground mt-1">
          Analytics will populate once trades are executed and daily metrics accumulate.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* ── Time Range Selector ── */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Analytics</h2>
        <div className="flex gap-1">
          {TIME_RANGES.map((r) => (
            <Button
              key={r.value}
              variant={days === r.value ? 'default' : 'outline'}
              size="sm"
              onClick={() => setDays(r.value)}
            >
              {r.label}
            </Button>
          ))}
        </div>
      </div>

      {/* ── KPI Summary Row ── */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard
          label="Total P&L"
          value={`$${fmt(kpis.totalPnl)}`}
          icon={DollarSign}
          trend={kpis.totalPnl > 0 ? 'up' : kpis.totalPnl < 0 ? 'down' : 'neutral'}
        />
        <KpiCard
          label="Win Rate"
          value={fmtPct(kpis.winRate)}
          icon={Target}
          trend={kpis.winRate >= 50 ? 'up' : 'down'}
        />
        <KpiCard
          label="Sharpe Ratio"
          value={kpis.sharpe.toFixed(2)}
          icon={Activity}
          trend={kpis.sharpe > 1 ? 'up' : kpis.sharpe < 0 ? 'down' : 'neutral'}
        />
        <KpiCard
          label="Max Drawdown"
          value={fmtPct(kpis.maxDd)}
          icon={TrendingDown}
          trend="down"
        />
        <KpiCard
          label="Profit Factor"
          value={kpis.profitFactor === Infinity ? '∞' : kpis.profitFactor.toFixed(2)}
          icon={TrendingUp}
          trend={kpis.profitFactor >= 1.5 ? 'up' : kpis.profitFactor < 1 ? 'down' : 'neutral'}
        />
        <KpiCard
          label="Avg Trade Duration"
          value="N/A"
          icon={Clock}
          trend="neutral"
        />
      </div>

      {/* ── Row 1: Cumulative P&L + Win Rate ── */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Cumulative P&L</CardTitle>
            <Badge variant="outline">{days}d</Badge>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={290}>
              <AreaChart data={cumulativePnl}>
                <defs>
                  <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--chart-1))" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={TICK_PROPS} />
                <YAxis tick={TICK_PROPS} tickFormatter={(v: number) => `$${fmt(v, 0)}`} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [`$${fmt(v)}`, 'Cumulative P&L']}
                />
                <Area
                  type="monotone"
                  dataKey="cumulative"
                  stroke="hsl(var(--chart-1))"
                  fill="url(#pnlGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Win Rate Trend</CardTitle>
            <Badge variant="outline">{days}d</Badge>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={290}>
              <LineChart data={winRateData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={TICK_PROPS} />
                <YAxis tick={TICK_PROPS} domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [`${v}%`, 'Win Rate']}
                />
                <Line
                  type="monotone"
                  dataKey="winRate"
                  stroke="hsl(var(--chart-2))"
                  strokeWidth={2}
                  dot={{ r: 3, fill: 'hsl(var(--chart-2))' }}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* ── Row 2: Daily P&L Breakdown + Performance by Ticker ── */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Daily P&L Breakdown</CardTitle>
            <Badge variant="outline">{days}d</Badge>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={290}>
              <BarChart data={cumulativePnl}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={TICK_PROPS} />
                <YAxis tick={TICK_PROPS} tickFormatter={(v: number) => `$${fmt(v, 0)}`} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [`$${fmt(v)}`, 'Daily P&L']}
                />
                <Bar dataKey="daily" radius={[3, 3, 0, 0]}>
                  {cumulativePnl.map((entry, i) => (
                    <Cell key={i} fill={entry.daily >= 0 ? GREEN : RED} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Performance by Ticker</CardTitle>
            <Badge variant="outline">{safeTrades.length} trades</Badge>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={290}>
              <BarChart data={tickerPerf.slice(0, 10)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis type="number" tick={TICK_PROPS} tickFormatter={(v: number) => `$${fmt(v, 0)}`} />
                <YAxis type="category" dataKey="ticker" tick={TICK_PROPS} width={60} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [`$${fmt(v)}`, 'P&L']}
                />
                <Bar dataKey="pnl" radius={[0, 3, 3, 0]}>
                  {tickerPerf.slice(0, 10).map((entry, i) => (
                    <Cell key={i} fill={entry.pnl >= 0 ? GREEN : RED} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* ── Row 3: Day of Week + Risk Metrics ── */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Trade Distribution by Day of Week</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={dowDistribution}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="day" tick={TICK_PROPS} />
                <YAxis tick={TICK_PROPS} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Bar
                  dataKey="trades"
                  fill="hsl(var(--chart-4))"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Risk Metrics Over Time</CardTitle>
            <Badge variant="outline">Drawdown</Badge>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={riskData}>
                <defs>
                  <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--chart-5))" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="hsl(var(--chart-5))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={TICK_PROPS} />
                <YAxis tick={TICK_PROPS} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [`${Number(v).toFixed(2)}%`, 'Drawdown']}
                />
                <Area
                  type="monotone"
                  dataKey="drawdown"
                  stroke="hsl(var(--chart-5))"
                  fill="url(#ddGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* ── Row 4: Win/Loss Streak + P&L Distribution ── */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Win/Loss Streak</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={streakData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={TICK_PROPS} />
                <YAxis tick={TICK_PROPS} allowDecimals={false} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [v, v >= 0 ? 'Win Streak' : 'Loss Streak']}
                />
                <Bar dataKey="streak" radius={[3, 3, 0, 0]}>
                  {streakData.map((entry, i) => (
                    <Cell key={i} fill={entry.streak >= 0 ? GREEN : RED} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">P&L Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={pnlHistogram}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="range" tick={TICK_PROPS} />
                <YAxis tick={TICK_PROPS} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Bar
                  dataKey="count"
                  fill="hsl(var(--chart-3))"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
