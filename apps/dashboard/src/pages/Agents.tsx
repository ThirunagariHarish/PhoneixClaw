/**
 * Agents page — manage Claude Code trading agents.
 * Cards for agent overview, 4-step creation wizard, detail panel.
 * M1.11.
 */
import React, { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, Link } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SidePanel } from '@/components/ui/SidePanel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { AiAssistPopover } from '@/components/AiAssistPopover'
import { EquityCurveChart } from '@/components/EquityCurveChart'
import { toast } from 'sonner'
import {
  Bot, Plus, Pause, Play, Trash2, CheckCircle2, Rocket, ChevronLeft, ChevronRight,
  Plug, MessageSquare, Globe, Radio, Activity, Newspaper, Webhook, TrendingUp, Landmark, BarChart3,
  CheckSquare, Square as SquareIcon, Hash, Loader2, Eye, ArrowUpRight, ArrowDownRight, Minus,
  FlaskConical, Zap, Shield,
} from 'lucide-react'

interface AgentData {
  id: string
  name: string
  type: string
  status: string
  worker_status?: string
  config: Record<string, unknown>
  created_at: string
  channel_name?: string
  analyst_name?: string
  model_type?: string
  model_accuracy?: number
  daily_pnl?: number
  total_pnl?: number
  total_trades?: number
  win_rate?: number
  last_signal_at?: string
  last_trade_at?: string
}

interface AgentStats {
  total: number
  running: number
  paused: number
  backtesting: number
  daily_pnl?: number
}

interface BacktestData {
  id: string
  agent_id: string
  status: string
  strategy_template: string | null
  start_date: string | null
  end_date: string | null
  parameters: Record<string, unknown>
  metrics: Record<string, unknown>
  equity_curve: Array<{ day: number; date: string; equity: number }>
  total_trades: number
  win_rate: number | null
  sharpe_ratio: number | null
  max_drawdown: number | null
  total_return: number | null
  error_message: string | null
  completed_at: string | null
  created_at: string | null
}

const STATUS_CONFIG: Record<string, { color: string; bgColor: string; borderColor: string; label: string; pulse?: boolean }> = {
  BACKTESTING:       { color: 'text-amber-600 dark:text-amber-400',   bgColor: 'bg-amber-500/10',   borderColor: 'border-amber-500/30',   label: 'Backtesting',       pulse: true },
  BACKTEST_COMPLETE: { color: 'text-blue-600 dark:text-blue-400',     bgColor: 'bg-blue-500/10',     borderColor: 'border-blue-500/30',    label: 'Review Ready' },
  PAPER:             { color: 'text-purple-600 dark:text-purple-400', bgColor: 'bg-purple-500/10',   borderColor: 'border-purple-500/30',  label: 'Paper Trading' },
  APPROVED:          { color: 'text-emerald-600 dark:text-emerald-400', bgColor: 'bg-emerald-500/10', borderColor: 'border-emerald-500/30', label: 'Approved' },
  RUNNING:           { color: 'text-green-600 dark:text-green-400',   bgColor: 'bg-green-500/10',    borderColor: 'border-green-500/30',   label: 'Live Trading' },
  PAUSED:            { color: 'text-zinc-500 dark:text-zinc-400',     bgColor: 'bg-zinc-500/10',     borderColor: 'border-zinc-500/30',    label: 'Paused' },
  CREATED:           { color: 'text-muted-foreground',                bgColor: 'bg-muted/50',        borderColor: 'border-border',         label: 'Created' },
}

function getStatusConfig(status: string) {
  return STATUS_CONFIG[status] ?? STATUS_CONFIG.CREATED
}

const AGENT_TYPES = [
  { value: 'trading', label: 'Trading Agent' },
  { value: 'trend', label: 'Trend Agent' },
]

const WIZARD_STEPS = ['Channel', 'Risk Config', 'Review'] as const

interface ConnectorInfo {
  id: string
  name: string
  type: string
  status: string
  config: Record<string, unknown>
  tags: string[]
  is_active: boolean
  last_connected_at: string | null
  error_message: string | null
  created_at: string
}

interface PlatformMeta {
  icon: typeof Plug
  color: string
  bgColor: string
  label: string
  category: 'data' | 'broker'
}

const PLATFORM_META: Record<string, PlatformMeta> = {
  discord:         { icon: MessageSquare, color: 'text-indigo-500',  bgColor: 'bg-indigo-500/10',  label: 'Discord',       category: 'data' },
  reddit:          { icon: Globe,         color: 'text-orange-500',  bgColor: 'bg-orange-500/10',  label: 'Reddit',        category: 'data' },
  twitter:         { icon: Radio,         color: 'text-sky-500',     bgColor: 'bg-sky-500/10',     label: 'Twitter / X',   category: 'data' },
  unusual_whales:  { icon: Activity,      color: 'text-purple-500',  bgColor: 'bg-purple-500/10',  label: 'Unusual Whales', category: 'data' },
  news_api:        { icon: Newspaper,     color: 'text-emerald-500', bgColor: 'bg-emerald-500/10', label: 'News API',      category: 'data' },
  custom_webhook:  { icon: Webhook,       color: 'text-zinc-400',    bgColor: 'bg-zinc-500/10',    label: 'Webhook',       category: 'data' },
  alpaca:          { icon: TrendingUp,    color: 'text-yellow-500',  bgColor: 'bg-yellow-500/10',  label: 'Alpaca',        category: 'broker' },
  ibkr:            { icon: Landmark,      color: 'text-red-500',     bgColor: 'bg-red-500/10',     label: 'IBKR',          category: 'broker' },
  tradier:         { icon: BarChart3,     color: 'text-teal-500',    bgColor: 'bg-teal-500/10',    label: 'Tradier',       category: 'broker' },
}

function getPlatformMeta(type: string): PlatformMeta {
  return PLATFORM_META[type] ?? { icon: Plug, color: 'text-muted-foreground', bgColor: 'bg-muted', label: type, category: 'data' }
}

function connectorSummary(c: ConnectorInfo): string {
  const cfg = c.config || {}
  switch (c.type) {
    case 'discord': {
      const chCount = Array.isArray(cfg.selected_channels) ? (cfg.selected_channels as unknown[]).length : 0
      return cfg.server_name ? `${cfg.server_name} · ${chCount} ch` : `${chCount} channels`
    }
    case 'reddit': {
      const subs = Array.isArray(cfg.subreddits) ? (cfg.subreddits as string[]) : []
      return subs.length ? subs.map((s) => `r/${s}`).slice(0, 3).join(', ') : 'Reddit'
    }
    case 'twitter': {
      const accts = Array.isArray(cfg.accounts) ? (cfg.accounts as string[]) : []
      return accts.length ? accts.map((a) => `@${a}`).slice(0, 3).join(', ') : 'Twitter'
    }
    case 'alpaca': return `${(cfg.mode as string) === 'live' ? 'Live' : 'Paper'} trading`
    case 'ibkr': return `${cfg.host || '127.0.0.1'}:${cfg.port || 7497}`
    case 'tradier': return cfg.sandbox ? 'Sandbox' : 'Production'
    default: return c.type
  }
}

