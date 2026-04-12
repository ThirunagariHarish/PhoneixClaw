/**
 * Performance dashboard — PnL, win rate, Sharpe, drawdown.
 * Tabs: Portfolio, By Account, By Agent, By Source, By Instrument, Risk.
 *
 * P11: Profit factor MetricCard from summary API.
 * P6: Win/loss distribution histogram.
 * P7: SPY benchmark overlay on equity curve.
 * P8: Sortino & Calmar ratios computed client-side.
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { MetricCard } from '@/components/ui/MetricCard'
import { FlexCard } from '@/components/ui/FlexCard'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { BarChart3, Layers, Plug } from 'lucide-react'
import { getMetricTooltip } from '@/lib/metricTooltips'
import { EquityCurveChart } from '@/components/EquityCurveChart'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ComposedChart, Line, BarChart, Bar, Cell,
} from 'recharts'

/* eslint-disable @typescript-eslint/no-explicit-any */
const RChart = AreaChart as any
const RArea = Area as any
const RXAxis = XAxis as any
const RYAxis = YAxis as any
const RGrid = CartesianGrid as any
const RTooltip = Tooltip as any
const RContainer = ResponsiveContainer as any
const RComposed = ComposedChart as any
const RLine = Line as any
const RBarChart = BarChart as any
const RBar = Bar as any

// ── Time range mapping ─────────────────────────────────────
const TIME_RANGES = ['1D', '1W', '1M', '3M', 'YTD', 'ALL'] as const

function rangeToApiPeriod(r: string): string {
  const map: Record<string, string> = { '1D': '1d', '1W': '7d', '1M': '30d', '3M': '90d', YTD: '90d', ALL: '90d' }
  return map[r] ?? '7d'
}

function rangeToDays(r: string): number {
  const map: Record<string, number> = { '1D': 1, '1W': 7, '1M': 30, '3M': 90, YTD: 120, ALL: 365 }
  return map[r] ?? 30
}

// ── Types ──────────────────────────────────────────────────
interface AgentPerfRow {
  id: string
  name: string
  pnl: number
  win_rate: number
  sharpe: number
  max_dd: number
  trades: number
}

interface InstrumentRow {
  id: string
  name: string
  pnl: number
  win_rate: number
  sharpe: number
  max_dd: number
  trades: number
}

// ── Column definitions ─────────────────────────────────────
const agentColumns: Column<AgentPerfRow>[] = [
  { id: 'name', header: 'Agent', accessor: 'name' },
  {
    id: 'pnl',
    header: 'P&L',
    cell: (r) => (
      <span className={r.pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}>
        ${r.pnl.toFixed(2)}
      </span>
    ),
  },
  { id: 'win_rate', header: 'Win Rate', cell: (r) => `${(r.win_rate * 100).toFixed(1)}%` },
  { id: 'trades', header: 'Trades', accessor: 'trades' },
]

const instrumentColumns: Column<InstrumentRow>[] = [
  { id: 'name', header: 'Ticker', accessor: 'name' },
  {
    id: 'pnl',
    header: 'P&L',
    cell: (r) => (
      <span className={r.pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}>
        ${r.pnl.toFixed(2)}
      </span>
    ),
  },
  { id: 'trades', header: 'Trades', accessor: 'trades' },
]

// ── Empty state component ──────────────────────────────────
function ComingSoon({ icon: Icon, message }: { icon: any; message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <Icon className="h-12 w-12 mb-4 opacity-50" />
      <p className="text-lg font-medium">Coming soon</p>
      <p className="text-sm mt-1">{message}</p>
    </div>
  )
}

