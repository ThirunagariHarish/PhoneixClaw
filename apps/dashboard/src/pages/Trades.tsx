/**
 * Trades page — agent leaderboard + trade pipeline.
 * Left: agent performance leaderboard. Right: trade log with filters.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { LayoutDashboard } from 'lucide-react'
import { SidePanel } from '@/components/ui/SidePanel'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { AgentLeaderboardTable, type AgentLeaderData } from '@/components/AgentLeaderCard'

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
  created_at: string
}

interface TradeStats {
  total: number
  filled: number
  rejected: number
  pending: number
}

const STATUS_OPTIONS = ['', 'PENDING', 'RISK_CHECK', 'APPROVED', 'SUBMITTED', 'FILLED', 'REJECTED', 'FAILED']

const columns: Column<Trade>[] = [
  {
    id: 'symbol',
    header: 'Symbol',
    cell: (row) => <span className="font-mono font-semibold">{row.symbol}</span>,
  },
  {
    id: 'side',
    header: 'Side',
    cell: (row) => (
      <Badge variant={row.side === 'buy' ? 'default' : 'destructive'} className="uppercase text-xs">
        {row.side}
      </Badge>
    ),
  },
  { id: 'qty', header: 'Qty', accessor: 'qty' },
  { id: 'order_type', header: 'Type', accessor: 'order_type' },
  {
    id: 'agent_id',
    header: 'Agent',
    cell: (row) => (
      <span className="text-xs font-mono truncate max-w-[80px] inline-block" title={row.agent_id}>
        {row.agent_id.slice(0, 8)}
      </span>
    ),
  },
  {
    id: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  {
    id: 'fill_price',
    header: 'Fill',
    cell: (row) => (row.fill_price ? `$${row.fill_price.toFixed(2)}` : '—'),
  },
  {
    id: 'created_at',
    header: 'Time',
    cell: (row) => new Date(row.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
  },
]

export default function TradesPage() {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)

  const { data: trades = [], isLoading } = useQuery<Trade[]>({
    queryKey: ['trades', statusFilter, symbolFilter],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      if (symbolFilter) params.set('symbol', symbolFilter)
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

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Agent Leaderboard */}
        <div className="lg:col-span-4 xl:col-span-3">
          <AgentLeaderboardTable agents={agentLeaders} />
        </div>

        {/* Trade Log */}
        <div className="lg:col-span-8 xl:col-span-9 space-y-3">
          <div className="flex flex-col sm:flex-row gap-2">
            <Input
              placeholder="Filter by symbol..."
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              className="w-full sm:w-44"
            />
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-full sm:w-36">
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
          </div>

          <div className="overflow-x-auto">
            <DataTable
              columns={columns}
              data={trades as (Trade & Record<string, unknown>)[]}
              isLoading={isLoading}
              emptyMessage="No trades yet. Agents will generate trade intents here."
              onRowClick={(row) => setSelectedTrade(row as unknown as Trade)}
            />
          </div>
        </div>
      </div>

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
              <span>{selectedTrade.fill_price ? `$${selectedTrade.fill_price.toFixed(2)}` : '—'}</span>
              <span className="text-muted-foreground">Agent</span>
              <span
                className="font-mono text-xs cursor-pointer text-primary hover:underline"
                onClick={() => navigate(`/agents/${selectedTrade.agent_id}`)}
              >
                {selectedTrade.agent_id.slice(0, 12)}...
              </span>
              <span className="text-muted-foreground">Source</span>
              <span>{selectedTrade.signal_source ?? '—'}</span>
            </div>
            {selectedTrade.rejection_reason && (
              <div className="p-3 bg-destructive/10 rounded text-sm text-destructive break-words">
                <strong>Rejected:</strong> {selectedTrade.rejection_reason}
              </div>
            )}
          </div>
        )}
      </SidePanel>
    </div>
  )
}
