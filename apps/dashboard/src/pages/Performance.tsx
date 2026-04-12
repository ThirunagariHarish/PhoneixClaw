/**
 * Performance dashboard — PnL, win rate, Sharpe, drawdown.
 * Tabs: Portfolio, By Account, By Agent, By Source, By Instrument, Risk.
 *
 * Portfolio: equity curve + summary metrics.
 * By Agent: real data from /api/v2/performance/agents.
 * By Instrument: real data from /api/v2/performance/instruments.
 * Risk: VaR, max drawdown, drawdown chart from /api/v2/performance/risk.
 * By Account / By Source: placeholder "coming soon" states.
 */
import { useState } from 'react'
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
} from 'recharts'

/* eslint-disable @typescript-eslint/no-explicit-any */
const RChart = AreaChart as any
const RArea = Area as any
const RXAxis = XAxis as any
const RYAxis = YAxis as any
const RGrid = CartesianGrid as any
const RTooltip = Tooltip as any
const RContainer = ResponsiveContainer as any

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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
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
              <MetricCard
                title="Profit Factor"
                value={(summary?.profit_factor ?? 0).toFixed(2)}
              />
            </div>
            {equityCurveData.length > 0 ? (
              <FlexCard title="Equity Curve">
                <RContainer width="100%" height={300}>
                  <RChart data={equityCurveData}>
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
                      formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']}
                    />
                    <RArea type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2} fill="url(#eqGrad)" />
                  </RChart>
                </RContainer>
              </FlexCard>
            ) : (
              <EquityCurveChart days={rangeToDays(timeRange)} title="Portfolio Equity Curve" />
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