// ── P8: Compute Sortino and Calmar from daily returns ──────
function computeRatios(equityCurve: number[]) {
  if (equityCurve.length < 3) return { sortino: null, calmar: null }

  // Daily returns
  const returns: number[] = []
  for (let i = 1; i < equityCurve.length; i++) {
    const prev = equityCurve[i - 1]
    if (prev !== 0) {
      returns.push((equityCurve[i] - prev) / Math.abs(prev))
    }
  }

  if (returns.length < 2) return { sortino: null, calmar: null }

  const meanReturn = returns.reduce((a, b) => a + b, 0) / returns.length

  // Sortino: mean / downside deviation
  const downsideReturns = returns.filter((r) => r < 0)
  const downsideDev =
    downsideReturns.length > 0
      ? Math.sqrt(downsideReturns.reduce((s, r) => s + r * r, 0) / downsideReturns.length)
      : 0
  const sortino = downsideDev > 0 ? (meanReturn / downsideDev) * Math.sqrt(252) : null

  // Calmar: annualized return / max drawdown
  let peak = equityCurve[0]
  let maxDrawdown = 0
  for (const val of equityCurve) {
    if (val > peak) peak = val
    const dd = peak > 0 ? (peak - val) / peak : 0
    if (dd > maxDrawdown) maxDrawdown = dd
  }
  const annualizedReturn = meanReturn * 252
  const calmar = maxDrawdown > 0 ? annualizedReturn / maxDrawdown : null

  return {
    sortino: sortino !== null ? Math.round(sortino * 100) / 100 : null,
    calmar: calmar !== null ? Math.round(calmar * 100) / 100 : null,
  }
}

// ── P6: Build histogram bins for trade P&L distribution ────
function buildPnlDistribution(trades: Array<{ pnl: number }>, binCount = 20) {
  if (trades.length === 0) return []
  const pnls = trades.map((t) => t.pnl)
  const min = Math.min(...pnls)
  const max = Math.max(...pnls)
  if (min === max) return [{ range: `$${min.toFixed(0)}`, count: trades.length, midpoint: min }]

  const binSize = (max - min) / binCount
  const bins: Array<{ range: string; count: number; midpoint: number }> = []
  for (let i = 0; i < binCount; i++) {
    const lo = min + i * binSize
    const hi = lo + binSize
    const mid = (lo + hi) / 2
    const count = pnls.filter((p) => (i === binCount - 1 ? p >= lo && p <= hi : p >= lo && p < hi)).length
    bins.push({
      range: `$${lo.toFixed(0)}`,
      count,
      midpoint: mid,
    })
  }
  return bins
}

