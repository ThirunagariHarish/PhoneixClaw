import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { TrendingUp, CheckCircle2, XCircle, AlertTriangle, Loader2, Download, Search, Clock, Eye } from 'lucide-react'
import { exportToCSV } from '@/lib/csv-export'

interface Trade {
  trade_id: string
  ticker: string
  action: string
  strike: number
  price: number
  status: string
  created_at: string
  error_message?: string | null
  rejection_reason?: string | null
  raw_message?: string | null
  source?: string | null
  source_author?: string | null
  option_type?: string
  expiration?: string
  account_name?: string | null
  pipeline_name?: string | null
}

const STATUS_DESCRIPTIONS: Record<string, string> = {
  EXECUTED: 'Order placed at broker, awaiting fill',
  IN_PROGRESS: 'Trade is being processed by the executor',
  PENDING: 'Awaiting approval before execution',
  STALE: 'Order polled for 5+ minutes without final status from broker — may still be pending',
  FILLED: 'Order fully filled at broker',
  PARTIAL_FILL: 'Order partially filled at broker',
  CANCELLED: 'Order was cancelled at broker',
  EXPIRED: 'Order expired before it could be filled',
  ERROR: 'An error occurred while processing the trade',
  REJECTED: 'Trade was rejected by the system or broker',
}

const statusBadge = (status: string, errorMessage?: string | null, rejectionReason?: string | null) => {
  const reason = rejectionReason || errorMessage
  const badge = (() => {
    switch (status) {
      case 'EXECUTED':
        return <Badge variant="success">Executed</Badge>
      case 'FILLED':
        return <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30">Filled</Badge>
      case 'PARTIAL_FILL':
        return <Badge className="bg-amber-500/15 text-amber-600 border-amber-500/30">Partial Fill</Badge>
      case 'ERROR':
        return <Badge variant="destructive">Error</Badge>
      case 'REJECTED':
        return <Badge variant="warning">Rejected</Badge>
      case 'IN_PROGRESS':
        return <Badge className="bg-blue-500/15 text-blue-600 border-blue-500/30">In Progress</Badge>
      case 'PENDING':
        return <Badge variant="outline">Pending</Badge>
      case 'STALE':
        return <Badge className="bg-gray-500/15 text-gray-500 border-gray-400/30">Stale</Badge>
      case 'CANCELLED':
        return <Badge className="bg-gray-500/15 text-gray-500 border-gray-400/30">Cancelled</Badge>
      case 'EXPIRED':
        return <Badge className="bg-orange-500/15 text-orange-600 border-orange-500/30">Expired</Badge>
      default:
        return <Badge variant="secondary">{status}</Badge>
    }
  })()

  const description = STATUS_DESCRIPTIONS[status]
  const detail = reason ? `${description || status}\n${reason}` : description

  if (detail) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help">{badge}</span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="text-xs font-medium">{status}</p>
          <p className="text-xs text-muted-foreground mt-0.5 whitespace-pre-line">{detail}</p>
        </TooltipContent>
      </Tooltip>
    )
  }

  return badge
}

const kpiCards = [
  { key: 'total', label: 'Total Trades', icon: TrendingUp, color: 'text-primary', tooltip: null },
  {
    key: 'executed',
    label: 'Executed',
    icon: CheckCircle2,
    color: 'text-emerald-500',
    tooltip: 'Order placed in Alpaca',
  },
  {
    key: 'inProgress',
    label: 'In Progress',
    icon: Clock,
    color: 'text-blue-500',
    tooltip: 'In queue or executing; awaiting order placement',
  },
  { key: 'rejected', label: 'Rejected', icon: AlertTriangle, color: 'text-amber-500', tooltip: null },
  { key: 'errored', label: 'Errors', icon: XCircle, color: 'text-red-500', tooltip: null },
] as const