interface SelectedChannel {
  channel_id: string
  channel_name: string
}

interface WizardFormData {
  name: string
  type: string
  description: string
  connector_ids: string[]
  selected_channel: SelectedChannel | null
  skills: string[]
  max_daily_loss_pct: number
  max_position_pct: number
  stop_loss_pct: number
  smart_hold_enabled: boolean
  smart_hold_buffer_pct: number
  source_config: Record<string, unknown>
}

/* P1: Spawn typed agent quick form (UW / social / strategy / supervisor) */
function QuickSpawnTypedAgent() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [type, setType] = useState('unusual_whales')

  const spawn = useMutation({
    mutationFn: async () => {
      return (await api.post('/api/v2/agents/spawn-typed', { name, type, config: {} })).data
    },
    onSuccess: (d) => {
      toast.success(`Spawned ${type}: ${d.agent_id}`)
      setName('')
      qc.invalidateQueries({ queryKey: ['agents'] })
    },
    onError: (e: unknown) => toast.error(`Spawn failed: ${String(e)}`),
  })

  return (
    <div className="flex items-center gap-2 p-3 rounded-lg border bg-muted/30">
      <Shield className="w-4 h-4 text-muted-foreground" />
      <span className="text-xs text-muted-foreground whitespace-nowrap">Quick spawn:</span>
      <Input
        placeholder="Agent name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="max-w-xs h-8 text-xs"
      />
      <Select value={type} onValueChange={setType}>
        <SelectTrigger className="w-44 h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="unusual_whales">Unusual Whales</SelectItem>
          <SelectItem value="social_sentiment">Social Sentiment</SelectItem>
          <SelectItem value="strategy">Strategy Agent</SelectItem>
          <SelectItem value="supervisor">AutoResearch Supervisor</SelectItem>
        </SelectContent>
      </Select>
      <Button
        size="sm"
        onClick={() => spawn.mutate()}
        disabled={!name || spawn.isPending}
      >
        <Plus className="w-3 h-3 mr-1" />
        Spawn
      </Button>
    </div>
  )
}

const DEFAULT_FORM: WizardFormData = {
  name: '',
  type: 'trading',
  description: '',
  connector_ids: [],
  selected_channel: null,
  skills: [],
  max_daily_loss_pct: 5,
  max_position_pct: 10,
  stop_loss_pct: 2,
  smart_hold_enabled: false,
  smart_hold_buffer_pct: 10,
  source_config: {},
}

