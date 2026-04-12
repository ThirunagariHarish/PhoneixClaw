/**
 * Home Overview — single-glance portfolio summary dashboard.
 * Top metrics, equity curve, activity feed, agent grid, recent trades, quick actions.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  Home as HomeIcon, TrendingUp, TrendingDown, DollarSign, Briefcase, Bot,
  ArrowRight, Plus, Eye, FlaskConical, Zap, Clock, ArrowUpRight, ArrowDownRight,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

/* eslint-disable @typescript-eslint/no-explicit-any */
const RAreaChart = AreaChart as any
const RArea = Area as any
const RXAxis = XAxis as any
const RYAxis = YAxis as any
const RGrid = CartesianGrid as any
const RTooltip = Tooltip as any
const RContainer = ResponsiveContainer as any

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Agent {
  id: string
  name: string
  status: string
  today_pnl?: number
  last_trade_at?: string | null
}

interface Trade {
  id: string
  symbol: string
  side: string
  fill_price: number | null
  qty: number
  status: string
  pnl?: number
  created_at: string
}

interface EquityPoint {
  timestamp: string | null
  equity: number
  pnl: number
}

// ---------------------------------------------------------------------------
// Animated counter hook
// ---------------------------------------------------------------------------

function useAnimatedNumber(target: number, duration = 600): number {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    const start = display
    const diff = target - start
    if (Math.abs(diff) < 0.01) { setDisplay(target); return }
    const startTime = performance.now()
    let raf: number
    const step = (now: number) => {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      // ease-out quad
      const eased = 1 - (1 - progress) * (1 - progress)
      setDisplay(start + diff * eased)
      if (progress < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
    // Only animate when target changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])
  return display
}

// ---------------------------------------------------------------------------
// Mini equity curve (area chart)
// ---------------------------------------------------------------------------

function MiniEquityCurve() {
  const { data, isLoading, isError } = useQuery<{ curve: EquityPoint[]; starting_capital: number }>({
    queryKey: ['home-equity-curve'],
    queryFn: async () => (await api.get('/api/v2/portfolio/equity-curve?days=30')).data,
    refetchInterval: 30_000,
    retry: 1,
    throwOnError: false,
  })

  const curve = Array.isArray(data?.curve) ? data!.curve : []
  const startCap = typeof data?.starting_capital === 'number' ? data.starting_capital : 100_000
  const chartData = curve.map((p) => ({
    date: p?.timestamp ? new Date(p.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '',
    equity: typeof p?.equity === 'number' ? p.equity : 0,
  }))

  const latest = curve.length ? curve[curve.length - 1] : null
  const returnPct = latest ? ((latest.equity - startCap) / startCap) * 100 : 0
  const isPositive = returnPct >= 0

  if (isError) {
    return (
      <Card className="h-full">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Equity Curve (30d)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[220px] flex items-center justify-center text-sm text-muted-foreground">
            Equity curve unavailable
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Equity Curve (30d)</CardTitle>
          {latest && (
            <div className="text-right">
              <div className="text-lg font-semibold">${latest.equity.toLocaleString()}</div>
              <div className={cn('text-xs', isPositive ? 'text-emerald-500' : 'text-rose-500')}>
                {isPositive ? '+' : ''}{returnPct.toFixed(2)}%
              </div>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="h-[220px] flex items-center justify-center text-sm text-muted-foreground animate-pulse">
            Loading...
          </div>
        ) : chartData.length === 0 ? (
          <div className="h-[220px] flex items-center justify-center text-sm text-muted-foreground">
            No data yet
          </div>
        ) : (
          <RContainer width="100%" height={220}>
            <RAreaChart data={chartData}>
              <defs>
                <linearGradient id="homeEquityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={isPositive ? '#10b981' : '#ef4444'} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={isPositive ? '#10b981' : '#ef4444'} stopOpacity={0} />
                </linearGradient>
              </defs>
              <RGrid strokeDasharray="3 3" stroke="#2d3748" opacity={0.25} />
              <RXAxis dataKey="date" fontSize={10} tick={{ fill: '#94a3b8' }} tickLine={false} axisLine={false} />
              <RYAxis
                fontSize={10}
                tick={{ fill: '#94a3b8' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              />
              <RTooltip
                contentStyle={{
                  background: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
                formatter={(value: number) => [`$${value.toLocaleString()}`, 'Equity']}
              />
              <RArea
                type="monotone"
                dataKey="equity"
                stroke={isPositive ? '#10b981' : '#ef4444'}
                strokeWidth={2}
                fill="url(#homeEquityGradient)"
              />
            </RAreaChart>
          </RContainer>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Activity feed
// ---------------------------------------------------------------------------

function ActivityFeed({ agents, trades }: { agents: Agent[]; trades: Trade[] }) {
  // Build a merged activity list from trades and agent status changes
  const activities: { id: string; text: string; time: string; type: 'trade' | 'agent' | 'info' }[] = []

  trades.slice(0, 5).forEach((t) => {
    activities.push({
      id: `trade-${t.id}`,
      text: `${t.side.toUpperCase()} ${t.qty} ${t.symbol} @ $${t.fill_price?.toFixed(2) ?? 'pending'}`,
      time: t.created_at,
      type: 'trade',
    })
  })

  agents.slice(0, 5).forEach((a) => {
    activities.push({
      id: `agent-${a.id}`,
      text: `Agent "${a.name}" is ${a.status}`,
      time: a.last_trade_at ?? '',
      type: 'agent',
    })
  })

  // Sort by time descending, take latest 10
  const sorted = activities
    .filter((a) => a.time)
    .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
    .slice(0, 10)

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Today's Activity</CardTitle>
      </CardHeader>
      <CardContent>
        {sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">No recent activity</p>
        ) : (
          <div className="space-y-3 max-h-[260px] overflow-y-auto pr-1">
            {sorted.map((item) => (
              <div key={item.id} className="flex items-start gap-2 text-sm">
                <span className={cn(
                  'mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full',
                  item.type === 'trade' ? 'bg-primary' : 'bg-emerald-500',
                )} />
                <div className="min-w-0 flex-1">
                  <p className="text-foreground truncate">{item.text}</p>
                  <p className="text-xs text-muted-foreground">
                    {item.time ? formatRelativeTime(item.time) : ''}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Agent status grid
// ---------------------------------------------------------------------------

function AgentStatusGrid({ agents }: { agents: Agent[] }) {
  const navigate = useNavigate()
  const running = agents.filter((a) => ['running', 'active'].includes(a.status?.toLowerCase()))

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Agent Status</CardTitle>
          <Button variant="ghost" size="sm" className="text-xs h-7" onClick={() => navigate('/agents')}>
            View all <ArrowRight className="h-3 w-3 ml-1" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {running.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">No running agents</p>
        ) : (
          <div className="space-y-2 max-h-[240px] overflow-y-auto pr-1">
            {running.slice(0, 6).map((agent) => (
              <div
                key={agent.id}
                className="flex items-center justify-between rounded-lg border p-2.5 hover:bg-accent/50 cursor-pointer transition-colors"
                onClick={() => navigate(`/agents/${agent.id}`)}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{agent.name}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <StatusBadge status={agent.status} className="text-[10px] px-1.5 py-0" />
                    {agent.last_trade_at && (
                      <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                        <Clock className="h-2.5 w-2.5" />
                        {formatRelativeTime(agent.last_trade_at)}
                      </span>
                    )}
                  </div>
                </div>
                {agent.today_pnl !== undefined && agent.today_pnl !== null && (
                  <span className={cn(
                    'text-sm font-semibold tabular-nums',
                    agent.today_pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400',
                  )}>
                    {agent.today_pnl >= 0 ? '+' : ''}${agent.today_pnl.toFixed(2)}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Recent trades table
// ---------------------------------------------------------------------------

function RecentTradesTable({ trades }: { trades: Trade[] }) {
  const navigate = useNavigate()

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Recent Trades</CardTitle>
          <Button variant="ghost" size="sm" className="text-xs h-7" onClick={() => navigate('/trades')}>
            View all <ArrowRight className="h-3 w-3 ml-1" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {trades.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">No recent trades</p>
        ) : (
          <div className="space-y-1.5">
            {trades.slice(0, 5).map((t) => (
              <div key={t.id} className="flex items-center justify-between rounded-lg border p-2.5">
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className={cn(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
                    t.side === 'buy'
                      ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                      : 'bg-red-500/10 text-red-600 dark:text-red-400',
                  )}>
                    {t.side === 'buy' ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-mono font-semibold">{t.symbol}</p>
                    <p className="text-[10px] text-muted-foreground uppercase">{t.side} {t.qty}</p>
                  </div>
                </div>
                <div className="text-right">
                  {t.pnl !== undefined && t.pnl !== null ? (
                    <p className={cn(
                      'text-sm font-semibold tabular-nums',
                      t.pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400',
                    )}>
                      {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t.status}</p>
                  )}
                  <p className="text-[10px] text-muted-foreground">{formatRelativeTime(t.created_at)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Quick actions
// ---------------------------------------------------------------------------

function QuickActions() {
  const navigate = useNavigate()

  const actions = [
    { label: 'Create Agent', icon: Plus, to: '/agents', variant: 'default' as const },
    { label: 'View Positions', icon: Eye, to: '/positions', variant: 'outline' as const },
    { label: 'Run Backtest', icon: FlaskConical, to: '/backtests', variant: 'outline' as const },
    { label: 'Morning Briefing', icon: Zap, to: '/morning-briefing', variant: 'outline' as const },
  ]

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Quick Actions</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-2">
          {actions.map((action) => (
            <Button
              key={action.label}
              variant={action.variant}
              className="justify-start gap-2 h-10"
              onClick={() => navigate(action.to)}
            >
              <action.icon className="h-4 w-4" />
              {action.label}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60_000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHrs = Math.floor(diffMins / 60)
  if (diffHrs < 24) return `${diffHrs}h ago`
  const diffDays = Math.floor(diffHrs / 24)
  if (diffDays === 1) return 'yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

function formatCurrency(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(2)}`
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function HomePage() {
  const REFETCH_INTERVAL = 30_000

  // Portfolio summary — TODO: replace with /api/v2/positions/summary when available
  const { data: perfSummary } = useQuery({
    queryKey: ['home-perf-summary'],
    queryFn: async () => {
      try {
        return (await api.get('/api/v2/performance/summary?range=1M')).data
      } catch {
        return null
      }
    },
    refetchInterval: REFETCH_INTERVAL,
  })

  // Trade stats
  const { data: tradeStats } = useQuery<{ total: number; filled: number; rejected: number; pending: number }>({
    queryKey: ['home-trade-stats'],
    queryFn: async () => {
      try {
        return (await api.get('/api/v2/trades/stats')).data
      } catch {
        return { total: 0, filled: 0, rejected: 0, pending: 0 }
      }
    },
    refetchInterval: REFETCH_INTERVAL,
  })

  // Agents list
  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ['home-agents'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/agents')
        return Array.isArray(res.data) ? res.data : (res.data?.agents ?? [])
      } catch {
        return []
      }
    },
    refetchInterval: REFETCH_INTERVAL,
  })

  // Recent trades
  const { data: recentTrades = [] } = useQuery<Trade[]>({
    queryKey: ['home-recent-trades'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/trades?limit=5')
        return Array.isArray(res.data) ? res.data : (res.data?.trades ?? [])
      } catch {
        return []
      }
    },
    refetchInterval: REFETCH_INTERVAL,
  })

  // Derived metrics
  const totalPnl = perfSummary?.total_pnl ?? 0
  const todayPnl = perfSummary?.today_pnl ?? 0
  const todayPnlPct = perfSummary?.today_pnl_pct ?? 0

  const openPositions = perfSummary?.open_positions ?? tradeStats?.pending ?? 0

  const agentList = Array.isArray(agents) ? agents : []
  const activeAgents = agentList.filter((a) => ['running', 'active'].includes(a.status?.toLowerCase()))
  const pausedAgents = agentList.filter((a) => a.status?.toLowerCase() === 'paused')
  const errorAgents = agentList.filter((a) => ['error', 'failed'].includes(a.status?.toLowerCase()))

  // Animated values
  const animatedTotalPnl = useAnimatedNumber(totalPnl)
  const animatedTodayPnl = useAnimatedNumber(todayPnl)

  return (
    <div className="space-y-4 sm:space-y-6 animate-in fade-in duration-500">
      {/* Header */}
      <PageHeader icon={HomeIcon} title="Overview" description="Portfolio summary at a glance" />

      {/* Top row: key metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <MetricCard
          title="Total P&L"
          value={formatCurrency(animatedTotalPnl)}
          trend={totalPnl >= 0 ? 'up' : 'down'}
          icon={totalPnl >= 0 ? TrendingUp : TrendingDown}
          subtitle="All time"
          tooltip="Cumulative realized profit and loss across all agents"
        />
        <MetricCard
          title="Today's P&L"
          value={formatCurrency(animatedTodayPnl)}
          trend={todayPnl >= 0 ? 'up' : todayPnl < 0 ? 'down' : 'neutral'}
          icon={DollarSign}
          subtitle={todayPnlPct ? `${todayPnlPct >= 0 ? '+' : ''}${todayPnlPct.toFixed(2)}%` : undefined}
          tooltip="Realized P&L for today's trading session"
        />
        <MetricCard
          title="Open Positions"
          value={openPositions}
          trend="neutral"
          icon={Briefcase}
          tooltip="Number of currently open positions across all agents"
        />
        <MetricCard
          title="Active Agents"
          value={activeAgents.length}
          trend="neutral"
          icon={Bot}
          subtitle={[
            activeAgents.length > 0 ? `${activeAgents.length} running` : null,
            pausedAgents.length > 0 ? `${pausedAgents.length} paused` : null,
            errorAgents.length > 0 ? `${errorAgents.length} error` : null,
          ].filter(Boolean).join(' / ') || 'No agents'}
          tooltip="Agents currently running, paused, or in error state"
        />
      </div>

      {/* Second row: equity curve + activity feed */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3 sm:gap-4">
        <div className="lg:col-span-3">
          <MiniEquityCurve />
        </div>
        <div className="lg:col-span-2">
          <ActivityFeed agents={agentList} trades={recentTrades} />
        </div>
      </div>

      {/* Third row: agent grid, recent trades, quick actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
        <AgentStatusGrid agents={agentList} />
        <RecentTradesTable trades={recentTrades} />
        <QuickActions />
      </div>
    </div>
  )
}
