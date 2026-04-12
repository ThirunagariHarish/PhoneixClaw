/**
 * Positions page — account-level view of open and closed positions.
 *
 * Features: close position button, detail side panel, P&L % column,
 * edit SL/TP, portfolio allocation donut, position grouping,
 * exposure summary cards, column sorting + filter.
 */
import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useRealtimeQuery } from '@/hooks/use-websocket'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { SidePanel } from '@/components/ui/SidePanel'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { TrendingUp, X, ArrowUpDown, ArrowUp, ArrowDown, Pencil } from 'lucide-react'
import { PieChart, Pie, Cell, Tooltip as ReTooltip, ResponsiveContainer, Legend } from 'recharts'
import { cn } from '@/lib/utils'

interface PositionData {
  id: string
  agent_id: string
  account_id: string
  symbol: string
  side: string
  qty: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  realized_pnl: number
  stop_loss: number | null
  take_profit: number | null
  status: string
  exit_price: number | null
  exit_reason: string | null
  opened_at: string
  closed_at: string | null
}

interface PositionSummary {
  open_positions: number
  total_unrealized_pnl: number
  total_realized_pnl: number
}

type SortField = 'symbol' | 'side' | 'qty' | 'entry_price' | 'current_price' | 'unrealized_pnl' | 'pnl_pct' | 'opened_at'
type SortDir = 'asc' | 'desc'
type GroupBy = 'none' | 'agent' | 'symbol'

const PIE_COLORS = [
  'hsl(var(--primary))',
  '#f59e0b', '#06b6d4', '#8b5cf6', '#ec4899',
  '#10b981', '#f97316', '#6366f1', '#14b8a6',
  '#e11d48', '#84cc16', '#0ea5e9',
]

