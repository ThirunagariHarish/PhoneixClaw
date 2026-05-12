/**
 * Backtests — View all backtesting runs with live progress and logs.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { useRealtimeQuery } from '@/hooks/use-websocket'
import { useBacktestProgress } from '@/hooks/useBacktestProgress'
import SubProgressBar from '@/components/backtests/SubProgressBar'
import {
  FlaskConical, Play, CheckCircle2, XCircle, Clock, Loader2,
  ArrowRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const PIPELINE_STEPS = [
  { key: 'init', label: 'Init', desc: 'Initialise pipeline' },
  { key: 'resolving_connectors', label: 'Connect', desc: 'Resolve Discord channels' },
  { key: 'ingesting_messages', label: 'Ingest', desc: 'Fetch historical messages' },
  { key: 'parsing_signals', label: 'Parse', desc: 'Parse trade signals' },
  { key: 'enriching_market_data', label: 'Enrich', desc: 'Add market data' },
  { key: 'analyzing_patterns', label: 'Analyse', desc: 'Discover patterns' },
  { key: 'computing_metrics', label: 'Metrics', desc: 'Compute performance' },
  { key: 'complete', label: 'Done', desc: 'Pipeline complete' },
]

const STATUS_STYLES: Record<string, { color: string; bg: string; icon: typeof Play }> = {
  RUNNING: { color: 'text-blue-400', bg: 'bg-blue-500/10', icon: Loader2 },
  COMPLETED: { color: 'text-emerald-400', bg: 'bg-emerald-500/10', icon: CheckCircle2 },
  FAILED: { color: 'text-red-400', bg: 'bg-red-500/10', icon: XCircle },
  PENDING: { color: 'text-zinc-400', bg: 'bg-zinc-500/10', icon: Clock },
}

interface Backtest {
  id: string
  agent_id: string
  status: string
  strategy_template: string | null
  parameters: Record<string, unknown>
  metrics: Record<string, unknown>
  equity_curve?: Array<{ day: number; date: string; equity: number }>
  total_trades: number
  win_rate: number | null
  sharpe_ratio: number | null
  max_drawdown: number | null
  total_return: number | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}

interface LogEntry {
  id: string
  source: string
  level: string
  service: string
  message: string
  details: Record<string, unknown>
  step: string | null
  progress_pct: number | null
  created_at: string
}

export default function Backtests() {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // Real-time updates via WebSocket — invalidates backtest queries on events
  useRealtimeQuery({
    channel: 'backtest-progress',
    queryKeys: [['backtests'], ['backtest-logs', selectedId ?? '']],
  })

  const { data: backtests = [] } = useQuery({
    queryKey: ['backtests'],
    queryFn: () => api.get<Backtest[]>('/api/v2/backtests').then(r => Array.isArray(r.data) ? r.data : []),
    refetchInterval: 30000, // Fallback polling (WS handles real-time)
  })

  const { data: agents = [] } = useQuery({
    queryKey: ['agents-list'],
    queryFn: () => api.get<{ id: string; name: string }[]>('/api/v2/agents').then(r => Array.isArray(r.data) ? r.data : []),
  })

  const { data: logs = [] } = useQuery({
    queryKey: ['backtest-logs', selectedId],
    queryFn: () => selectedId
      ? api.get<LogEntry[]>(`/api/v2/system-logs?backtest_id=${selectedId}&limit=200`).then(r => Array.isArray(r.data) ? r.data : [])
      : Promise.resolve([]),
    enabled: !!selectedId,
    refetchInterval: selectedId ? 15000 : false, // Fallback; WS handles real-time
  })

  const agentName = (agentId: string) => agents.find(a => a.id === agentId)?.name || agentId.slice(0, 8)
  const running = backtests.filter(b => b.status === 'RUNNING').length
  const completed = backtests.filter(b => b.status === 'COMPLETED').length
  const failed = backtests.filter(b => b.status === 'FAILED').length
  const selected = backtests.find(b => b.id === selectedId)

  const currentStep = (() => {
    if (logs.length === 0) return null
    const filtered = logs.filter(l => l.step)
    return filtered[filtered.length - 1]?.step || null
  })()

  // Poll substep progress for the selected backtest
  const { data: stepLogs = [] } = useBacktestProgress({
    agentId: selected?.agent_id || null,
    backtestId: selectedId,
    isRunning: selected?.status === 'RUNNING',
  })

  // Filter substep events for long-running steps
  const substepEvents = stepLogs.filter(log =>
    log.step.startsWith('enrich_') ||
    log.step.startsWith('preprocess_') ||
    log.step.startsWith('train_') ||
    log.step.startsWith('evaluate_') ||
    log.step.startsWith('patterns_')
  )

  const latestSubstep = substepEvents.length > 0 ? substepEvents[substepEvents.length - 1] : null
  const recentSubsteps = substepEvents.slice(-10).reverse() // Last 10, newest first

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FlaskConical className="h-6 w-6 text-purple-500" />
          Backtesting
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          View and monitor all backtesting pipeline runs
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Total Runs', value: backtests.length, color: 'text-foreground' },
          { label: 'Running', value: running, color: 'text-blue-400' },
          { label: 'Completed', value: completed, color: 'text-emerald-400' },
          { label: 'Failed', value: failed, color: 'text-red-400' },
        ].map(card => (
          <div key={card.label} className="bg-card border border-border rounded-xl p-4">
            <div className="text-xs text-muted-foreground">{card.label}</div>
            <div className={cn('text-2xl font-bold mt-1', card.color)}>{card.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Run List */}
        <div className="lg:col-span-1 space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Runs</h3>
          {backtests.length === 0 && (
            <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">
              No backtesting runs yet
            </div>
          )}
          {backtests.map(bt => {
            const ss = STATUS_STYLES[bt.status] || STATUS_STYLES.PENDING
            const StatusIcon = ss.icon
            const isSelected = selectedId === bt.id
            return (
              <button
                key={bt.id}
                onClick={() => setSelectedId(bt.id)}
                className={cn(
                  'w-full text-left bg-card border rounded-xl p-4 transition-all hover:border-primary/50',
                  isSelected ? 'border-primary ring-1 ring-primary/30' : 'border-border'
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm">{agentName(bt.agent_id)}</span>
                  <span className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full', ss.bg, ss.color)}>
                    <StatusIcon className={cn('h-3 w-3', bt.status === 'RUNNING' && 'animate-spin')} />
                    {bt.status}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                  <span>{bt.total_trades} trades</span>
                  {bt.win_rate != null && <span>{((bt.win_rate ?? 0) * 100).toFixed(1)}% win</span>}
                  {bt.sharpe_ratio != null && <span>SR {(bt.sharpe_ratio ?? 0).toFixed(2)}</span>}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {bt.created_at ? (() => { const d = new Date(bt.created_at); return isNaN(d.getTime()) ? 'N/A' : d.toLocaleString() })() : 'N/A'}
                </div>
              </button>
            )
          })}
        </div>

        {/* Detail Panel */}
        <div className="lg:col-span-2 space-y-4">
          {!selected ? (
            <div className="bg-card border border-border rounded-xl p-12 text-center text-muted-foreground">
              <FlaskConical className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>Select a backtest run to view details</p>
            </div>
          ) : (
            <>
              {/* Pipeline Steps */}
              <div className="bg-card border border-border rounded-xl p-4">
                <h3 className="text-sm font-medium mb-3">Pipeline Progress</h3>
                <div className="flex items-center gap-1 overflow-x-auto pb-2">
                  {PIPELINE_STEPS.map((step, i) => {
                    const stepLogs = logs.filter(l => l.step === step.key)
                    const stepIdx = PIPELINE_STEPS.findIndex(s => s.key === currentStep)
                    const isDone = stepLogs.length > 0 && (i < stepIdx || currentStep === 'complete' || selected?.status === 'COMPLETED')
                    const isCurrent = currentStep === step.key && selected?.status !== 'COMPLETED'
                    const isFailed = stepLogs.some(l => l.level === 'ERROR') || (selected?.status === 'FAILED' && currentStep === step.key)
                    return (
                      <div key={step.key} className="flex items-center gap-1">
                        <div className="flex flex-col items-center min-w-[70px]">
                          <div className={cn(
                            'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all',
                            isDone ? 'border-emerald-500 bg-emerald-500/20 text-emerald-400' :
                            isFailed ? 'border-red-500 bg-red-500/20 text-red-400' :
                            isCurrent ? 'border-blue-500 bg-blue-500/20 text-blue-400 animate-pulse' :
                            'border-border bg-muted text-muted-foreground'
                          )}>
                            {isDone ? '✓' : isFailed ? '✗' : i + 1}
                          </div>
                          <span className="text-[10px] mt-1 text-center text-muted-foreground">{step.label}</span>
                        </div>
                        {i < PIPELINE_STEPS.length - 1 && (
                          <ArrowRight className={cn('h-3 w-3 shrink-0 mt-[-12px]', isDone ? 'text-emerald-500' : 'text-border')} />
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Current Step Detail (substep progress) */}
              {latestSubstep && (
                <div className="bg-card border border-border rounded-xl p-4 space-y-3">
                  <h3 className="text-sm font-medium">Current Step Detail</h3>
                  <SubProgressBar
                    step={latestSubstep.step}
                    message={latestSubstep.message}
                    percent={latestSubstep.sub_progress_pct}
                  />
                  {recentSubsteps.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground uppercase tracking-wider">Recent Substeps</div>
                      <div className="max-h-[120px] overflow-y-auto space-y-1 text-xs font-mono">
                        {recentSubsteps.map((log, idx) => {
                          const time = log.ts ? (() => {
                            const d = new Date(log.ts)
                            return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('en-US', { hour12: false })
                          })() : ''
                          return (
                            <div
                              key={`${log.id}-${idx}`}
                              className="flex items-center gap-2 px-2 py-1 bg-slate-800/50 rounded border border-slate-700"
                            >
                              <span className="text-slate-400 shrink-0 w-[65px]">{time}</span>
                              <span className="text-cyan-400 shrink-0">{log.sub_progress_pct}%</span>
                              <span className="text-slate-300 truncate">{log.message}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Metrics */}
              {selected.status === 'COMPLETED' && (
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Trades', value: selected.total_trades },
                    { label: 'Win Rate', value: selected.win_rate !== null ? `${(selected.win_rate * 100).toFixed(1)}%` : 'N/A' },
                    { label: 'Sharpe', value: selected.sharpe_ratio?.toFixed(2) ?? 'N/A' },
                    { label: 'Return', value: selected.total_return !== null ? `${(selected.total_return * 100).toFixed(1)}%` : 'N/A' },
                  ].map(m => (
                    <div key={m.label} className="bg-card border border-border rounded-lg p-3">
                      <div className="text-[10px] text-muted-foreground uppercase">{m.label}</div>
                      <div className="text-lg font-bold mt-0.5">{m.value}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* BKT1: Equity Curve in Detail */}
              {selected.status === 'COMPLETED' && selected.equity_curve && selected.equity_curve.length > 1 && (() => {
                const curve = selected.equity_curve
                const vals = curve.map(d => d.equity)
                const curveMin = Math.min(...vals)
                const curveMax = Math.max(...vals)
                const curveRange = curveMax - curveMin || 1
                const isPositive = vals[vals.length - 1] >= vals[0]
                return (
                  <div className="bg-card border border-border rounded-xl p-4">
                    <h3 className="text-sm font-medium mb-3">Equity Curve</h3>
                    <div className="relative h-40">
                      <svg viewBox={`0 0 ${vals.length} 100`} className="w-full h-full" preserveAspectRatio="none">
                        <defs>
                          <linearGradient id="bt-eq-grad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity="0.3" />
                            <stop offset="100%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity="0" />
                          </linearGradient>
                        </defs>
                        <polygon
                          points={`0,100 ${vals.map((v, i) => `${i},${100 - ((v - curveMin) / curveRange) * 100}`).join(' ')} ${vals.length - 1},100`}
                          fill="url(#bt-eq-grad)"
                        />
                        <polyline
                          points={vals.map((v, i) => `${i},${100 - ((v - curveMin) / curveRange) * 100}`).join(' ')}
                          fill="none"
                          stroke={isPositive ? '#22c55e' : '#ef4444'}
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
                )
              })()}

              {/* Live Logs */}
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border flex items-center justify-between">
                  <h3 className="text-sm font-medium">Agent Activity Log</h3>
                  <span className="text-xs text-muted-foreground">{logs.length} entries</span>
                </div>
                <div className="max-h-[400px] overflow-y-auto font-mono text-xs divide-y divide-border/50">
                  {logs.length === 0 && (
                    <div className="p-6 text-center text-muted-foreground">No logs yet for this run</div>
                  )}
                  {logs.map(log => {
                    const ls = log.level === 'ERROR' ? 'text-red-400' :
                               log.level === 'WARN' ? 'text-yellow-400' :
                               log.level === 'INFO' ? 'text-blue-400' : 'text-zinc-500'
                    const time = log.created_at ? (() => { const d = new Date(log.created_at); return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('en-US', { hour12: false }) })() : ''
                    return (
                      <div key={log.id} className="px-4 py-1.5 hover:bg-muted/30 flex items-start gap-2">
                        <span className="text-muted-foreground shrink-0 w-[65px]">{time}</span>
                        <span className={cn('shrink-0 w-[45px]', ls)}>{log.level}</span>
                        {log.step && <span className="text-cyan-400 shrink-0">[{log.step}]</span>}
                        <span className="text-foreground break-all">{log.message}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Error message */}
              {selected.error_message && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
                  <h3 className="text-sm font-medium text-red-400 mb-1">Error</h3>
                  <p className="text-xs text-red-300 font-mono">{selected.error_message}</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