export default function Dashboard() {
  const [searchQuery, setSearchQuery] = useState('')
  const [viewTrade, setViewTrade] = useState<Trade | null>(null)
  const { data: trades, isLoading: tradesLoading, isError: tradesError, refetch: refetchTrades } = useQuery<Trade[]>({
    queryKey: ['trades'],
    queryFn: () => axios.get('/api/v1/trades?limit=50').then((r) => r.data),
    refetchInterval: 5000,
  })
  const { data: metrics, isError: metricsError } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => axios.get('/api/v1/metrics/daily?days=7').then((r) => r.data),
  })

  const filteredTrades = useMemo(() => {
    if (!trades) return []
    const visible = trades.filter((t) => t.ticker !== '_CONTEXT')
    if (!searchQuery.trim()) return visible
    const q = searchQuery.toLowerCase()
    return visible.filter((t) => {
      const searchable = [
        t.ticker, t.action, t.status, t.option_type,
        t.strike?.toString(), t.price?.toFixed(2),
        t.error_message, t.rejection_reason, t.raw_message,
        t.source, t.account_name, t.pipeline_name,
        t.created_at ? new Date(t.created_at).toLocaleString() : '',
      ].filter(Boolean).join(' ').toLowerCase()
      return searchable.includes(q)
    })
  }, [trades, searchQuery])

  const stats = {
    total: trades?.length || 0,
    executed: trades?.filter((t) => t.status === 'EXECUTED').length || 0,
    inProgress: trades?.filter((t) => t.status === 'IN_PROGRESS').length || 0,
    rejected: trades?.filter((t) => t.status === 'REJECTED').length || 0,
    errored: trades?.filter((t) => t.status === 'ERROR').length || 0,
  }

  if (tradesError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <XCircle className="h-10 w-10 text-destructive mb-3" />
        <p className="text-lg font-medium">Failed to load dashboard data</p>
        <p className="text-sm text-muted-foreground mt-1">Please check your connection and try again.</p>
        <Button variant="outline" className="mt-4" onClick={() => refetchTrades()}>Retry</Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {kpiCards.map(({ key, label, icon: Icon, color, tooltip }) => {
          const card = (
            <Card>
              <CardContent className="p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{label}</p>
                    <p className="text-3xl font-bold mt-1">{stats[key]}</p>
                  </div>
                  <div className={`${color} opacity-80`}>
                    <Icon className="h-8 w-8" />
                  </div>
                </div>
              </CardContent>
            </Card>
          )
          return tooltip ? (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <div className="cursor-help min-w-0">{card}</div>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-sm">{tooltip}</p>
              </TooltipContent>
            </Tooltip>
          ) : (
            <div key={key}>{card}</div>
          )
        })}
      </div>

      {tradesLoading && (
        <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      )}

      {metrics && metrics.length > 0 && !metricsError && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Daily P&L (7 days)</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={metrics}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" className="text-xs" tick={{ fill: 'hsl(var(--muted-foreground))' }} />
                <YAxis className="text-xs" tick={{ fill: 'hsl(var(--muted-foreground))' }} />
                <RechartsTooltip
                  contentStyle={{
                    backgroundColor: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px',
                    color: 'hsl(var(--card-foreground))',
                  }}
                />
                <Bar dataKey="total_pnl" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <CardTitle className="text-base shrink-0">Recent Trades</CardTitle>
          <div className="flex items-center gap-2 flex-1 justify-end">
            <div className="relative max-w-xs w-full">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search trades..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-8 pl-8 text-sm"
              />
            </div>
            {trades && trades.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1 text-xs shrink-0"
                onClick={() => {
                  const headers = ['Ticker', 'Action', 'Strike', 'Type', 'Price', 'Source', 'Account', 'Pipeline', 'Status', 'Error', 'Time']
                  const rows = (filteredTrades).map(t => [
                    t.ticker,
                    t.action,
                    String(t.strike),
                    t.option_type === 'PUT' ? 'Put' : t.option_type === 'CALL' ? 'Call' : '',
                    t.price?.toFixed(2) ?? '',
                    t.source || '',
                    t.account_name || '',
                    t.pipeline_name || '',
                    t.status,
                    t.rejection_reason || t.error_message || '',
                    t.created_at ? new Date(t.created_at).toLocaleString() : '',
                  ])
                  exportToCSV('recent-trades', headers, rows)
                }}
              >
                <Download className="h-3 w-3" /> Export CSV
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Strike</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Pipeline</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Time</TableHead>
                <TableHead className="w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredTrades.map((t) => (
                <TableRow key={t.trade_id}>
                  <TableCell className="font-medium">{t.ticker}</TableCell>
                  <TableCell>
                    <span className={t.action === 'BUY' ? 'text-emerald-500' : 'text-red-500'}>
                      {t.action}
                    </span>
                  </TableCell>
                  <TableCell>{t.strike}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {t.option_type === 'PUT' ? 'Put' : t.option_type === 'CALL' ? 'Call' : '—'}
                  </TableCell>
                  <TableCell>${t.price?.toFixed(2)}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-xs capitalize">
                      {t.source || '—'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs max-w-[120px] truncate" title={t.account_name || undefined}>
                    {t.account_name || '—'}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs max-w-[120px] truncate" title={t.pipeline_name || undefined}>
                    {t.pipeline_name || '—'}
                  </TableCell>
                  <TableCell>{statusBadge(t.status, t.error_message, t.rejection_reason)}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => setViewTrade(t)}
                      title="View raw message"
                    >
                      <Eye className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {filteredTrades.length === 0 && (
                <TableRow>
                  <TableCell colSpan={11} className="text-center text-muted-foreground py-8">
                    {searchQuery ? 'No trades match your search.' : 'No trades yet. Connect a data source to get started.'}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={!!viewTrade} onOpenChange={v => { if (!v) setViewTrade(null) }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Raw Message</DialogTitle>
          </DialogHeader>
          {viewTrade && (
            <div className="space-y-4">
              <div className="rounded-lg border bg-muted/30 p-3 space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">Ticker:</span>
                  <span className="font-medium">{viewTrade.ticker}</span>
                  <span className={viewTrade.action === 'BUY' || viewTrade.action === 'BTO' ? 'text-emerald-500 font-medium' : 'text-red-500 font-medium'}>
                    {viewTrade.action}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">Source:</span>
                  <span className="font-medium capitalize">{viewTrade.source || 'Unknown'}</span>
                  {viewTrade.source_author && (
                    <>
                      <span className="text-muted-foreground">by</span>
                      <span className="font-medium">{viewTrade.source_author}</span>
                    </>
                  )}
                </div>
                {viewTrade.account_name && (
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Account:</span>
                    <span className="font-medium">{viewTrade.account_name}</span>
                  </div>
                )}
                {viewTrade.pipeline_name && (
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Pipeline:</span>
                    <span className="font-medium">{viewTrade.pipeline_name}</span>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">Time:</span>
                  <span>{viewTrade.created_at ? new Date(viewTrade.created_at).toLocaleString() : '—'}</span>
                </div>
              </div>
              <div className="space-y-1.5">
                <p className="text-sm font-medium text-muted-foreground">Original Message</p>
                <div className="rounded-lg border bg-muted/20 p-4 text-sm font-mono whitespace-pre-wrap break-words min-h-[60px]">
                  {viewTrade.raw_message || <span className="text-muted-foreground italic">No raw message available</span>}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