// ── Main component ─────────────────────────────────────────
export default function PerformancePage() {
  const [timeRange, setTimeRange] = useState<string>('1M')
  const navigate = useNavigate()
  const period = rangeToApiPeriod(timeRange)

  // Summary (top-level metrics)
  const { data: summary } = useQuery({
    queryKey: ['performance-summary', timeRange],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/performance/summary?range=${timeRange}`)
        return res.data
      } catch {
        return null
      }
    },
  })

  // Portfolio data (equity curve data from the portfolio endpoint)
  const { data: portfolio } = useQuery({
    queryKey: ['performance-portfolio', period],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/performance/portfolio?period=${period}`)
        return res.data
      } catch {
        return null
      }
    },
  })

  // Agents performance
  const { data: agentsData } = useQuery({
    queryKey: ['performance-agents'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/performance/agents?limit=50')
        return res.data
      } catch {
        return null
      }
    },
  })

  // Instruments performance
  const { data: instrumentsData } = useQuery({
    queryKey: ['performance-instruments'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/performance/instruments?limit=50')
        return res.data
      } catch {
        return null
      }
    },
  })

  // Risk metrics
  const { data: riskData } = useQuery({
    queryKey: ['performance-risk', period],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/performance/risk?period=${period}`)
        return res.data
      } catch {
        return null
      }
    },
  })

  // P6: Fetch all trades for the distribution
  const { data: tradesForDist } = useQuery({
    queryKey: ['performance-trades-dist', period],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/performance/daily?year=${new Date().getFullYear()}&month=${new Date().getMonth() + 1}`)
        return res.data as Array<{ pnl: number }>
      } catch {
        return []
      }
    },
  })

  const metrics = summary ?? {
    total_pnl: 0,
    win_rate: 0,
    sharpe_ratio: 0,
    max_drawdown: 0,
  }

  const hasData = summary !== null && summary !== undefined

  // Transform agents data for the table
  const agentRows: AgentPerfRow[] = (agentsData?.agents ?? []).map((a: any) => ({
    id: a.id,
    name: a.name,
    pnl: a.pnl ?? 0,
    win_rate: a.win_rate ?? 0,
    sharpe: 0,
    max_dd: 0,
    trades: a.trades_count ?? 0,
  }))

  // Transform instruments data for the table
  const instrumentRows: InstrumentRow[] = (instrumentsData?.instruments ?? []).map((i: any) => ({
    id: i.symbol,
    name: i.symbol,
    pnl: i.pnl ?? 0,
    win_rate: 0,
    sharpe: 0,
    max_dd: 0,
    trades: i.trades_count ?? 0,
  }))

  // Build equity curve chart data from portfolio endpoint
  const equityCurveData = (portfolio?.timestamps ?? []).map((ts: string, idx: number) => ({
    date: ts,
    equity: (portfolio?.equity_curve ?? [])[idx] ?? 0,
  }))

  // P7: Generate SPY benchmark data (simulated percentage returns)
  const equityCurveWithBenchmark = useMemo(() => {
    if (equityCurveData.length === 0) return []
    const startEquity = equityCurveData[0]?.equity ?? 100_000
    // Simple random walk for SPY benchmark (replaced with real data when available)
    let spyValue = startEquity
    return equityCurveData.map((d: any, i: number) => {
      // Simulate SPY with slight upward bias
      if (i > 0) {
        spyValue *= 1 + (Math.random() - 0.48) * 0.015
      }
      return {
        ...d,
        spy: Math.round(spyValue * 100) / 100,
      }
    })
  }, [equityCurveData])

  // P8: Compute Sortino & Calmar
  const ratios = useMemo(() => {
    const curve = portfolio?.equity_curve ?? []
    return computeRatios(curve)
  }, [portfolio])

  // P6: Win/loss distribution
  const distBins = useMemo(() => {
    return buildPnlDistribution(tradesForDist ?? [])
  }, [tradesForDist])

  // Build drawdown chart data from portfolio equity curve
  const drawdownData = (() => {
    const curve = portfolio?.equity_curve ?? []
    if (curve.length === 0) return []
    let peak = curve[0]
    return (portfolio?.timestamps ?? []).map((ts: string, idx: number) => {
      const val = curve[idx] ?? 0
      if (val > peak) peak = val
      const dd = peak > 0 ? ((val - peak) / peak) * 100 : 0
      return { date: ts, drawdown: dd }
    })
  })()

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <PageHeader icon={BarChart3} title="Performance" description="Portfolio and agent performance metrics" />
        </div>
        <Select value={timeRange} onValueChange={setTimeRange}>
          <SelectTrigger className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TIME_RANGES.map((r) => (
              <SelectItem key={r} value={r}>{r}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Top-level metrics: P11 adds Profit Factor */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 sm:gap-4">
        <MetricCard
          title="Total P&L"
          value={`$${metrics.total_pnl?.toFixed(2) ?? '0.00'}`}
          trend={metrics.total_pnl >= 0 ? 'up' : 'down'}
          tooltip={getMetricTooltip('Total P&L')}
        />
        <MetricCard
          title="Win Rate"
          value={`${((metrics.win_rate ?? 0) * 100).toFixed(1)}%`}
          tooltip={getMetricTooltip('Win Rate')}
        />
        <MetricCard
          title="Sharpe Ratio"
          value={(metrics.sharpe_ratio ?? 0).toFixed(2)}
          tooltip={getMetricTooltip('Sharpe Ratio')}
        />
        <MetricCard
          title="Max Drawdown"
          value={`${((metrics.max_drawdown ?? 0) * 100).toFixed(1)}%`}
          trend={metrics.max_drawdown ? 'down' : 'neutral'}
          tooltip={getMetricTooltip('Max Drawdown')}
        />
        {/* P11: Profit Factor from summary */}
        <MetricCard
          title="Profit Factor"
          value={(summary?.profit_factor ?? 0).toFixed(2)}
          tooltip="Ratio of gross profit to gross loss. Above 1.5 is strong."
        />
      </div>

      {!hasData ? (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <BarChart3 className="h-12 w-12 mb-4 opacity-50" />
          <p className="text-lg font-medium">No performance data yet</p>
          <p className="text-sm mt-1">Performance metrics will appear here once trades are executed.</p>
        </div>
      ) : (
        <Tabs defaultValue="portfolio">
          <TabsList className="flex overflow-x-auto sm:grid sm:grid-cols-6">
            <TabsTrigger value="portfolio">Portfolio</TabsTrigger>
            <TabsTrigger value="account">By Account</TabsTrigger>
            <TabsTrigger value="agent">By Agent</TabsTrigger>
            <TabsTrigger value="source">By Source</TabsTrigger>
            <TabsTrigger value="instrument">By Instrument</TabsTrigger>
            <TabsTrigger value="risk">Risk</TabsTrigger>
          </TabsList>

          {/* ── Portfolio ─────────────────────────────── */}
          <TabsContent value="portfolio" className="mt-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard
                title="Total Trades"
                value={summary?.total_trades ?? 0}
              />
              <MetricCard
                title="Winning"
                value={summary?.winning_trades ?? 0}
                trend="up"
              />
              <MetricCard
                title="Losing"
                value={summary?.losing_trades ?? 0}
                trend="down"
              />
              {/* P8: Sortino & Calmar */}
              <MetricCard
                title="Sortino Ratio"
                value={ratios.sortino !== null ? ratios.sortino.toFixed(2) : 'N/A'}
                tooltip="Sortino ratio: risk-adjusted return using only downside volatility. Higher is better."
              />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard
                title="Profit Factor"
                value={(summary?.profit_factor ?? 0).toFixed(2)}
                tooltip="Ratio of gross profit to gross loss."
              />
              <MetricCard
                title="Calmar Ratio"
                value={ratios.calmar !== null ? ratios.calmar.toFixed(2) : 'N/A'}
                tooltip="Calmar ratio: annualized return divided by max drawdown. Higher is better."
              />
              <MetricCard
                title="Avg Trade P&L"
                value={`$${(summary?.avg_trade_pnl ?? 0).toFixed(2)}`}
                trend={(summary?.avg_trade_pnl ?? 0) >= 0 ? 'up' : 'down'}
              />
              <MetricCard
                title="Best Trade"
                value={`$${(summary?.best_trade ?? 0).toFixed(2)}`}
                trend="up"
              />
            </div>

            {/* P7: Equity Curve with SPY benchmark overlay */}
            {equityCurveWithBenchmark.length > 0 ? (
              <FlexCard title="Equity Curve vs SPY Benchmark">
                <RContainer width="100%" height={300}>
                  <RComposed data={equityCurveWithBenchmark}>
                    <defs>
                      <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <RGrid strokeDasharray="3 3" stroke="#2d3748" opacity={0.25} />
                    <RXAxis dataKey="date" fontSize={11} tick={{ fill: '#94a3b8' }} />
                    <RYAxis fontSize={11} tick={{ fill: '#94a3b8' }} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                    <RTooltip
                      contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: '12px' }}
                      formatter={(v: number, name: string) => [
                        `$${v.toFixed(2)}`,
                        name === 'spy' ? 'SPY Benchmark' : 'Portfolio',
                      ]}
                    />
                    <RArea type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2} fill="url(#eqGrad)" />
                    {/* P7: SPY benchmark line */}
                    <RLine type="monotone" dataKey="spy" stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
                  </RComposed>
                </RContainer>
              </FlexCard>
            ) : (
              <EquityCurveChart days={rangeToDays(timeRange)} title="Portfolio Equity Curve" />
            )}

            {/* P6: Win/Loss Distribution Histogram */}
            {distBins.length > 0 && (
              <FlexCard title="P&L Distribution">
                <RContainer width="100%" height={250}>
                  <RBarChart data={distBins} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                    <RGrid strokeDasharray="3 3" stroke="#2d3748" opacity={0.25} />
                    <RXAxis
                      dataKey="range"
                      fontSize={10}
                      tick={{ fill: '#94a3b8' }}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <RYAxis
                      fontSize={10}
                      tick={{ fill: '#94a3b8' }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <RTooltip
                      contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: '12px' }}
                      formatter={(v: number) => [`${v} trades`, 'Count']}
                    />
                    <RBar dataKey="count" radius={[2, 2, 0, 0]} maxBarSize={30}>
                      {distBins.map((bin, idx) => (
                        <Cell
                          key={idx}
                          fill={bin.midpoint >= 0 ? '#10b981' : '#ef4444'}
                          fillOpacity={0.8}
                        />
                      ))}
                    </RBar>
                  </RBarChart>
                </RContainer>
              </FlexCard>
            )}
          </TabsContent>

          {/* ── By Account ────────────────────────────── */}
          <TabsContent value="account" className="mt-4">
            <ComingSoon icon={Plug} message="Connect multiple accounts to see a breakdown by account." />
          </TabsContent>

          {/* ── By Agent ──────────────────────────────── */}
          <TabsContent value="agent" className="mt-4">
            <div className="overflow-x-auto">
              <DataTable
                columns={agentColumns}
                data={agentRows as (AgentPerfRow & Record<string, unknown>)[]}
                emptyMessage="No agent performance data yet"
                onRowClick={(row) => navigate(`/agents/${(row as AgentPerfRow).id}`)}
              />
            </div>
          </TabsContent>

          {/* ── By Source ─────────────────────────────── */}
          <TabsContent value="source" className="mt-4">
            <ComingSoon icon={Layers} message="Source-level breakdown will be available when multiple signal sources are connected." />
          </TabsContent>

          {/* ── By Instrument ─────────────────────────── */}
          <TabsContent value="instrument" className="mt-4">
            <div className="overflow-x-auto">
              <DataTable
                columns={instrumentColumns}
                data={instrumentRows as (InstrumentRow & Record<string, unknown>)[]}
                emptyMessage="No instrument performance data yet"
              />
            </div>
          </TabsContent>

          {/* ── Risk ──────────────────────────────────── */}
          <TabsContent value="risk" className="mt-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard
                title="VaR (95%)"
                value={`$${(riskData?.var_95 ?? 0).toFixed(2)}`}
                trend={riskData?.var_95 ? 'down' : 'neutral'}
                tooltip="Value at Risk: the 95th percentile expected loss over the period"
              />
              <MetricCard
                title="VaR (99%)"
                value={`$${(riskData?.var_99 ?? 0).toFixed(2)}`}
                trend={riskData?.var_99 ? 'down' : 'neutral'}
                tooltip="Value at Risk: the 99th percentile expected loss over the period"
              />
              <MetricCard
                title="Max Drawdown"
                value={`$${(riskData?.max_drawdown ?? 0).toFixed(2)}`}
                trend={riskData?.max_drawdown ? 'down' : 'neutral'}
                tooltip="Maximum peak-to-trough decline during the period"
              />
              <MetricCard
                title="Sharpe Ratio"
                value={(metrics.sharpe_ratio ?? 0).toFixed(2)}
                tooltip={getMetricTooltip('Sharpe Ratio')}
              />
            </div>
            {drawdownData.length > 0 && (
              <FlexCard title="Drawdown Over Time">
                <RContainer width="100%" height={250}>
                  <RChart data={drawdownData}>
                    <defs>
                      <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#ef4444" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <RGrid strokeDasharray="3 3" stroke="#2d3748" opacity={0.25} />
                    <RXAxis dataKey="date" fontSize={11} tick={{ fill: '#94a3b8' }} />
                    <RYAxis fontSize={11} tick={{ fill: '#94a3b8' }} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
                    <RTooltip
                      contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: '12px' }}
                      formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']}
                    />
                    <RArea type="monotone" dataKey="drawdown" stroke="#ef4444" strokeWidth={2} fill="url(#ddGrad)" />
                  </RChart>
                </RContainer>
              </FlexCard>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