function MiniEquityCurve({ data }: { data: Array<{ equity: number }> }) {
  if (!data || data.length < 2) return null
  const vals = data.map((d) => d.equity)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const range = max - min || 1
  const w = 120
  const h = 32
  const points = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${h - ((v - min) / range) * h}`).join(' ')
  const isPositive = vals[vals.length - 1] >= vals[0]
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-8" preserveAspectRatio="none">
      <polyline
        points={points}
        fill="none"
        stroke={isPositive ? '#22c55e' : '#ef4444'}
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

function BacktestingSpinner() {
  return (
    <div className="flex items-center gap-2 py-2">
      <div className="relative">
        <Loader2 className="h-5 w-5 text-amber-500 animate-spin" />
        <div className="absolute inset-0 h-5 w-5 rounded-full border-2 border-amber-500/20" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-400 animate-pulse" style={{ width: '60%' }} />
        </div>
        <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1 font-medium">Running backtest...</p>
      </div>
    </div>
  )
}

function MetricPill({ label, value, trend }: { label: string; value: string; trend?: 'up' | 'down' | 'neutral' }) {
  const Icon = trend === 'up' ? ArrowUpRight : trend === 'down' ? ArrowDownRight : Minus
  const trendColor = trend === 'up' ? 'text-green-600 dark:text-green-400' : trend === 'down' ? 'text-red-500' : 'text-muted-foreground'
  return (
    <div className="flex items-center gap-1 rounded-md bg-muted/60 px-2 py-1">
      <span className="text-[10px] text-muted-foreground uppercase">{label}</span>
      <span className={`text-xs font-semibold font-mono ${trendColor}`}>{value}</span>
      {trend && <Icon className={`h-3 w-3 ${trendColor}`} />}
    </div>
  )
}

function AgentCard({ agent, onSelect, onPause, onResume, onDelete, onReview, onPromote }: {
  agent: AgentData
  onSelect: () => void
  onPause: () => void
  onResume: () => void
  onDelete: () => void
  onReview: () => void
  onPromote: () => void
}) {
  const config = agent.config as Record<string, unknown>
  const sc = getStatusConfig(agent.status)

  const { data: backtest } = useQuery<BacktestData>({
    queryKey: ['agent-backtest', agent.id],
    queryFn: async () => (await api.get(`/api/v2/agents/${agent.id}/backtest`)).data,
    enabled: agent.status === 'BACKTEST_COMPLETE',
    staleTime: 60_000,
  })

  // Trigger artifacts endpoint to backfill DB when backtest metrics are empty
  const backtestMissing = backtest && backtest.win_rate == null && backtest.total_return == null
  const { data: artifacts } = useQuery<Record<string, unknown>>({
    queryKey: ['agent-backtest-artifacts-backfill', agent.id],
    queryFn: async () => {
      try { return (await api.get(`/api/v2/agents/${agent.id}/backtest-artifacts`)).data } catch { return null }
    },
    enabled: agent.status === 'BACKTEST_COMPLETE' && !!backtestMissing,
    staleTime: 120_000,
  })

  const queryClient = useQueryClient()
  // If artifacts returned data, invalidate the backtest query to pick up persisted values
  React.useEffect(() => {
    if (artifacts && (artifacts.total_trades as number) > 0) {
      queryClient.invalidateQueries({ queryKey: ['agent-backtest', agent.id] })
    }
  }, [artifacts, agent.id, queryClient])

  const isLocked = agent.status === 'BACKTESTING'

  return (
    <div
      className={`group relative rounded-xl border bg-card overflow-hidden transition-all duration-200 ${isLocked ? 'opacity-80 cursor-not-allowed' : 'hover:shadow-lg hover:shadow-black/5 dark:hover:shadow-black/20 hover:-translate-y-0.5 cursor-pointer'} ${sc.borderColor}`}
      onClick={isLocked ? undefined : onSelect}
    >
      {/* Status strip */}
      <div className={`h-1 w-full ${sc.bgColor}`}>
        {sc.pulse && <div className="h-full w-full bg-amber-500/60 animate-pulse" />}
      </div>

      <div className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${sc.bgColor}`}>
              {agent.status === 'BACKTESTING' ? (
                <FlaskConical className={`h-4 w-4 ${sc.color}`} />
              ) : agent.status === 'RUNNING' ? (
                <Zap className={`h-4 w-4 ${sc.color}`} />
              ) : (
                <Bot className={`h-4 w-4 ${sc.color}`} />
              )}
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-sm truncate">{agent.name}</p>
              <p className="text-[11px] text-muted-foreground capitalize">{agent.type} agent</p>
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
            {agent.status === 'RUNNING' && (
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); onPause() }}>
                <Pause className="h-3.5 w-3.5" />
              </Button>
            )}
            {agent.status === 'PAUSED' && (
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); onResume() }}>
                <Play className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); onDelete() }}>
              <Trash2 className="h-3.5 w-3.5 text-destructive" />
            </Button>
          </div>
        </div>

        {/* Status badge */}
        <div className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${sc.bgColor} ${sc.color}`}>
          {agent.status === 'RUNNING' && <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />}
          {sc.label}
        </div>

        {/* BACKTESTING: spinner */}
        {agent.status === 'BACKTESTING' && <BacktestingSpinner />}

        {/* BACKTEST_COMPLETE: rich metrics preview */}
        {agent.status === 'BACKTEST_COMPLETE' && backtest && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-1.5">
              <MetricPill label="Return" value={backtest.total_return != null ? `${backtest.total_return.toFixed(1)}%` : '—'} trend={backtest.total_return != null ? (backtest.total_return >= 0 ? 'up' : 'down') : 'neutral'} />
              <MetricPill label="Win Rate" value={backtest.win_rate != null ? `${(backtest.win_rate * 100).toFixed(0)}%` : '—'} trend={backtest.win_rate != null ? (backtest.win_rate >= 0.5 ? 'up' : 'down') : 'neutral'} />
              <MetricPill label="Sharpe" value={backtest.sharpe_ratio != null ? backtest.sharpe_ratio.toFixed(2) : '—'} trend={backtest.sharpe_ratio != null ? (backtest.sharpe_ratio >= 1.0 ? 'up' : 'neutral') : 'neutral'} />
              <MetricPill label="Trades" value={`${backtest.total_trades ?? 0}`} trend="neutral" />
            </div>
            {Array.isArray(backtest.metrics?.rules) && backtest.metrics.rules.length > 0 && (
              <div className="text-[10px] text-muted-foreground flex items-center gap-1.5">
                <Shield className="h-3 w-3" />
                {String(backtest.metrics.rules.length)} rules learned
                {backtest.metrics?.overall_channel_metrics != null
                  && typeof (backtest.metrics.overall_channel_metrics as Record<string, unknown>).best_ticker === 'string'
                  ? ` · Top: ${(backtest.metrics.overall_channel_metrics as Record<string, string>).best_ticker}`
                  : null
                }
              </div>
            )}
            {backtest.equity_curve?.length > 0 && <MiniEquityCurve data={backtest.equity_curve} />}
            <Button
              size="sm"
              className="w-full gap-1.5"
              variant="default"
              onClick={(e) => { e.stopPropagation(); onReview() }}
            >
              <Eye className="h-3.5 w-3.5" /> Review & Approve
            </Button>
          </div>
        )}

        {/* PAPER / APPROVED: promote button */}
        {(agent.status === 'PAPER' || agent.status === 'APPROVED') && (
          <Button
            size="sm"
            className="w-full gap-1.5"
            variant="outline"
            onClick={(e) => { e.stopPropagation(); onPromote() }}
          >
            <Rocket className="h-3.5 w-3.5" /> Promote to Live
          </Button>
        )}

        {/* RUNNING: live metrics */}
        {agent.status === 'RUNNING' && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 rounded-md bg-green-500/5 border border-green-500/20 px-2.5 py-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
              </span>
              <span className="text-[11px] font-medium text-green-700 dark:text-green-400">Active &middot; Live trading</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              <MetricPill
                label="P&L"
                value={agent.daily_pnl != null ? `$${agent.daily_pnl.toFixed(0)}` : '$0'}
                trend={agent.daily_pnl != null ? (agent.daily_pnl >= 0 ? 'up' : 'down') : 'neutral'}
              />
              <MetricPill
                label="Trades"
                value={`${agent.total_trades ?? 0}`}
                trend="neutral"
              />
              <MetricPill
                label="Win Rate"
                value={agent.win_rate != null ? `${(agent.win_rate * 100).toFixed(0)}%` : '—'}
                trend={agent.win_rate != null ? (agent.win_rate >= 0.5 ? 'up' : 'down') : 'neutral'}
              />
              <MetricPill
                label="Conf"
                value={agent.model_accuracy != null ? `${(agent.model_accuracy * 100).toFixed(0)}%` : '—'}
                trend="neutral"
              />
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-1 border-t border-border/50">
          <p className="text-[11px] text-muted-foreground">
            {agent.channel_name ? `#${agent.channel_name}` : new Date(agent.created_at).toLocaleDateString()}
          </p>
          {agent.last_signal_at ? (
            <p className="text-[11px] text-muted-foreground truncate max-w-[50%]">
              Last signal {new Date(agent.last_signal_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
            </p>
          ) : config.data_source ? (
            <p className="text-[11px] text-muted-foreground truncate max-w-[50%]">
              {String(config.data_source)}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function StepIndicator({ currentStep }: { currentStep: number }) {
  return (
    <div className="flex items-center justify-between mb-6 overflow-x-auto">
      {WIZARD_STEPS.map((label, idx) => (
        <div key={label} className="flex items-center">
          <div className="flex flex-col items-center">
            <div
              className={`h-8 w-8 rounded-full flex items-center justify-center text-sm font-medium border-2 transition-colors shrink-0 ${
                idx < currentStep
                  ? 'bg-primary border-primary text-primary-foreground'
                  : idx === currentStep
                    ? 'border-primary text-primary bg-primary/10'
                    : 'border-muted-foreground/30 text-muted-foreground'
              }`}
            >
              {idx < currentStep ? '✓' : idx + 1}
            </div>
            <span className={`text-xs mt-1 hidden sm:block whitespace-nowrap ${idx === currentStep ? 'text-primary font-medium' : 'text-muted-foreground'}`}>
              {label}
            </span>
          </div>
          {idx < WIZARD_STEPS.length - 1 && (
            <div className={`h-0.5 w-4 sm:w-8 mx-1 mt-[-14px] sm:mt-[-14px] ${idx < currentStep ? 'bg-primary' : 'bg-muted-foreground/30'}`} />
          )}
        </div>
      ))}
    </div>
  )
}

function StepChannel({ form, onChange, connectors }: {
  form: WizardFormData
  onChange: (f: Partial<WizardFormData>) => void
  connectors: ConnectorInfo[]
}) {
  const isTrading = form.type === 'trading'

  const allowed = isTrading
    ? connectors.filter((c) => c.type === 'discord')
    : connectors.filter((c) => ['discord', 'reddit', 'twitter', 'unusual_whales', 'news_api'].includes(c.type))

  const selectConnector = (id: string) => {
    if (isTrading) {
      onChange({ connector_ids: [id], selected_channel: null })
    } else {
      const next = form.connector_ids.includes(id)
        ? form.connector_ids.filter((c) => c !== id)
        : [...form.connector_ids, id]
      onChange({ connector_ids: next })
    }
  }

  const selectedConnector = isTrading && form.connector_ids.length === 1
    ? connectors.find((c) => c.id === form.connector_ids[0])
    : null

  const channelsFromConnector = (c: ConnectorInfo | null | undefined): Array<{ channel_id: string; channel_name: string }> => {
    if (!c) return []
    const chs = c.config?.selected_channels
    if (!Array.isArray(chs)) return []
    return chs as Array<{ channel_id: string; channel_name: string }>
  }

  const channels = channelsFromConnector(selectedConnector)

  return (
    <div className="space-y-4">
      <div>
        <Label>Agent Name</Label>
        <Input
          value={form.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="e.g. SPY-Discord-Trader"
        />
      </div>
      <div>
        <Label>Type</Label>
        <Select value={form.type} onValueChange={(v) => onChange({ type: v })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {AGENT_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <AiAssistPopover
        label="Description"
        value={form.description}
        onChange={(v) => onChange({ description: v })}
        placeholder="What does this agent do?"
        multiline
        context={`agent type: ${form.type}`}
      />

      <div className="border-t pt-4">
        <p className="text-sm text-muted-foreground mb-3">
          {isTrading
            ? 'Select a Discord connector and one channel to ingest trading signals from.'
            : 'Select data sources for trend analysis.'}
        </p>
        {allowed.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center">
            <Plug className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {isTrading ? 'No Discord connectors found.' : 'No matching connectors found.'}
            </p>
            <Link to="/connectors">
              <Button variant="outline" size="sm">
                <Plus className="h-4 w-4 mr-1.5" /> Add Connectors
              </Button>
            </Link>
          </div>
        ) : (
          <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              {isTrading ? 'Discord Servers' : 'Data Sources'}
            </p>
            {allowed.map((c) => {
              const meta = getPlatformMeta(c.type)
              const Icon = meta.icon
              const selected = form.connector_ids.includes(c.id)
              return (
                <div key={c.id}>
                  <button
                    type="button"
                    onClick={() => selectConnector(c.id)}
                    className={`w-full flex items-center gap-3 rounded-lg border p-3 text-left transition-all ${
                      selected
                        ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
                        : 'border-border hover:border-primary/40 hover:bg-accent/50'
                    }`}
                  >
                    {isTrading ? (
                      <div className={`h-4 w-4 rounded-full border-2 shrink-0 ${selected ? 'border-primary bg-primary' : 'border-muted-foreground/40'}`}>
                        {selected && <div className="h-full w-full rounded-full bg-primary" />}
                      </div>
                    ) : selected ? (
                      <CheckSquare className="h-4 w-4 text-primary shrink-0" />
                    ) : (
                      <SquareIcon className="h-4 w-4 text-muted-foreground/40 shrink-0" />
                    )}
                    <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${meta.bgColor}`}>
                      <Icon className={`h-4 w-4 ${meta.color}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{c.name}</p>
                      <p className="text-xs text-muted-foreground truncate">{connectorSummary(c)}</p>
                    </div>
                    <Badge variant="outline" className={`text-[10px] ${meta.color}`}>{meta.label}</Badge>
                  </button>

                  {isTrading && selected && channels.length > 0 && (
                    <div className="ml-7 mt-2 space-y-1 border-l-2 border-primary/20 pl-4">
                      <p className="text-xs font-medium text-muted-foreground mb-1.5">Select one channel:</p>
                      {channels.map((ch) => {
                        const isActive = form.selected_channel?.channel_id === ch.channel_id
                        return (
                          <button
                            key={ch.channel_id}
                            type="button"
                            onClick={() => onChange({ selected_channel: { channel_id: ch.channel_id, channel_name: ch.channel_name } })}
                            className={`w-full flex items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-all ${
                              isActive
                                ? 'bg-primary/10 text-primary font-medium'
                                : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                            }`}
                          >
                            <div className={`h-3.5 w-3.5 rounded-full border-2 shrink-0 flex items-center justify-center ${isActive ? 'border-primary' : 'border-muted-foreground/40'}`}>
                              {isActive && <div className="h-1.5 w-1.5 rounded-full bg-primary" />}
                            </div>
                            <Hash className="h-3.5 w-3.5 shrink-0 opacity-50" />
                            <span className="truncate">{ch.channel_name}</span>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {form.connector_ids.length > 0 && !isTrading && (
          <p className="text-xs text-muted-foreground mt-2">
            {form.connector_ids.length} connector{form.connector_ids.length !== 1 ? 's' : ''} selected
          </p>
        )}
      </div>
    </div>
  )
}

function StepReview({ form, connectors }: {
  form: WizardFormData
  connectors: ConnectorInfo[]
}) {
  const typeName = AGENT_TYPES.find((t) => t.value === form.type)?.label ?? form.type
  const selectedConnectors = connectors.filter((c) => form.connector_ids.includes(c.id))

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">Review your agent configuration before creating.</p>

      <div className="rounded-lg border divide-y">
        <div className="p-3">
          <p className="text-xs text-muted-foreground">Name</p>
          <p className="font-medium">{form.name}</p>
        </div>
        <div className="p-3">
          <p className="text-xs text-muted-foreground">Type</p>
          <p className="font-medium">{typeName}</p>
        </div>
        {form.description && (
          <div className="p-3">
            <p className="text-xs text-muted-foreground">Description</p>
            <p className="text-sm">{form.description}</p>
          </div>
        )}
        <div className="p-3">
          <p className="text-xs text-muted-foreground">Connectors</p>
          <div className="flex flex-wrap gap-1 mt-1">
            {selectedConnectors.length === 0 ? (
              <span className="text-sm text-muted-foreground">None selected</span>
            ) : (
              selectedConnectors.map((c) => {
                const meta = getPlatformMeta(c.type)
                return (
                  <Badge key={c.id} variant="secondary" className="gap-1">
                    <span className={meta.color}>●</span> {c.name}
                  </Badge>
                )
              })
            )}
          </div>
          {form.selected_channel && (
            <p className="text-xs text-muted-foreground mt-1.5 flex items-center gap-1">
              <Hash className="h-3 w-3" /> Channel: <span className="font-medium text-foreground">{form.selected_channel.channel_name}</span>
            </p>
          )}
        </div>
        <div className="p-3">
          <p className="text-xs text-muted-foreground">Execution</p>
          <p className="text-sm mt-1">Backtesting runs on the Phoenix server. Live trading uses a managed Docker worker.</p>
        </div>
        <div className="p-3">
          <p className="text-xs text-muted-foreground">Risk Configuration</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-1">
            <div>
              <p className="text-xs text-muted-foreground">Max Daily Loss</p>
              <p className="font-mono font-medium">{form.max_daily_loss_pct}%</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Max Position</p>
              <p className="font-mono font-medium">{form.max_position_pct}%</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Stop Loss</p>
              <p className="font-mono font-medium">{form.stop_loss_pct}%</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function SliderInput({ label, value, onChange, min, max, step, unit }: {
  label: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  step: number
  unit: string
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        <span className="text-sm font-mono font-medium">{value}{unit}</span>
      </div>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="flex-1 accent-primary"
        />
        <Input
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => {
            const v = parseFloat(e.target.value)
            if (!isNaN(v) && v >= min && v <= max) onChange(v)
          }}
          className="w-20"
        />
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{min}{unit}</span>
        <span>{max}{unit}</span>
      </div>
    </div>
  )
}

function StepRiskConfig({ form, onChange }: { form: WizardFormData; onChange: (f: Partial<WizardFormData>) => void }) {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
        <p className="text-xs text-blue-400">
          <strong>Tip:</strong> These defaults are a starting point. When backtesting completes, the agent&apos;s risk parameters will be automatically tuned based on historical performance (optimal stop-loss, position sizing, max drawdown). You can override them anytime from the agent&apos;s Rules tab.
        </p>
      </div>
      <SliderInput
        label="Max Daily Loss"
        value={form.max_daily_loss_pct}
        onChange={(v) => onChange({ max_daily_loss_pct: v })}
        min={0.5}
        max={20}
        step={0.5}
        unit="%"
      />
      <SliderInput
        label="Max Position Size"
        value={form.max_position_pct}
        onChange={(v) => onChange({ max_position_pct: v })}
        min={1}
        max={50}
        step={1}
        unit="%"
      />
      <SliderInput
        label="Stop Loss"
        value={form.stop_loss_pct}
        onChange={(v) => onChange({ stop_loss_pct: v })}
        min={0.25}
        max={10}
        step={0.25}
        unit="%"
      />

      <div className="rounded-lg border p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Smart Hold</p>
            <p className="text-xs text-muted-foreground">Allow agent to hold beyond target if trade shows continued strength</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={form.smart_hold_enabled}
            onClick={() => onChange({ smart_hold_enabled: !form.smart_hold_enabled })}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.smart_hold_enabled ? 'bg-primary' : 'bg-muted'}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.smart_hold_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        {form.smart_hold_enabled && (
          <SliderInput
            label="Hold Buffer"
            value={form.smart_hold_buffer_pct}
            onChange={(v) => onChange({ smart_hold_buffer_pct: v })}
            min={5}
            max={30}
            step={1}
            unit="%"
          />
        )}
      </div>
    </div>
  )
}

function BacktestReviewDialog({ agent, open, onOpenChange }: {
  agent: AgentData | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [selectedAccountId, setSelectedAccountId] = useState<string>('')

  const { data: backtest, isLoading } = useQuery<BacktestData>({
    queryKey: ['agent-backtest', agent?.id],
    queryFn: async () => (await api.get(`/api/v2/agents/${agent!.id}/backtest`)).data,
    enabled: !!agent && open,
  })

  const { data: artifacts } = useQuery<Record<string, unknown>>({
    queryKey: ['agent-backtest-artifacts', agent?.id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${agent!.id}/backtest-artifacts`)).data } catch { return null } },
    enabled: !!agent && open,
  })

  const { data: brokerConnectors } = useQuery<Array<{ id: string; name: string; type: string; status: string }>>({
    queryKey: ['broker-connectors'],
    queryFn: async () => {
      const res = await api.get('/api/v2/connectors?type=robinhood')
      return res.data
    },
    enabled: !!agent && open,
  })

  const totalTrades = backtest?.total_trades || (artifacts?.total_trades as number) || (artifacts?.preprocessing_summary as Record<string, number>)?.total_rows || 0
  const winRate = backtest?.win_rate ?? (artifacts?.win_rate as number | null)
  const totalReturn = backtest?.total_return ?? (artifacts?.total_return as number | null)
  const sharpeRatio = backtest?.sharpe_ratio ?? (artifacts?.sharpe_ratio as number | null)
  const maxDrawdown = backtest?.max_drawdown ?? (artifacts?.max_drawdown as number | null)
  const modelResults = (artifacts?.all_model_results as Array<Record<string, unknown>>) || []
  const bestModel = modelResults.length > 0 ? modelResults.reduce((a, b) => ((a.auc_roc as number) ?? 0) >= ((b.auc_roc as number) ?? 0) ? a : b) : null

  const approveMutation = useMutation({
    mutationFn: async ({ mode }: { mode: 'paper' | 'live' }) => {
      const payload: Record<string, string> = { trading_mode: mode }
      if (mode === 'live' && selectedAccountId) {
        payload.account_id = selectedAccountId
      }
      await api.post(`/api/v2/agents/${agent!.id}/approve`, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      queryClient.invalidateQueries({ queryKey: ['agent-stats'] })
      onOpenChange(false)
    },
  })

  const curve = backtest?.equity_curve ?? []
  const curveVals = curve.map((d) => d.equity)
  const curveMin = curveVals.length ? Math.min(...curveVals) : 0
  const curveMax = curveVals.length ? Math.max(...curveVals) : 1
  const curveRange = curveMax - curveMin || 1

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl w-[calc(100vw-2rem)] sm:w-full max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-blue-500" />
            Backtest Results &mdash; {agent?.name}
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : !backtest ? (
          <p className="text-center py-8 text-muted-foreground">No backtest data found.</p>
        ) : (
          <div className="space-y-6">
            {/* Summary metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Total Return', value: totalReturn != null ? `${totalReturn.toFixed(2)}%` : 'N/A', good: (totalReturn ?? 0) > 0, icon: TrendingUp },
                { label: 'Win Rate', value: `${((winRate ?? 0) * 100).toFixed(1)}%`, good: (winRate ?? 0) >= 0.5, icon: CheckCircle2 },
                { label: 'Sharpe Ratio', value: sharpeRatio != null ? sharpeRatio.toFixed(2) : 'N/A', good: (sharpeRatio ?? 0) >= 1.0, icon: Activity },
                { label: 'Max Drawdown', value: maxDrawdown != null ? `${maxDrawdown.toFixed(2)}%` : 'N/A', good: (maxDrawdown ?? 0) < 10, icon: Shield },
              ].map((m) => (
                <div key={m.label} className={`rounded-lg border p-3 ${m.good ? 'border-green-500/30 bg-green-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <m.icon className={`h-3.5 w-3.5 ${m.good ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`} />
                    <span className="text-[11px] text-muted-foreground uppercase tracking-wider">{m.label}</span>
                  </div>
                  <p className={`text-lg font-bold font-mono ${m.good ? 'text-green-700 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>{m.value}</p>
                </div>
              ))}
            </div>

            {/* Additional metrics */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground uppercase">Total Trades</p>
                <p className="text-base font-bold font-mono">{totalTrades}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground uppercase">Profit Factor</p>
                <p className="text-base font-bold font-mono">{(backtest?.metrics as Record<string, number>)?.profit_factor?.toFixed(2) ?? 'N/A'}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground uppercase">Avg Trade P&L</p>
                <p className="text-base font-bold font-mono">${(backtest?.metrics as Record<string, number>)?.avg_trade_pnl?.toFixed(2) ?? 'N/A'}</p>
              </div>
            </div>

            {/* Best model info from artifacts */}
            {bestModel && (
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
                  <p className="text-[11px] text-muted-foreground uppercase">Best Model</p>
                  <p className="text-base font-bold font-mono text-blue-400">{String(bestModel.model_name)}</p>
                </div>
                <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
                  <p className="text-[11px] text-muted-foreground uppercase">Accuracy</p>
                  <p className="text-base font-bold font-mono text-blue-400">{((bestModel.accuracy as number) * 100).toFixed(1)}%</p>
                </div>
                <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
                  <p className="text-[11px] text-muted-foreground uppercase">AUC-ROC</p>
                  <p className="text-base font-bold font-mono text-blue-400">{(bestModel.auc_roc as number)?.toFixed(3) ?? 'N/A'}</p>
                </div>
              </div>
            )}

            {/* Equity curve */}
            {curve.length > 1 && (
              <div className="rounded-lg border p-4">
                <p className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wider">Equity Curve (90 days)</p>
                <div className="relative h-40">
                  <svg viewBox={`0 0 ${curve.length} 100`} className="w-full h-full" preserveAspectRatio="none">
                    <defs>
                      <linearGradient id="eq-grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={curveVals[curveVals.length - 1] >= curveVals[0] ? '#22c55e' : '#ef4444'} stopOpacity="0.3" />
                        <stop offset="100%" stopColor={curveVals[curveVals.length - 1] >= curveVals[0] ? '#22c55e' : '#ef4444'} stopOpacity="0" />
                      </linearGradient>
                    </defs>
                    <polygon
                      points={`0,100 ${curveVals.map((v, i) => `${i},${100 - ((v - curveMin) / curveRange) * 100}`).join(' ')} ${curveVals.length - 1},100`}
                      fill="url(#eq-grad)"
                    />
                    <polyline
                      points={curveVals.map((v, i) => `${i},${100 - ((v - curveMin) / curveRange) * 100}`).join(' ')}
                      fill="none"
                      stroke={curveVals[curveVals.length - 1] >= curveVals[0] ? '#22c55e' : '#ef4444'}
                      strokeWidth="0.8"
                      vectorEffect="non-scaling-stroke"
                    />
                  </svg>
                  <div className="absolute top-0 left-0 text-[10px] font-mono text-muted-foreground">${curveMax.toLocaleString()}</div>
                  <div className="absolute bottom-0 left-0 text-[10px] font-mono text-muted-foreground">${curveMin.toLocaleString()}</div>
                </div>
                <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                  <span>{curve[0]?.date}</span>
                  <span>{curve[curve.length - 1]?.date}</span>
                </div>
              </div>
            )}

            {/* Strategy info */}
            <div className="rounded-lg border p-3 text-sm">
              <p className="text-xs text-muted-foreground uppercase mb-1">Strategy</p>
              <p className="font-medium">{backtest.strategy_template ?? 'Default'}</p>
              {backtest.start_date && backtest.end_date && (
                <p className="text-xs text-muted-foreground mt-1">
                  Period: {new Date(backtest.start_date).toLocaleDateString()} &mdash; {new Date(backtest.end_date).toLocaleDateString()}
                </p>
              )}
            </div>

            {/* Approve actions */}
            <div className="border-t pt-4 space-y-4">
              <p className="text-sm text-muted-foreground">Approve this agent for trading:</p>

              {/* Broker account selector */}
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider">Trading Account (required for live)</Label>
                {brokerConnectors && brokerConnectors.length > 0 ? (
                  <Select value={selectedAccountId} onValueChange={setSelectedAccountId}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select a Robinhood account..." />
                    </SelectTrigger>
                    <SelectContent>
                      {brokerConnectors.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          <span className="flex items-center gap-2">
                            <Landmark className="h-3.5 w-3.5" />
                            {c.name}
                            <Badge variant="outline" className="text-[10px] ml-1">{c.status}</Badge>
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600 dark:text-amber-400">
                    No Robinhood accounts configured. <Link to="/connectors" className="underline font-medium">Add one in Connectors</Link> to enable live trading.
                  </div>
                )}
              </div>

              <div className="flex gap-3">
                <Button
                  className="flex-1 gap-2"
                  variant="outline"
                  onClick={() => approveMutation.mutate({ mode: 'paper' })}
                  disabled={approveMutation.isPending}
                >
                  <FlaskConical className="h-4 w-4" />
                  {approveMutation.isPending ? 'Approving...' : 'Start Paper Trading'}
                </Button>
                <Button
                  className="flex-1 gap-2"
                  onClick={() => approveMutation.mutate({ mode: 'live' })}
                  disabled={approveMutation.isPending || !selectedAccountId}
                  title={!selectedAccountId ? 'Select a trading account first' : ''}
                >
                  <Zap className="h-4 w-4" />
                  {approveMutation.isPending ? 'Approving...' : 'Start Live Trading'}
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function AgentLeaderboard({ agents }: { agents: AgentData[] }) {
  const ranked = agents
    .filter((a) => ['RUNNING', 'PAPER', 'BACKTEST_COMPLETE'].includes(a.status))
    .map((a) => {
      const cfg = (a.config || {}) as Record<string, unknown>
      return {
        id: a.id,
        name: a.name,
        type: a.type,
        status: a.status,
        totalReturn: typeof cfg.total_return === 'number' ? cfg.total_return : null,
        winRate: typeof cfg.win_rate === 'number' ? cfg.win_rate : null,
        sharpe: typeof cfg.sharpe_ratio === 'number' ? cfg.sharpe_ratio : null,
      }
    })
    .sort((a, b) => (b.totalReturn ?? -999) - (a.totalReturn ?? -999))
    .slice(0, 5)

  if (ranked.length === 0) return null

  return (
    <div className="rounded-xl border bg-card p-4">
      <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <TrendingUp className="h-4 w-4 text-primary" />
        Agent Leaderboard
      </h3>
      <div className="space-y-2">
        {ranked.map((a, i) => (
          <Link to={`/agents/${a.id}`} key={a.id} className="flex items-center gap-3 rounded-lg bg-muted/50 px-3 py-2 hover:bg-muted/80 transition-colors cursor-pointer">
            <span className={`text-xs font-bold w-5 text-center ${i === 0 ? 'text-yellow-500' : i === 1 ? 'text-zinc-400' : i === 2 ? 'text-amber-600' : 'text-muted-foreground'}`}>
              #{i + 1}
            </span>
            <div className={`h-2 w-2 rounded-full shrink-0 ${a.type === 'trading' ? 'bg-blue-500' : 'bg-purple-500'}`} />
            <span className="text-sm font-medium flex-1 truncate">{a.name}</span>
            <div className="flex items-center gap-4 text-xs">
              {a.totalReturn !== null && (
                <span className={a.totalReturn >= 0 ? 'text-emerald-500' : 'text-red-500'}>
                  {a.totalReturn >= 0 ? '+' : ''}{a.totalReturn.toFixed(1)}%
                </span>
              )}
              {a.winRate !== null && (
                <span className="text-muted-foreground">
                  {(a.winRate * 100).toFixed(0)}% WR
                </span>
              )}
              {a.sharpe !== null && (
                <span className="text-muted-foreground">
                  {a.sharpe.toFixed(2)} SR
                </span>
              )}
            </div>
            <Badge variant="outline" className="text-[10px]">
              {a.type}
            </Badge>
          </Link>
        ))}
      </div>
    </div>
  )
}

export default function AgentsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [selected, setSelected] = useState<AgentData | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [wizardStep, setWizardStep] = useState(0)
  const [form, setForm] = useState<WizardFormData>({ ...DEFAULT_FORM })
  const [reviewAgent, setReviewAgent] = useState<AgentData | null>(null)

  const updateForm = useCallback((partial: Partial<WizardFormData>) => {
    setForm((prev) => ({ ...prev, ...partial }))
  }, [])

  const resetWizard = useCallback(() => {
    setWizardStep(0)
    setForm({ ...DEFAULT_FORM })
  }, [])

  const { data: agents = [], isLoading } = useQuery<AgentData[]>({
    queryKey: ['agents'],
    queryFn: async () => (await api.get('/api/v2/agents')).data,
    refetchInterval: (query) => {
      const data = query.state.data as AgentData[] | undefined
      const hasBacktesting = data?.some((a) => a.status === 'BACKTESTING')
      return hasBacktesting ? 5000 : 10000
    },
  })

  // Backtesting is now handled locally via task_runner — no VPS needed

  const { data: stats } = useQuery<AgentStats>({
    queryKey: ['agent-stats'],
    queryFn: async () => (await api.get('/api/v2/agents/stats')).data,
    refetchInterval: 15000,
  })

  const { data: connectors = [] } = useQuery<ConnectorInfo[]>({
    queryKey: ['connectors'],
    queryFn: async () => (await api.get('/api/v2/connectors')).data,
  })

  const invalidateAgents = () => {
    queryClient.invalidateQueries({ queryKey: ['agents'] })
    queryClient.invalidateQueries({ queryKey: ['agent-stats'] })
  }

  const createMutation = useMutation({
    mutationFn: async () => {
      const config: Record<string, unknown> = {
        max_daily_loss_pct: form.max_daily_loss_pct,
        max_position_pct: form.max_position_pct,
        stop_loss_pct: form.stop_loss_pct,
        smart_hold_enabled: form.smart_hold_enabled,
        smart_hold_buffer_pct: form.smart_hold_buffer_pct,
        source_config: form.source_config,
      }
      if (form.type === 'trading' && form.selected_channel) {
        config.selected_channel = form.selected_channel
      }
      const payload = {
        name: form.name,
        type: form.type,
        description: form.description,
        skills: form.skills,
        connector_ids: form.connector_ids,
        config,
      }
      await api.post('/api/v2/agents', payload)
    },
    onSuccess: () => {
      invalidateAgents()
      setCreateOpen(false)
      resetWizard()
    },
  })

  const pauseMutation = useMutation({
    mutationFn: async (id: string) => api.post(`/api/v2/agents/${id}/pause`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agents'] }),
  })

  const resumeMutation = useMutation({
    mutationFn: async (id: string) => api.post(`/api/v2/agents/${id}/resume`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agents'] }),
  })

  const promoteMutation = useMutation({
    mutationFn: async (id: string) => api.post(`/api/v2/agents/${id}/promote`),
    onSuccess: invalidateAgents,
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => api.delete(`/api/v2/agents/${id}`),
    onSuccess: invalidateAgents,
  })

  const canAdvance = (step: number): boolean => {
    switch (step) {
      case 0: {
        if (form.name.trim().length === 0) return false
        if (form.type === 'trading') {
          return form.connector_ids.length === 1 && form.selected_channel !== null
        }
        return form.connector_ids.length > 0
      }
      case 1: return true
      case 2: return true
      default: return false
    }
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <PageHeader icon={Bot} title="Agents" description="Manage Claude Code trading and monitoring agents" />
        </div>
        <Dialog
          open={createOpen}
          onOpenChange={(open) => {
            setCreateOpen(open)
            if (!open) resetWizard()
          }}
        >
          <DialogTrigger asChild>
            <Button><Plus className="h-4 w-4 mr-2" /> New Agent</Button>
          </DialogTrigger>
          <DialogContent className="max-w-xl w-[calc(100vw-2rem)] sm:w-full">
            <DialogHeader>
              <DialogTitle>Create Agent</DialogTitle>
            </DialogHeader>

            <StepIndicator currentStep={wizardStep} />

            <div className="min-h-[280px]">
              {wizardStep === 0 && <StepChannel form={form} onChange={updateForm} connectors={connectors} />}
              {wizardStep === 1 && <StepRiskConfig form={form} onChange={updateForm} />}
              {wizardStep === 2 && <StepReview form={form} connectors={connectors} />}
            </div>

            <div className="flex items-center justify-between pt-4 border-t">
              <Button
                variant="outline"
                onClick={() => setWizardStep((s) => s - 1)}
                disabled={wizardStep === 0}
              >
                <ChevronLeft className="h-4 w-4 mr-1" /> Back
              </Button>

              {wizardStep < WIZARD_STEPS.length - 1 ? (
                <Button
                  onClick={() => setWizardStep((s) => s + 1)}
                  disabled={!canAdvance(wizardStep)}
                >
                  Next <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              ) : (
                <Button
                  onClick={() => createMutation.mutate()}
                  disabled={!canAdvance(wizardStep) || createMutation.isPending}
                >
                  {createMutation.isPending ? 'Creating...' : 'Create Agent'}
                </Button>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
          <MetricCard title="Total Agents" value={stats.total} />
          <MetricCard title="Running" value={stats.running} trend="up" />
          <MetricCard title="Paused" value={stats.paused} trend="neutral" />
          <MetricCard title="Backtesting" value={stats.backtesting} />
          <MetricCard title="P&L Today" value={`$${(stats.daily_pnl ?? 0).toLocaleString()}`} trend={(stats.daily_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        </div>
      )}

      {/* P6: Global portfolio equity curve */}
      <EquityCurveChart title="Global Portfolio (all agents)" days={30} />

      {/* P1: Quick spawn typed agent */}
      <QuickSpawnTypedAgent />


      {/* Leaderboard */}
      {agents.filter((a) => ['RUNNING', 'PAPER', 'BACKTEST_COMPLETE'].includes(a.status)).length > 0 && (
        <AgentLeaderboard agents={agents} />
      )}

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-40 rounded-lg border animate-pulse bg-muted" />
          ))}
        </div>
      ) : agents.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p className="text-lg">No agents yet</p>
          <p className="text-sm">Create your first agent to get started</p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Trading Agents Section */}
          {(() => {
            const tradingAgents = agents.filter((a) => a.type === 'trading')
            if (tradingAgents.length === 0) return null
            return (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <div className="h-2 w-2 rounded-full bg-blue-500" />
                  <h2 className="text-base font-semibold">Trading Agents</h2>
                  <span className="text-xs text-muted-foreground ml-1">({tradingAgents.length})</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4">
                  {tradingAgents.map((agent) => (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      onSelect={() => agent.status !== 'BACKTESTING' && navigate(`/agents/${agent.id}`)}
                      onPause={() => pauseMutation.mutate(agent.id)}
                      onResume={() => resumeMutation.mutate(agent.id)}
                      onReview={() => setReviewAgent(agent)}
                      onPromote={() => promoteMutation.mutate(agent.id)}
                      onDelete={() => deleteMutation.mutate(agent.id)}
                    />
                  ))}
                </div>
              </div>
            )
          })()}

          {/* Trend Agents Section */}
          {(() => {
            const trendAgents = agents.filter((a) => a.type === 'trend' || a.type === 'sentiment')
            if (trendAgents.length === 0) return null
            return (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <div className="h-2 w-2 rounded-full bg-purple-500" />
                  <h2 className="text-base font-semibold">Trend Agents</h2>
                  <span className="text-xs text-muted-foreground ml-1">({trendAgents.length})</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4">
                  {trendAgents.map((agent) => (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      onSelect={() => agent.status !== 'BACKTESTING' && navigate(`/agents/${agent.id}`)}
                      onPause={() => pauseMutation.mutate(agent.id)}
                      onResume={() => resumeMutation.mutate(agent.id)}
                      onReview={() => setReviewAgent(agent)}
                      onPromote={() => promoteMutation.mutate(agent.id)}
                      onDelete={() => deleteMutation.mutate(agent.id)}
                    />
                  ))}
                </div>
              </div>
            )
          })()}
        </div>
      )}

      <SidePanel
        open={!!selected}
        onOpenChange={() => setSelected(null)}
        title={selected?.name ?? ''}
        description={`${selected?.type} agent`}
      >
        {selected && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <span className="text-muted-foreground">Status</span>
              <StatusBadge status={selected.status} />
              <span className="text-muted-foreground">Type</span>
              <span className="capitalize">{selected.type}</span>
              <span className="text-muted-foreground">Worker</span>
              <span className="font-mono text-xs">{selected.worker_status || 'STOPPED'}</span>
              <span className="text-muted-foreground">Created</span>
              <span>{new Date(selected.created_at).toLocaleString()}</span>
            </div>

            {selected.status === 'BACKTESTING' && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
                <BacktestingSpinner />
                <p className="text-xs text-muted-foreground mt-2">Backtest will complete automatically. Agent will be ready for review once done.</p>
              </div>
            )}

            {selected.status === 'BACKTEST_COMPLETE' && (
              <Button
                className="w-full gap-2"
                onClick={() => {
                  setReviewAgent(selected)
                  setSelected(null)
                }}
              >
                <Eye className="h-4 w-4" /> Review Backtest & Approve
              </Button>
            )}

            {(selected.status === 'PAPER' || selected.status === 'APPROVED') && (
              <Button
                className="w-full gap-2"
                onClick={() => {
                  promoteMutation.mutate(selected.id)
                  setSelected({ ...selected, status: 'RUNNING' })
                }}
                disabled={promoteMutation.isPending}
              >
                <Rocket className="h-4 w-4" />
                {promoteMutation.isPending ? 'Promoting...' : 'Promote to Live Trading'}
              </Button>
            )}

            {selected.config && Object.keys(selected.config).length > 0 && (
              <div>
                <p className="text-sm font-medium mb-2">Configuration</p>
                <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-60">
                  {JSON.stringify(selected.config, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </SidePanel>

      <BacktestReviewDialog
        agent={reviewAgent}
        open={!!reviewAgent}
        onOpenChange={(open) => { if (!open) setReviewAgent(null) }}
      />
    </div>
  )
}
