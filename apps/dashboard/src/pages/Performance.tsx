/**
 * Performance dashboard — PnL, win rate, Sharpe, drawdown.
 * Tabs: Portfolio, By Account, By Agent, By Source, By Instrument, Risk.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { MetricCard } from '@/components/ui/MetricCard'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { BarChart3 } from 'lucide-react'
import { getMetricTooltip } from '@/lib/metricTooltips'

const TIME_RANGES = ['1D', '1W', '1M', '3M', 'YTD', 'ALL'] as const

interface PerfRow {
  id: string
  name: string
  pnl: number
  win_rate: number
  sharpe: number
  max_dd: number
  trades: number
}

const perfColumns: Column<PerfRow>[] = [
  { id: 'name', header: 'Name', accessor: 'name' },
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
  { id: 'sharpe', header: 'Sharpe', cell: (r) => r.sharpe.toFixed(2) },
  { id: 'max_dd', header: 'Max DD', cell: (r) => `${(r.max_dd * 100).toFixed(1)}%` },
  { id: 'trades', header: 'Trades', accessor: 'trades' },
]

const EMPTY_PERF: PerfRow[] = []

export default function PerformancePage() {
  const [timeRange, setTimeRange] = useState<string>('1M')
  const navigate = useNavigate()

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

  const metrics = summary ?? {
    total_pnl: 0,
    win_rate: 0,
    sharpe_ratio: 0,
    max_drawdown: 0,
  }

  const hasData = summary !== null && summary !== undefined

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
          trend="down"
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
          <TabsContent value="portfolio" className="mt-4">
            <div className="overflow-x-auto">
            <DataTable columns={perfColumns} data={EMPTY_PERF as (PerfRow & Record<string, unknown>)[]} emptyMessage="No data" />
            </div>
          </TabsContent>
          <TabsContent value="account" className="mt-4">
            <div className="overflow-x-auto">
            <DataTable columns={perfColumns} data={EMPTY_PERF as (PerfRow & Record<string, unknown>)[]} emptyMessage="No data" />
            </div>
          </TabsContent>
          <TabsContent value="agent" className="mt-4">
            <div className="overflow-x-auto">
            <DataTable
              columns={perfColumns}
              data={EMPTY_PERF as (PerfRow & Record<string, unknown>)[]}
              emptyMessage="No data"
              onRowClick={(row) => navigate(`/agents/${(row as PerfRow).id}`)}
            />
            </div>
          </TabsContent>
          <TabsContent value="source" className="mt-4">
            <div className="overflow-x-auto">
            <DataTable columns={perfColumns} data={EMPTY_PERF as (PerfRow & Record<string, unknown>)[]} emptyMessage="No data" />
            </div>
          </TabsContent>
          <TabsContent value="instrument" className="mt-4">
            <div className="overflow-x-auto">
            <DataTable columns={perfColumns} data={EMPTY_PERF as (PerfRow & Record<string, unknown>)[]} emptyMessage="No data" />
            </div>
          </TabsContent>
          <TabsContent value="risk" className="mt-4">
            <div className="overflow-x-auto">
            <DataTable columns={perfColumns} data={EMPTY_PERF as (PerfRow & Record<string, unknown>)[]} emptyMessage="No data" />
            </div>
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