function pnlColor(pnl: number) {
  if (pnl > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (pnl < 0) return 'text-red-600 dark:text-red-400'
  return ''
}

function calcPnlPct(pos: PositionData): number {
  if (pos.entry_price === 0) return 0
  const diff = pos.status === 'OPEN'
    ? pos.current_price - pos.entry_price
    : (pos.exit_price ?? pos.current_price) - pos.entry_price
  const multiplier = pos.side === 'long' ? 1 : -1
  return (diff / pos.entry_price) * 100 * multiplier
}

function timeSince(dateStr: string): string {
  const ms = Date.now() - new Date(dateStr).getTime()
  const hours = Math.floor(ms / 3600000)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d`
}

export default function PositionsPage() {
  const qc = useQueryClient()

  // Real-time updates via WebSocket
  useRealtimeQuery({
    channel: 'positions',
    queryKeys: [['positions-open'], ['positions-closed'], ['position-summary']],
  })

  // State
  const [selectedPosition, setSelectedPosition] = useState<PositionData | null>(null)
  const [closingPosition, setClosingPosition] = useState<PositionData | null>(null)
  const [editingSLTP, setEditingSLTP] = useState<PositionData | null>(null)
  const [slValue, setSlValue] = useState('')
  const [tpValue, setTpValue] = useState('')
  const [sortField, setSortField] = useState<SortField>('unrealized_pnl')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [filterText, setFilterText] = useState('')
  const [groupBy, setGroupBy] = useState<GroupBy>('none')

  // Queries
  const { data: openPositions = [], isLoading: openLoading } = useQuery<PositionData[]>({
    queryKey: ['positions-open'],
    queryFn: async () => (await api.get('/api/v2/positions?status=OPEN')).data,
    refetchInterval: 30000,
  })

  const { data: closedPositions = [], isLoading: closedLoading } = useQuery<PositionData[]>({
    queryKey: ['positions-closed'],
    queryFn: async () => (await api.get('/api/v2/positions/closed')).data,
    refetchInterval: 60000,
  })

  const { data: summary } = useQuery<PositionSummary>({
    queryKey: ['position-summary'],
    queryFn: async () => (await api.get('/api/v2/positions/summary')).data,
    refetchInterval: 30000,
  })

  // Mutations
  const closeMutation = useMutation({
    mutationFn: async (pos: PositionData) => {
      return (await api.post(`/api/v2/positions/${pos.id}/close`, {
        exit_price: pos.current_price,
        exit_reason: 'manual_close',
      })).data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['positions-open'] })
      qc.invalidateQueries({ queryKey: ['positions-closed'] })
      qc.invalidateQueries({ queryKey: ['position-summary'] })
      setClosingPosition(null)
    },
  })

  const updateSLTP = useMutation({
    mutationFn: async ({ id, stop_loss, take_profit }: { id: string; stop_loss: number | null; take_profit: number | null }) => {
      return (await api.patch(`/api/v2/positions/${id}`, { stop_loss, take_profit })).data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['positions-open'] })
      setEditingSLTP(null)
    },
  })

  // Sort toggle
  const toggleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('desc')
    }
  }, [sortField])

  // Filtered + sorted open positions
  const filteredOpen = useMemo(() => {
    let rows = [...openPositions]
    if (filterText) {
      const ft = filterText.toUpperCase()
      rows = rows.filter((p) => p.symbol.includes(ft) || p.agent_id.includes(filterText))
    }
    rows.sort((a, b) => {
      let cmp = 0
      if (sortField === 'pnl_pct') {
        cmp = calcPnlPct(a) - calcPnlPct(b)
      } else if (sortField === 'symbol') {
        cmp = a.symbol.localeCompare(b.symbol)
      } else {
        const av = (a as unknown as Record<string, unknown>)[sortField] ?? 0
        const bv = (b as unknown as Record<string, unknown>)[sortField] ?? 0
        cmp = (av as number) < (bv as number) ? -1 : (av as number) > (bv as number) ? 1 : 0
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return rows
  }, [openPositions, filterText, sortField, sortDir])

  // Grouped positions
  const groupedPositions = useMemo(() => {
    if (groupBy === 'none') return null
    const groups: Record<string, { positions: PositionData[]; totalPnl: number; totalValue: number }> = {}
    for (const p of filteredOpen) {
      const key = groupBy === 'agent' ? p.agent_id.slice(0, 8) : p.symbol
      if (!groups[key]) groups[key] = { positions: [], totalPnl: 0, totalValue: 0 }
      groups[key].positions.push(p)
      groups[key].totalPnl += p.unrealized_pnl
      groups[key].totalValue += p.current_price * p.qty
    }
    return groups
  }, [filteredOpen, groupBy])

  // Exposure metrics
  const exposure = useMemo(() => {
    let longExp = 0
    let shortExp = 0
    for (const p of openPositions) {
      const value = p.current_price * p.qty
      if (p.side === 'long') longExp += value
      else shortExp += value
    }
    return { long: longExp, short: shortExp, net: longExp - shortExp }
  }, [openPositions])

  // Allocation chart data
  const allocationData = useMemo(() => {
    const bySymbol: Record<string, number> = {}
    for (const p of openPositions) {
      const val = p.current_price * p.qty
      bySymbol[p.symbol] = (bySymbol[p.symbol] ?? 0) + val
    }
    return Object.entries(bySymbol)
      .map(([name, value]) => ({ name, value: Math.round(value * 100) / 100 }))
      .sort((a, b) => b.value - a.value)
  }, [openPositions])

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

  const renderPositionRow = (pos: PositionData, showClose = false) => {
    const pnlPct = calcPnlPct(pos)
    return (
      <TableRow
        key={pos.id}
        className="cursor-pointer hover:bg-muted/50"
        onClick={() => setSelectedPosition(pos)}
      >
        <TableCell><span className="font-mono font-semibold">{pos.symbol}</span></TableCell>
        <TableCell>
          <Badge variant={pos.side === 'long' ? 'default' : 'destructive'} className="uppercase">
            {pos.side}
          </Badge>
        </TableCell>
        <TableCell>{pos.qty}</TableCell>
        <TableCell>${pos.entry_price.toFixed(2)}</TableCell>
        <TableCell>${pos.current_price.toFixed(2)}</TableCell>
        <TableCell>
          <span className={pnlColor(pos.unrealized_pnl)}>
            ${pos.unrealized_pnl.toFixed(2)}
          </span>
        </TableCell>
        <TableCell>
          <span className={cn('font-mono tabular-nums', pnlColor(pnlPct))}>
            {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
          </span>
        </TableCell>
        <TableCell>{pos.stop_loss ? `$${pos.stop_loss.toFixed(2)}` : '\u2014'}</TableCell>
        <TableCell className="text-xs whitespace-nowrap">
          {new Date(pos.opened_at).toLocaleDateString()}
        </TableCell>
        {showClose && (
          <TableCell>
            <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => {
                  setEditingSLTP(pos)
                  setSlValue(pos.stop_loss?.toString() ?? '')
                  setTpValue(pos.take_profit?.toString() ?? '')
                }}
              >
                <Pencil className="h-3 w-3" />
              </Button>
              <Button
                variant="destructive"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => setClosingPosition(pos)}
              >
                <X className="h-3 w-3 mr-1" /> Close
              </Button>
            </div>
          </TableCell>
        )}
      </TableRow>
    )
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={TrendingUp} title="Positions" description="Account-level position management" />

      {/* Summary + Exposure cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 sm:gap-3">
        {summary && (
          <>
            <MetricCard title="Open Positions" value={summary.open_positions} />
            <MetricCard
              title="Unrealized P&L"
              value={`$${summary.total_unrealized_pnl.toFixed(2)}`}
              trend={summary.total_unrealized_pnl >= 0 ? 'up' : 'down'}
            />
            <MetricCard
              title="Realized P&L"
              value={`$${summary.total_realized_pnl.toFixed(2)}`}
              trend={summary.total_realized_pnl >= 0 ? 'up' : 'down'}
            />
          </>
        )}
        <MetricCard
          title="Long Exposure"
          value={`$${exposure.long.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          trend="up"
        />
        <MetricCard
          title="Short Exposure"
          value={`$${exposure.short.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          trend="down"
        />
        <MetricCard
          title="Net Exposure"
          value={`$${exposure.net.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          trend={exposure.net >= 0 ? 'up' : 'down'}
        />
      </div>

      {/* Portfolio Allocation Donut */}
      {allocationData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <h3 className="text-sm font-semibold">Portfolio Allocation by Symbol</h3>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={allocationData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  dataKey="value"
                  nameKey="name"
                  paddingAngle={2}
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {allocationData.map((_, idx) => (
                    <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <ReTooltip
                  contentStyle={{
                    backgroundColor: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px',
                    fontSize: 12,
                  }}
                  formatter={(value: number) => [`$${value.toLocaleString()}`, 'Value']}
                />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="open">
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 mb-2">
          <TabsList>
            <TabsTrigger value="open">
              Open ({openPositions.length})
            </TabsTrigger>
            <TabsTrigger value="closed">
              Closed ({closedPositions.length})
            </TabsTrigger>
          </TabsList>
          <div className="flex gap-2 flex-wrap">
            <Input
              placeholder="Filter symbol/agent..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              className="w-44 text-sm"
            />
            <Select value={groupBy} onValueChange={(v) => setGroupBy(v as GroupBy)}>
              <SelectTrigger className="w-32 text-sm">
                <SelectValue placeholder="Group by" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No grouping</SelectItem>
                <SelectItem value="agent">By Agent</SelectItem>
                <SelectItem value="symbol">By Symbol</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <TabsContent value="open" className="mt-2">
          {groupedPositions ? (
            // Grouped view
            <div className="space-y-4">
              {Object.entries(groupedPositions).map(([groupName, group]) => (
                <div key={groupName} className="rounded-xl border border-border overflow-x-auto">
                  <div className="px-4 py-2 bg-muted/30 flex items-center justify-between border-b">
                    <span className="font-semibold text-sm">{groupName}</span>
                    <span className={cn('text-sm font-mono', pnlColor(group.totalPnl))}>
                      P&L: ${group.totalPnl.toFixed(2)} | Value: ${group.totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </span>
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <SortHeader field="symbol" label="Symbol" />
                        <TableHead>Side</TableHead>
                        <TableHead>Qty</TableHead>
                        <SortHeader field="entry_price" label="Entry" />
                        <SortHeader field="current_price" label="Current" />
                        <SortHeader field="unrealized_pnl" label="P&L $" />
                        <SortHeader field="pnl_pct" label="Return %" />
                        <TableHead>Stop Loss</TableHead>
                        <SortHeader field="opened_at" label="Opened" />
                        <TableHead>Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {group.positions.map((pos) => renderPositionRow(pos, true))}
                    </TableBody>
                  </Table>
                </div>
              ))}
            </div>
          ) : (
            // Flat view
            <div className="rounded-xl border border-border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <SortHeader field="symbol" label="Symbol" />
                    <TableHead>Side</TableHead>
                    <TableHead>Qty</TableHead>
                    <SortHeader field="entry_price" label="Entry" />
                    <SortHeader field="current_price" label="Current" />
                    <SortHeader field="unrealized_pnl" label="P&L $" />
                    <SortHeader field="pnl_pct" label="Return %" />
                    <TableHead>Stop Loss</TableHead>
                    <SortHeader field="opened_at" label="Opened" />
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {openLoading ? (
                    Array.from({ length: 3 }).map((_, i) => (
                      <TableRow key={i}>
                        {Array.from({ length: 10 }).map((__, j) => (
                          <TableCell key={j}><Skeleton className="h-6 w-full" /></TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : filteredOpen.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                        No open positions
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredOpen.map((pos) => renderPositionRow(pos, true))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="closed" className="mt-2">
          <div className="rounded-xl border border-border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead>Qty</TableHead>
                  <TableHead>Entry</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead>P&L $</TableHead>
                  <TableHead>Return %</TableHead>
                  <TableHead>Exit Reason</TableHead>
                  <TableHead>Closed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {closedLoading ? (
                  Array.from({ length: 3 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 9 }).map((__, j) => (
                        <TableCell key={j}><Skeleton className="h-6 w-full" /></TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : closedPositions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                      No closed positions yet
                    </TableCell>
                  </TableRow>
                ) : (
                  closedPositions.map((pos) => {
                    const pnlPct = calcPnlPct(pos)
                    return (
                      <TableRow
                        key={pos.id}
                        className="cursor-pointer hover:bg-muted/50"
                        onClick={() => setSelectedPosition(pos)}
                      >
                        <TableCell><span className="font-mono font-semibold">{pos.symbol}</span></TableCell>
                        <TableCell><span className="uppercase">{pos.side}</span></TableCell>
                        <TableCell>{pos.qty}</TableCell>
                        <TableCell>${pos.entry_price.toFixed(2)}</TableCell>
                        <TableCell>{pos.exit_price ? `$${pos.exit_price.toFixed(2)}` : '\u2014'}</TableCell>
                        <TableCell>
                          <span className={pnlColor(pos.realized_pnl)}>${pos.realized_pnl.toFixed(2)}</span>
                        </TableCell>
                        <TableCell>
                          <span className={cn('font-mono tabular-nums', pnlColor(pnlPct))}>
                            {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                          </span>
                        </TableCell>
                        <TableCell>{pos.exit_reason ?? '\u2014'}</TableCell>
                        <TableCell className="text-xs">
                          {pos.closed_at ? new Date(pos.closed_at).toLocaleString() : '\u2014'}
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>

      {/* Position Detail Side Panel */}
      <SidePanel
        open={!!selectedPosition}
        onOpenChange={() => setSelectedPosition(null)}
        title={selectedPosition ? `Position: ${selectedPosition.symbol}` : ''}
      >
        {selectedPosition && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <span className="text-muted-foreground">Symbol</span>
              <span className="font-mono font-semibold">{selectedPosition.symbol}</span>
              <span className="text-muted-foreground">Side</span>
              <Badge variant={selectedPosition.side === 'long' ? 'default' : 'destructive'} className="uppercase w-fit">
                {selectedPosition.side}
              </Badge>
              <span className="text-muted-foreground">Quantity</span>
              <span>{selectedPosition.qty}</span>
              <span className="text-muted-foreground">Entry Price</span>
              <span className="font-mono">${selectedPosition.entry_price.toFixed(2)}</span>
              <span className="text-muted-foreground">Current Price</span>
              <span className="font-mono">${selectedPosition.current_price.toFixed(2)}</span>
              <span className="text-muted-foreground">Stop Loss</span>
              <span className="font-mono">{selectedPosition.stop_loss ? `$${selectedPosition.stop_loss.toFixed(2)}` : '\u2014'}</span>
              <span className="text-muted-foreground">Take Profit</span>
              <span className="font-mono">{selectedPosition.take_profit ? `$${selectedPosition.take_profit.toFixed(2)}` : '\u2014'}</span>
              <span className="text-muted-foreground">Unrealized P&L</span>
              <span className={cn('font-mono', pnlColor(selectedPosition.unrealized_pnl))}>
                ${selectedPosition.unrealized_pnl.toFixed(2)}
              </span>
              <span className="text-muted-foreground">Return %</span>
              <span className={cn('font-mono', pnlColor(calcPnlPct(selectedPosition)))}>
                {calcPnlPct(selectedPosition).toFixed(2)}%
              </span>
              <span className="text-muted-foreground">Realized P&L</span>
              <span className={cn('font-mono', pnlColor(selectedPosition.realized_pnl))}>
                ${selectedPosition.realized_pnl.toFixed(2)}
              </span>
              <span className="text-muted-foreground">Agent</span>
              <span className="font-mono text-xs">{selectedPosition.agent_id.slice(0, 12)}...</span>
              <span className="text-muted-foreground">Status</span>
              <Badge variant={selectedPosition.status === 'OPEN' ? 'default' : 'secondary'}>
                {selectedPosition.status}
              </Badge>
              <span className="text-muted-foreground">Duration</span>
              <span>{timeSince(selectedPosition.opened_at)}</span>
              <span className="text-muted-foreground">Opened</span>
              <span className="text-xs">{new Date(selectedPosition.opened_at).toLocaleString()}</span>
              {selectedPosition.closed_at && (
                <>
                  <span className="text-muted-foreground">Closed</span>
                  <span className="text-xs">{new Date(selectedPosition.closed_at).toLocaleString()}</span>
                </>
              )}
              {selectedPosition.exit_reason && (
                <>
                  <span className="text-muted-foreground">Exit Reason</span>
                  <span>{selectedPosition.exit_reason}</span>
                </>
              )}
            </div>
          </div>
        )}
      </SidePanel>

      {/* Close Position Confirm Dialog */}
      <ConfirmDialog
        open={!!closingPosition}
        onOpenChange={() => setClosingPosition(null)}
        title="Close Position"
        description={closingPosition
          ? `Close ${closingPosition.symbol} ${closingPosition.side} position (${closingPosition.qty} shares) at current price $${closingPosition.current_price.toFixed(2)}?`
          : ''
        }
        confirmLabel="Close Position"
        variant="destructive"
        onConfirm={async () => {
          if (closingPosition) await closeMutation.mutateAsync(closingPosition)
        }}
      />

      {/* Edit SL/TP Dialog */}
      <Dialog open={!!editingSLTP} onOpenChange={() => setEditingSLTP(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Stop Loss / Take Profit</DialogTitle>
            <DialogDescription>
              {editingSLTP && `${editingSLTP.symbol} ${editingSLTP.side} - Entry: $${editingSLTP.entry_price.toFixed(2)}`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium">Stop Loss</label>
              <Input
                type="number"
                step="0.01"
                value={slValue}
                onChange={(e) => setSlValue(e.target.value)}
                placeholder="e.g. 145.00"
              />
            </div>
            <div>
              <label className="text-sm font-medium">Take Profit</label>
              <Input
                type="number"
                step="0.01"
                value={tpValue}
                onChange={(e) => setTpValue(e.target.value)}
                placeholder="e.g. 165.00"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingSLTP(null)}>Cancel</Button>
            <Button
              disabled={updateSLTP.isPending}
              onClick={() => {
                if (!editingSLTP) return
                updateSLTP.mutate({
                  id: editingSLTP.id,
                  stop_loss: slValue ? parseFloat(slValue) : null,
                  take_profit: tpValue ? parseFloat(tpValue) : null,
                })
              }}
            >
              {updateSLTP.isPending ? 'Saving...' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
