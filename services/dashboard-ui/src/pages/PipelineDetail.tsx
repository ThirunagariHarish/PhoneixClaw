import { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer,
  CartesianGrid, ReferenceDot,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import {
  ArrowLeft, TrendingUp, TrendingDown, Activity, BarChart3,
  Clock, CheckCircle2, XCircle, AlertTriangle, Loader2,
  RefreshCw, Database, Hash, Wallet, Target, Zap,
  MessageSquare, Download, ChevronUp, ChevronDown, Settings,
} from 'lucide-react'
import { exportToCSV } from '@/lib/csv-export'

interface Pipeline {
  id: string
  name: string
  data_source_id: string
  data_source_name: string | null
  source_type: string | null
  channel_id: string
  channel_name: string | null
  channel_identifier: string | null
  trading_account_id: string
  trading_account_name: string | null
  enabled: boolean
  status: string
  error_message: string | null
  auto_approve: boolean
  paper_mode: boolean
  last_message_at: string | null
  messages_count: number
  trades_count: number
  created_at: string
  updated_at: string
}

interface Account {
  id: string
  display_name: string
  broker_type: string
  paper_mode: boolean
}

interface PipelineTrade {
  id: number
  trade_id: string
  ticker: string
  strike: number
  option_type: string
  action: string
  price: number
  quantity: string
  status: string
  source: string
  error_message: string | null
  rejection_reason: string | null
  broker_order_id: string | null
  raw_message: string | null
  buffered_price: number | null
  fill_price: number | null
  realized_pnl: number | null
  execution_latency_ms: number | null
  created_at: string | null
  processed_at: string | null
}

interface PipelineStats {
  total: number
  executed: number
  rejected: number
  errored: number
  pending: number
  total_pnl: number
  winning: number
  losing: number
  win_rate: number
  avg_execution_latency_ms: number | null
  messages_count: number
}

interface PerformancePoint {
  date: string
  trades: number
  pnl: number
  cumulative_pnl: number
  executed: number
}

interface RawMsg {
  id: string
  content: string
  author: string | null
  channel_name: string | null
  created_at: string | null
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  CONNECTED: { label: 'Connected', color: 'bg-emerald-500' },
  CONNECTING: { label: 'Connecting', color: 'bg-amber-500 animate-pulse' },
  RUNNING: { label: 'Running', color: 'bg-emerald-500' },
  STOPPED: { label: 'Stopped', color: 'bg-zinc-400' },
  ERROR: { label: 'Error', color: 'bg-red-500' },
  DISCONNECTED: { label: 'Disconnected', color: 'bg-zinc-400' },
}

type TimeRange = '7d' | '30d' | '90d'

function formatCurrency(val: number): string {
  const sign = val >= 0 ? '+' : ''
  return `${sign}$${Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function statusBadge(status: string, errorMessage?: string | null, rejectionReason?: string | null) {
  const reason = rejectionReason || errorMessage
  const badge = (() => {
    switch (status) {
      case 'EXECUTED':
        return <Badge variant="default" className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/20">Executed</Badge>
      case 'ERROR':
        return <Badge variant="destructive">Error</Badge>
      case 'REJECTED':
        return <Badge className="bg-amber-500/15 text-amber-600 border-amber-500/30">Rejected</Badge>
      case 'IN_PROGRESS':
        return <Badge className="bg-blue-500/15 text-blue-600 border-blue-500/30">In Progress</Badge>
      case 'PENDING':
        return <Badge variant="outline">Pending</Badge>
      default:
        return <Badge variant="secondary">{status}</Badge>
    }
  })()

  if (reason && (status === 'ERROR' || status === 'REJECTED')) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help">{badge}</span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="text-xs font-medium">{status === 'REJECTED' ? 'Rejection Reason' : 'Error Details'}</p>
          <p className="text-xs text-muted-foreground mt-0.5">{reason}</p>
        </TooltipContent>
      </Tooltip>
    )
  }

  return badge
}

export default function PipelineDetail() {
  const { pipelineId } = useParams<{ pipelineId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [timeRange, setTimeRange] = useState<TimeRange>('30d')
  const [editName, setEditName] = useState('')
  const [editAccount, setEditAccount] = useState('')
  const [editAutoApprove, setEditAutoApprove] = useState(true)
  const [editPaperMode, setEditPaperMode] = useState(false)
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  const days = timeRange === '7d' ? 7 : timeRange === '30d' ? 30 : 90

  const { data: pipeline, isLoading: pipelineLoading } = useQuery<Pipeline>({
    queryKey: ['pipeline', pipelineId],
    queryFn: () => axios.get(`/api/v1/pipelines/${pipelineId}`).then(r => r.data),
    refetchInterval: 10_000,
  })

  const { data: accounts } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => axios.get('/api/v1/accounts').then(r => r.data),
  })

  if (pipeline && !settingsLoaded) {
    setEditName(pipeline.name)
    setEditAccount(pipeline.trading_account_id)
    setEditAutoApprove(pipeline.auto_approve)
    setEditPaperMode(pipeline.paper_mode)
    setSettingsLoaded(true)
  }

  const updateMutation = useMutation({
    mutationFn: (data: { name?: string; trading_account_id?: string; auto_approve?: boolean; paper_mode?: boolean }) =>
      axios.put(`/api/v1/pipelines/${pipelineId}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline', pipelineId] })
      setSaveMsg('Settings saved')
      setTimeout(() => setSaveMsg(null), 2500)
    },
    onError: () => setSaveMsg('Failed to save'),
  })

  const handleSaveSettings = () => {
    if (!pipeline) return
    const payload: Record<string, unknown> = {}
    if (editName !== pipeline.name) payload.name = editName
    if (editAccount !== pipeline.trading_account_id) payload.trading_account_id = editAccount
    if (editAutoApprove !== pipeline.auto_approve) payload.auto_approve = editAutoApprove
    if (editPaperMode !== pipeline.paper_mode) payload.paper_mode = editPaperMode
    if (Object.keys(payload).length === 0) {
      setSaveMsg('No changes')
      setTimeout(() => setSaveMsg(null), 2000)
      return
    }
    updateMutation.mutate(payload as Parameters<typeof updateMutation.mutate>[0])
  }

  const { data: stats } = useQuery<PipelineStats>({
    queryKey: ['pipeline-stats', pipelineId],
    queryFn: () => axios.get(`/api/v1/pipelines/${pipelineId}/stats`).then(r => r.data),
    refetchInterval: 15_000,
  })

  const { data: performance } = useQuery<PerformancePoint[]>({
    queryKey: ['pipeline-performance', pipelineId, days],
    queryFn: () => axios.get(`/api/v1/pipelines/${pipelineId}/performance?days=${days}`).then(r => r.data),
    refetchInterval: 30_000,
  })

  const { data: trades, refetch: refetchTrades } = useQuery<PipelineTrade[]>({
    queryKey: ['pipeline-trades', pipelineId],
    queryFn: () => axios.get(`/api/v1/pipelines/${pipelineId}/trades?limit=50`).then(r => r.data),
    refetchInterval: 10_000,
  })

  const visibleTrades = useMemo(
    () => (trades ?? []).filter((t) => t.ticker !== '_CONTEXT'),
    [trades],
  )

  const { data: messages } = useQuery<RawMsg[]>({
    queryKey: ['pipeline-messages', pipelineId],
    queryFn: () => axios.get(`/api/v1/pipelines/${pipelineId}/messages?limit=20`).then(r => r.data),
  })

  const totalPnl = stats?.total_pnl ?? 0
  const pnlPositive = totalPnl >= 0

  const chartColor = useMemo(() => {
    if (!performance || performance.length === 0) return 'hsl(var(--primary))'
    const last = performance[performance.length - 1]
    return (last?.cumulative_pnl ?? 0) >= 0 ? '#10b981' : '#ef4444'
  }, [performance])

  const tradeMarkers = useMemo(() => {
    if (!trades || !performance || performance.length === 0) return []
    const pnlByDate = new Map(performance.map(p => [p.date, p.cumulative_pnl]))
    return trades
      .filter(t => t.status === 'EXECUTED' && (t.processed_at || t.created_at))
      .map(t => {
        const ts = t.processed_at || t.created_at!
        const date = ts.slice(0, 10)
        const cumulativePnl = pnlByDate.get(date)
        if (cumulativePnl === undefined) return null
        const isBuy = t.action === 'BUY' || t.action === 'BTO'
        return { date, cumulative_pnl: cumulativePnl, isBuy, ticker: t.ticker, action: t.action, price: t.price }
      })
      .filter(Boolean) as { date: string; cumulative_pnl: number; isBuy: boolean; ticker: string; action: string; price: number }[]
  }, [trades, performance])

  const statusInfo = STATUS_MAP[pipeline?.status ?? 'STOPPED'] ?? STATUS_MAP.STOPPED

  if (pipelineLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!pipeline) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <XCircle className="h-10 w-10 text-destructive" />
        <p className="text-lg font-medium">Pipeline not found</p>
        <Button variant="outline" onClick={() => navigate('/pipelines')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Pipelines
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <Button variant="ghost" size="icon" className="mt-0.5 shrink-0" onClick={() => navigate('/pipelines')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-2xl font-bold tracking-tight truncate">{pipeline.name}</h2>
              <div className="flex items-center gap-2">
                <div className={`h-2.5 w-2.5 rounded-full ${statusInfo.color}`} />
                <span className="text-sm text-muted-foreground">{statusInfo.label}</span>
              </div>
              {pipeline.auto_approve && <Badge variant="outline" className="text-xs">Auto</Badge>}
              {pipeline.paper_mode && <Badge variant="outline" className="text-xs">Paper</Badge>}
            </div>
            <div className="flex items-center gap-4 mt-1.5 text-sm text-muted-foreground flex-wrap">
              <span className="flex items-center gap-1.5">
                <Database className="h-3.5 w-3.5" />
                {pipeline.data_source_name || 'Unknown'}
              </span>
              <span className="flex items-center gap-1.5">
                <Hash className="h-3.5 w-3.5" />
                {pipeline.channel_name || pipeline.channel_identifier || 'Unknown'}
              </span>
              <span className="flex items-center gap-1.5">
                <Wallet className="h-3.5 w-3.5" />
                {pipeline.trading_account_name || 'Unknown'}
              </span>
            </div>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetchTrades()} className="shrink-0">
          <RefreshCw className="mr-1.5 h-4 w-4" /> Refresh
        </Button>
      </div>

      {pipeline.error_message && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{pipeline.error_message}</span>
        </div>
      )}

      {/* Portfolio Value Chart - Robinhood Style */}
      <Card className="overflow-hidden">
        <CardContent className="p-6">
          <div className="flex items-end justify-between mb-1">
            <div>
              <p className="text-sm text-muted-foreground mb-1">Total P&L</p>
              <p className={`text-4xl font-bold tracking-tight ${pnlPositive ? 'text-emerald-500' : 'text-red-500'}`}>
                {formatCurrency(totalPnl)}
              </p>
              {stats && stats.total > 0 && (
                <div className="flex items-center gap-1.5 mt-1">
                  {pnlPositive
                    ? <ChevronUp className="h-4 w-4 text-emerald-500" />
                    : <ChevronDown className="h-4 w-4 text-red-500" />
                  }
                  <span className={`text-sm font-medium ${pnlPositive ? 'text-emerald-500' : 'text-red-500'}`}>
                    {stats.win_rate}% win rate
                  </span>
                  <span className="text-sm text-muted-foreground">
                    &middot; {stats.winning}W / {stats.losing}L
                  </span>
                </div>
              )}
            </div>
            <div className="flex gap-1">
              {(['7d', '30d', '90d'] as TimeRange[]).map(r => (
                <Button
                  key={r}
                  variant={timeRange === r ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-3 text-xs"
                  onClick={() => setTimeRange(r)}
                >
                  {r.toUpperCase()}
                </Button>
              ))}
            </div>
          </div>

          <div className="h-64 mt-4 -mx-2">
            {performance && performance.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={performance} margin={{ top: 5, right: 5, left: 5, bottom: 0 }}>
                  <defs>
                    <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={chartColor} stopOpacity={0.25} />
                      <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" opacity={0.3} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={formatDate}
                    tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tickFormatter={(v: number) => `$${v}`}
                    tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={60}
                  />
                  <RechartsTooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null
                      const d = payload[0].payload as PerformancePoint
                      return (
                        <div className="rounded-lg border bg-card p-3 shadow-lg text-sm">
                          <p className="font-medium">{new Date(d.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</p>
                          <div className="mt-1.5 space-y-0.5">
                            <p className={d.cumulative_pnl >= 0 ? 'text-emerald-500' : 'text-red-500'}>
                              Cumulative: {formatCurrency(d.cumulative_pnl)}
                            </p>
                            <p className="text-muted-foreground">
                              Day: {formatCurrency(d.pnl)} &middot; {d.trades} trade{d.trades !== 1 ? 's' : ''}
                            </p>
                          </div>
                        </div>
                      )
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="cumulative_pnl"
                    stroke={chartColor}
                    strokeWidth={2.5}
                    fill="url(#pnlGradient)"
                    dot={false}
                    activeDot={{ r: 5, fill: chartColor, stroke: 'hsl(var(--card))', strokeWidth: 2 }}
                  />
                  {tradeMarkers.map((m, i) => (
                    <ReferenceDot
                      key={`marker-${i}`}
                      x={m.date}
                      y={m.cumulative_pnl}
                      r={6}
                      fill={m.isBuy ? '#10b981' : '#ef4444'}
                      stroke="hsl(var(--card))"
                      strokeWidth={2}
                      shape={(props: any) => {
                        const { cx, cy } = props
                        const size = 7
                        const points = m.isBuy
                          ? `${cx},${cy - size} ${cx - size},${cy + size} ${cx + size},${cy + size}`
                          : `${cx - size},${cy - size} ${cx + size},${cy - size} ${cx},${cy + size}`
                        return <polygon points={points} fill={m.isBuy ? '#10b981' : '#ef4444'} stroke="hsl(var(--card))" strokeWidth={2} />
                      }}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                <BarChart3 className="h-10 w-10 mb-2 opacity-40" />
                <p className="text-sm">No performance data yet</p>
                <p className="text-xs mt-0.5">Chart will populate as trades are executed</p>
              </div>
            )}
          </div>
          {tradeMarkers.length > 0 && (
            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground justify-end">
              <div className="flex items-center gap-1.5">
                <svg width="12" height="12" viewBox="0 0 12 12"><polygon points="6,1 1,11 11,11" fill="#10b981" /></svg>
                <span>Bought</span>
              </div>
              <div className="flex items-center gap-1.5">
                <svg width="12" height="12" viewBox="0 0 12 12"><polygon points="1,1 11,1 6,11" fill="#ef4444" /></svg>
                <span>Sold</span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Total Trades</p>
                <p className="text-2xl font-bold mt-0.5">{stats?.total ?? 0}</p>
              </div>
              <Activity className="h-5 w-5 text-primary opacity-60" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Executed</p>
                <p className="text-2xl font-bold mt-0.5 text-emerald-500">{stats?.executed ?? 0}</p>
              </div>
              <CheckCircle2 className="h-5 w-5 text-emerald-500 opacity-60" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Win Rate</p>
                <p className="text-2xl font-bold mt-0.5">{stats?.win_rate ?? 0}%</p>
              </div>
              <Target className="h-5 w-5 text-primary opacity-60" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Messages</p>
                <p className="text-2xl font-bold mt-0.5">{stats?.messages_count ?? pipeline.messages_count}</p>
              </div>
              <MessageSquare className="h-5 w-5 text-blue-500 opacity-60" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Avg Latency</p>
                <p className="text-2xl font-bold mt-0.5">
                  {stats?.avg_execution_latency_ms ? `${stats.avg_execution_latency_ms}ms` : '—'}
                </p>
              </div>
              <Zap className="h-5 w-5 text-amber-500 opacity-60" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Errors</p>
                <p className="text-2xl font-bold mt-0.5 text-red-500">{stats?.errored ?? 0}</p>
              </div>
              <XCircle className="h-5 w-5 text-red-500 opacity-60" />
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="trades" className="space-y-4">
        <TabsList>
          <TabsTrigger value="trades" className="gap-1.5">
            <TrendingUp className="h-3.5 w-3.5" /> Trades
          </TabsTrigger>
          <TabsTrigger value="messages" className="gap-1.5">
            <MessageSquare className="h-3.5 w-3.5" /> Messages
          </TabsTrigger>
          <TabsTrigger value="settings" className="gap-1.5">
            <Settings className="h-3.5 w-3.5" /> Settings
          </TabsTrigger>
        </TabsList>

        <TabsContent value="trades">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between py-4">
              <CardTitle className="text-base">Trade History</CardTitle>
              {visibleTrades.length > 0 && (
                <Button
                  variant="outline" size="sm" className="h-7 gap-1 text-xs"
                  onClick={() => {
                    const headers = ['Ticker', 'Action', 'Type', 'Strike', 'Price', 'Fill', 'P&L', 'Status', 'Latency', 'Time']
                    const rows = visibleTrades.map(t => [
                      t.ticker, t.action, t.option_type, String(t.strike),
                      t.price.toFixed(2), t.fill_price?.toFixed(2) ?? '',
                      t.realized_pnl?.toFixed(2) ?? '', t.status,
                      t.execution_latency_ms ? `${t.execution_latency_ms}ms` : '',
                      t.created_at ? new Date(t.created_at).toLocaleString() : '',
                    ])
                    exportToCSV(`pipeline-trades-${pipelineId}`, headers, rows)
                  }}
                >
                  <Download className="h-3 w-3" /> Export
                </Button>
              )}
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ticker</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="text-right">Strike</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Fill</TableHead>
                    <TableHead className="text-right">P&L</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Latency</TableHead>
                    <TableHead>Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleTrades.length > 0 ? visibleTrades.map(t => (
                    <TableRow key={t.trade_id}>
                      <TableCell className="font-semibold">{t.ticker}</TableCell>
                      <TableCell>
                        <span className={t.action === 'BUY' || t.action === 'BTO' ? 'text-emerald-500 font-medium' : 'text-red-500 font-medium'}>
                          {t.action}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{t.option_type}</TableCell>
                      <TableCell className="text-right">${t.strike.toFixed(2)}</TableCell>
                      <TableCell className="text-right">${t.price.toFixed(2)}</TableCell>
                      <TableCell className="text-right">
                        {t.fill_price ? `$${t.fill_price.toFixed(2)}` : '—'}
                      </TableCell>
                      <TableCell className="text-right">
                        {t.realized_pnl != null ? (
                          <span className={t.realized_pnl >= 0 ? 'text-emerald-500 font-medium' : 'text-red-500 font-medium'}>
                            {formatCurrency(t.realized_pnl)}
                          </span>
                        ) : '—'}
                      </TableCell>
                      <TableCell>{statusBadge(t.status, t.error_message, t.rejection_reason)}</TableCell>
                      <TableCell className="text-right text-muted-foreground text-xs">
                        {t.execution_latency_ms ? `${t.execution_latency_ms}ms` : '—'}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                        {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
                      </TableCell>
                    </TableRow>
                  )) : (
                    <TableRow>
                      <TableCell colSpan={10} className="text-center text-muted-foreground py-12">
                        <div className="flex flex-col items-center gap-2">
                          <TrendingUp className="h-8 w-8 opacity-30" />
                          <p>No trades yet for this pipeline</p>
                          <p className="text-xs">Trades will appear here as signals are processed</p>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="messages">
          <Card>
            <CardHeader className="py-4">
              <CardTitle className="text-base">Recent Messages</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {messages && messages.length > 0 ? (
                <div className="divide-y">
                  {messages.map(m => (
                    <div key={m.id} className="px-4 py-3 hover:bg-accent/30 transition-colors">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-primary">{m.author || 'Unknown'}</span>
                        <span className="text-xs text-muted-foreground">
                          {m.created_at ? new Date(m.created_at).toLocaleString() : ''}
                        </span>
                      </div>
                      <p className="text-sm text-foreground break-words whitespace-pre-wrap">{m.content}</p>
                      {m.channel_name && (
                        <span className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                          <Hash className="h-3 w-3" /> {m.channel_name}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
                  <MessageSquare className="h-8 w-8 opacity-30" />
                  <p className="text-sm">No messages received yet</p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="settings">
          <Card>
            <CardHeader className="py-4">
              <CardTitle className="text-base">Pipeline Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6 max-w-lg">
              <div className="space-y-2">
                <Label htmlFor="pipeline-name">Pipeline Name</Label>
                <Input
                  id="pipeline-name"
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  placeholder="Pipeline name"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="trading-account">Trading Account</Label>
                <Select value={editAccount} onValueChange={setEditAccount}>
                  <SelectTrigger id="trading-account">
                    <SelectValue placeholder="Select account" />
                  </SelectTrigger>
                  <SelectContent>
                    {(accounts ?? []).map(a => (
                      <SelectItem key={a.id} value={a.id}>
                        {a.display_name} ({a.broker_type}{a.paper_mode ? ' - Paper' : ''})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="auto-approve">Auto-Approve</Label>
                  <p className="text-xs text-muted-foreground mt-0.5">Automatically execute parsed trade signals</p>
                </div>
                <Switch
                  id="auto-approve"
                  checked={editAutoApprove}
                  onCheckedChange={setEditAutoApprove}
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="paper-mode">Paper Mode</Label>
                  <p className="text-xs text-muted-foreground mt-0.5">Simulate trades without real orders</p>
                </div>
                <Switch
                  id="paper-mode"
                  checked={editPaperMode}
                  onCheckedChange={setEditPaperMode}
                />
              </div>

              <div className="flex items-center gap-3 pt-2">
                <Button onClick={handleSaveSettings} disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : null}
                  Save Changes
                </Button>
                {saveMsg && (
                  <span className={`text-sm ${saveMsg === 'Settings saved' ? 'text-emerald-500' : 'text-muted-foreground'}`}>
                    {saveMsg}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Pipeline Info Footer */}
      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <p className="text-xs text-muted-foreground mb-0.5">Created</p>
              <p className="font-medium">{new Date(pipeline.created_at).toLocaleDateString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-0.5">Last Updated</p>
              <p className="font-medium">{new Date(pipeline.updated_at).toLocaleDateString()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-0.5">Last Message</p>
              <p className="font-medium">
                {pipeline.last_message_at
                  ? new Date(pipeline.last_message_at).toLocaleString()
                  : 'Never'
                }
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-0.5">Pipeline ID</p>
              <p className="font-mono text-xs text-muted-foreground truncate">{pipeline.id}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
