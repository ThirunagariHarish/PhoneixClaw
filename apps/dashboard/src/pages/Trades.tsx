/**
 * Trades page — agent leaderboard + trade pipeline.
 * Left: agent performance leaderboard. Right: trade log with filters.
 *
 * Features: P&L columns, date range filter, pagination, column sorting,
 * equity curve chart, CSV export, trade journal notes.
 */
import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { LayoutDashboard, Download, ChevronLeft, ChevronRight, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { SidePanel } from '@/components/ui/SidePanel'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { AgentLeaderboardTable, type AgentLeaderData } from '@/components/AgentLeaderCard'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer } from 'recharts'
import { cn } from '@/lib/utils'

interface Trade {
  id: string
  agent_id: string
  account_id: string
  symbol: string
  side: string
  qty: number
  order_type: string
  limit_price: number | null
  stop_price: number | null
  status: string
  fill_price: number | null
  filled_at: string | null
  rejection_reason: string | null
  signal_source: string | null
  pnl_dollar: number | null
  pnl_pct: number | null
  notes: string | null
  created_at: string
}

interface TradeStats {
  total: number
  filled: number
  rejected: number
  pending: number
}

interface EquityPoint {
  date: string
  equity: number
  daily_return: number
}

type SortField = 'symbol' | 'side' | 'qty' | 'status' | 'fill_price' | 'created_at' | 'pnl_dollar'
type SortDir = 'asc' | 'desc'

const STATUS_OPTIONS = ['', 'PENDING', 'RISK_CHECK', 'APPROVED', 'SUBMITTED', 'FILLED', 'REJECTED', 'FAILED']
const PAGE_SIZE = 25

function pnlColor(v: number | null | undefined): string {
  if (v == null || v === 0) return ''
  return v > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
}

