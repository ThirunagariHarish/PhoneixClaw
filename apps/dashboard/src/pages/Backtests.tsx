/**
 * Backtests — View all backtesting runs with live progress and logs.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { useRealtimeQuery } from '@/hooks/use-websocket'
import {
  FlaskConical, Play, CheckCircle2, XCircle, Clock, Loader2,
  ArrowRight, BarChart3,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const PIPELINE_STEPS = [
  { key: 'transform', label: 'Transform', desc: 'Parse Discord messages → trade rows' },
  { key: 'enrich', label: 'Enrich', desc: 'Add 200+ market attributes' },
  { key: 'embed', label: 'Embed', desc: 'Compute text embeddings' },
  { key: 'preprocess', label: 'Preprocess', desc: 'Split & scale for training' },
  { key: 'train', label: 'Train', desc: 'Train 8 ML models' },
  { key: 'evaluate', label: 'Evaluate', desc: 'Select best model' },
  { key: 'explain', label: 'Explain', desc: 'Build explainability' },
  { key: 'patterns', label: 'Patterns', desc: 'Discover trading patterns' },
  { key: 'agent', label: 'Create Agent', desc: 'Ship live trading agent' },
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

  const currentStep = logs.length > 0
    ? logs.find(l => l.step)?.step || null
    : null

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
                    const isDone = stepLogs.some(l => l.message.toLowerCase().includes('complete') || l.message.toLowerCase().includes('saved'))
                    const isCurrent = currentStep === step.key
                    const isFailed = stepLogs.some(l => l.level === 'ERROR')
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