export default function TradesPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [sortField, setSortField] = useState<SortField>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)
  const [editingNotes, setEditingNotes] = useState('')

  // Trade count for pagination
  const { data: countData } = useQuery<{ count: number }>({
    queryKey: ['trade-count', statusFilter, symbolFilter, dateFrom, dateTo],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      if (symbolFilter) params.set('symbol', symbolFilter)
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo) params.set('date_to', dateTo)
      return (await api.get(`/api/v2/trades/count?${params}`)).data
    },
    refetchInterval: 10000,
  })

  const totalCount = countData?.count ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))

  const { data: trades = [], isLoading } = useQuery<Trade[]>({
    queryKey: ['trades', statusFilter, symbolFilter, dateFrom, dateTo, page, sortField, sortDir],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      if (symbolFilter) params.set('symbol', symbolFilter)
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo) params.set('date_to', dateTo)
      params.set('limit', String(PAGE_SIZE))
      params.set('offset', String(page * PAGE_SIZE))
      params.set('sort_by', sortField)
      params.set('sort_dir', sortDir)
      const res = await api.get(`/api/v2/trades?${params}`)
      return res.data
    },
    refetchInterval: 5000,
  })

  const { data: stats } = useQuery<TradeStats>({
    queryKey: ['trade-stats'],
    queryFn: async () => (await api.get('/api/v2/trades/stats')).data,
    refetchInterval: 10000,
  })

  const { data: agentLeaders = [] } = useQuery<AgentLeaderData[]>({
    queryKey: ['trade-agent-leaders'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/performance/by-agent')
        return res.data ?? []
      } catch {
        return []
      }
    },
    refetchInterval: 30000,
  })

  // Equity curve
  const { data: equityCurve = [] } = useQuery<EquityPoint[]>({
    queryKey: ['equity-curve'],
    queryFn: async () => {
      try {
        return (await api.get('/api/v2/portfolio/equity-curve?days=90')).data ?? []
      } catch {
        return []
      }
    },
    refetchInterval: 60000,
  })

  // Notes mutation
  const notesMutation = useMutation({
    mutationFn: async ({ tradeId, notes }: { tradeId: string; notes: string }) => {
      return (await api.patch(`/api/v2/trades/${tradeId}/notes`, { notes })).data
    },
    onSuccess: (data: Trade) => {
      qc.invalidateQueries({ queryKey: ['trades'] })
      setSelectedTrade(data)
    },
  })

  // Sort toggle
  const toggleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('asc')
    }
    setPage(0)
  }, [sortField])

  // CSV export
  const exportCSV = useCallback(() => {
    const headers = ['Symbol', 'Side', 'Qty', 'Type', 'Status', 'Fill Price', 'P&L $', 'P&L %', 'Time']
    const csvRows = [headers.join(',')]
    for (const t of trades) {
      csvRows.push([
        t.symbol,
        t.side,
        t.qty,
        t.order_type,
        t.status,
        t.fill_price ?? '',
        t.pnl_dollar ?? '',
        t.pnl_pct ?? '',
        t.created_at,
      ].join(','))
    }
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `trades_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [trades])

  // Sort header component
  const SortHeader = ({ field, label }: { field: SortField; label: string }) => (
    <TableHead
      className="cursor-pointer select-none hover:text-foreground transition-colors"
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortField === field ? (
          sortDir === 'asc' ? <ArrowUp className="h-3 w-3 text-primary" /> : <ArrowDown className="h-3 w-3 text-primary" />
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30" />
        )}
      </span>
    </TableHead>
  )

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={LayoutDashboard} title="Trades" description="Agent performance leaderboard and trade pipeline" />

      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
          <MetricCard title="Total Trades" value={stats.total} />
          <MetricCard title="Filled" value={stats.filled} trend="up" />
          <MetricCard title="Rejected" value={stats.rejected} trend="down" />
          <MetricCard title="Pending" value={stats.pending} trend="neutral" />
        </div>
      )}

      {/* Equity Curve Chart */}
      {equityCurve.length > 1 && (
        <Card>
          <CardHeader className="pb-2">
            <h3 className="text-sm font-semibold">Cumulative P&L (Equity Curve)</h3>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={equityCurve} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <defs>
                  <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  className="fill-muted-foreground"
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  className="fill-muted-foreground"
                  tickFormatter={(v: number) => `$${v.toLocaleString()}`}
                />
                <ReTooltip
                  contentStyle={{
                    backgroundColor: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px',
                    fontSize: 12,
                  }}
                  formatter={(value: number) => [`$${value.toFixed(2)}`, 'Equity']}
                />
                <Area
                  type="monotone"
                  dataKey="equity"
                  stroke="hsl(var(--primary))"
                  fill="url(#equityGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Agent Leaderboard */}
        <div className="lg:col-span-4 xl:col-span-3">
          <AgentLeaderboardTable agents={agentLeaders} />
        </div>

        {/* Trade Log */}
        <div className="lg:col-span-8 xl:col-span-9 space-y-3">
          {/* Filters Row */}
          <div className="flex flex-col sm:flex-row gap-2 flex-wrap items-end">
            <Input
              placeholder="Filter by symbol..."
              value={symbolFilter}
              onChange={(e) => { setSymbolFilter(e.target.value); setPage(0) }}
              className="w-full sm:w-36"
            />
            <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v === ' ' ? '' : v); setPage(0) }}>
              <SelectTrigger className="w-full sm:w-32">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((s) => (
                  <SelectItem key={s || '__all'} value={s || ' '}>
                    {s || 'All'}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex gap-1 items-center">
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => { setDateFrom(e.target.value); setPage(0) }}
                className="w-36 text-xs"
                placeholder="From"
              />
              <span className="text-muted-foreground text-xs">to</span>
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => { setDateTo(e.target.value); setPage(0) }}
                className="w-36 text-xs"
                placeholder="To"
              />
            </div>
            <Button variant="outline" size="sm" onClick={exportCSV} className="gap-1">
              <Download className="h-3.5 w-3.5" /> Export CSV
            </Button>
          </div>

          {/* Trades Table */}
          <div className="rounded-xl border border-border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <SortHeader field="symbol" label="Symbol" />
                  <SortHeader field="side" label="Side" />
                  <SortHeader field="qty" label="Qty" />
                  <TableHead>Type</TableHead>
                  <TableHead>Agent</TableHead>
                  <SortHeader field="status" label="Status" />
                  <SortHeader field="fill_price" label="Fill" />
                  <SortHeader field="pnl_dollar" label="P&L $" />
                  <TableHead>P&L %</TableHead>
                  <SortHeader field="created_at" label="Time" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 10 }).map((__, j) => (
                        <TableCell key={j}><Skeleton className="h-6 w-full" /></TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : trades.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                      No trades yet. Agents will generate trade intents here.
                    </TableCell>
                  </TableRow>
                ) : (
                  trades.map((trade) => (
                    <TableRow
                      key={trade.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => { setSelectedTrade(trade); setEditingNotes(trade.notes ?? '') }}
                    >
                      <TableCell><span className="font-mono font-semibold">{trade.symbol}</span></TableCell>
                      <TableCell>
                        <Badge variant={trade.side === 'buy' ? 'default' : 'destructive'} className="uppercase text-xs">
                          {trade.side}
                        </Badge>
                      </TableCell>
                      <TableCell>{trade.qty}</TableCell>
                      <TableCell>{trade.order_type}</TableCell>
                      <TableCell>
                        <span className="text-xs font-mono truncate max-w-[80px] inline-block" title={trade.agent_id}>
                          {trade.agent_id.slice(0, 8)}
                        </span>
                      </TableCell>
                      <TableCell><StatusBadge status={trade.status} /></TableCell>
                      <TableCell>{trade.fill_price ? `$${trade.fill_price.toFixed(2)}` : '\u2014'}</TableCell>
                      <TableCell>
                        <span className={cn('font-mono tabular-nums', pnlColor(trade.pnl_dollar))}>
                          {trade.pnl_dollar != null ? `${trade.pnl_dollar >= 0 ? '+' : ''}$${trade.pnl_dollar.toFixed(2)}` : '\u2014'}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className={cn('font-mono tabular-nums', pnlColor(trade.pnl_pct))}>
                          {trade.pnl_pct != null ? `${trade.pnl_pct >= 0 ? '+' : ''}${trade.pnl_pct.toFixed(2)}%` : '\u2014'}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        {new Date(trade.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {totalCount} trade{totalCount !== 1 ? 's' : ''} total
              {totalCount > 0 && ` \u00b7 Page ${page + 1} of ${totalPages}`}
            </span>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                <ChevronLeft className="h-4 w-4" /> Prev
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
              >
                Next <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Trade Detail Side Panel */}
      <SidePanel
        open={!!selectedTrade}
        onOpenChange={() => setSelectedTrade(null)}
        title={selectedTrade ? `Trade: ${selectedTrade.symbol}` : ''}
      >
        {selectedTrade && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <span className="text-muted-foreground">Symbol</span>
              <span className="font-mono">{selectedTrade.symbol}</span>
              <span className="text-muted-foreground">Side</span>
              <span className="uppercase">{selectedTrade.side}</span>
              <span className="text-muted-foreground">Quantity</span>
              <span>{selectedTrade.qty}</span>
              <span className="text-muted-foreground">Status</span>
              <StatusBadge status={selectedTrade.status} />
              <span className="text-muted-foreground">Fill Price</span>
              <span>{selectedTrade.fill_price ? `$${selectedTrade.fill_price.toFixed(2)}` : '\u2014'}</span>
              <span className="text-muted-foreground">P&L $</span>
              <span className={cn('font-mono', pnlColor(selectedTrade.pnl_dollar))}>
                {selectedTrade.pnl_dollar != null ? `${selectedTrade.pnl_dollar >= 0 ? '+' : ''}$${selectedTrade.pnl_dollar.toFixed(2)}` : '\u2014'}
              </span>
              <span className="text-muted-foreground">P&L %</span>
              <span className={cn('font-mono', pnlColor(selectedTrade.pnl_pct))}>
                {selectedTrade.pnl_pct != null ? `${selectedTrade.pnl_pct >= 0 ? '+' : ''}${selectedTrade.pnl_pct.toFixed(2)}%` : '\u2014'}
              </span>
              <span className="text-muted-foreground">Agent</span>
              <span
                className="font-mono text-xs cursor-pointer text-primary hover:underline"
                onClick={() => navigate(`/agents/${selectedTrade.agent_id}`)}
              >
                {selectedTrade.agent_id.slice(0, 12)}...
              </span>
              <span className="text-muted-foreground">Source</span>
              <span>{selectedTrade.signal_source ?? '\u2014'}</span>
            </div>
            {selectedTrade.rejection_reason && (
              <div className="p-3 bg-destructive/10 rounded text-sm text-destructive break-words">
                <strong>Rejected:</strong> {selectedTrade.rejection_reason}
              </div>
            )}

            {/* Trade Journal Notes */}
            <div className="space-y-2 pt-2 border-t">
              <label className="text-sm font-medium">Journal Notes</label>
              <Textarea
                value={editingNotes}
                onChange={(e) => setEditingNotes(e.target.value)}
                placeholder="Add notes about this trade..."
                rows={4}
              />
              <Button
                size="sm"
                disabled={notesMutation.isPending || editingNotes === (selectedTrade.notes ?? '')}
                onClick={() => notesMutation.mutate({ tradeId: selectedTrade.id, notes: editingNotes })}
              >
                {notesMutation.isPending ? 'Saving...' : 'Save Notes'}
              </Button>
            </div>
          </div>
        )}
      </SidePanel>
    </div>
  )
}
