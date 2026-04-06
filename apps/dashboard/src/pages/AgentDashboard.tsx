/**
 * AgentDashboard — Mission Control for a single agent.
 * Route: /agents/:id
 *
 * Top-level: Live | Backtesting
 * Live tabs: Portfolio | Trades | Chat | Intelligence | Logs | Rules
 * Backtesting tabs: Overview | Models | Features | Downloads
 */
import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useRealtimeQuery } from '@/hooks/use-websocket'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AreaChart } from '@/components/tremor/AreaChart'
import {
  ArrowLeft, Bot, Pause, Play, Send, MessageSquare, User,
  Shield, TrendingUp, List, ScrollText, BookOpen,
  ChevronDown, ChevronUp, Check, X,
  Download, FlaskConical, Zap, Database, Columns3, BarChart3,
  FileJson, FileSpreadsheet, FileDown, Brain,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

/* ---------- Types ---------- */

interface AgentData {
  id: string; name: string; type: string; status: string
  worker_status?: string; config: Record<string, unknown>
  channel_name?: string; analyst_name?: string
  model_type?: string; model_accuracy?: number
  daily_pnl?: number; total_pnl?: number; total_trades?: number; win_rate?: number
  current_mode?: string; rules_version?: number
  last_signal_at?: string; last_trade_at?: string; created_at: string
}

interface Position {
  id: string; ticker: string; side: string; entry_price: number
  quantity: number; entry_time: string; model_confidence?: number
}

interface Trade {
  id: string; ticker: string; side: string; option_type?: string
  strike?: number; entry_price: number; exit_price?: number
  quantity: number; entry_time: string; exit_time?: string
  pnl_dollar?: number; pnl_pct?: number; status: string
  model_confidence?: number; pattern_matches?: number
  reasoning?: string; signal_raw?: string
}

interface ChatMsg {
  id: string; role: 'user' | 'agent'
  content: string; message_type?: string
  metadata?: Record<string, unknown>; created_at: string
}

interface LogEntry {
  id: string; level: string; message: string
  context: Record<string, unknown>; created_at: string
}

interface ManifestData {
  agent_id: string
  manifest: Record<string, unknown>
  current_mode: string
  rules_version: number
}

interface Rule {
  name: string; condition: string; weight: number
  source?: string; enabled?: boolean; description?: string
}

interface ModelResult {
  model_name: string; accuracy?: number; precision?: number
  recall?: number; f1_score?: number; auc_roc?: number
  profit_factor?: number; sharpe_ratio?: number; max_drawdown_pct?: number
  score?: number; feature_importances?: Record<string, number>
}

interface BacktestArtifacts {
  backtest_id: string; status: string; progress_pct: number
  current_step: string | null
  total_trades: number; win_rate: number | null; sharpe_ratio: number | null
  max_drawdown: number | null; total_return: number | null
  feature_names: string[]; feature_count: number
  all_model_results: ModelResult[]; preprocessing_summary: Record<string, unknown>
  explainability: Record<string, unknown>; patterns: Array<Record<string, unknown>>
  downloadable_files: Array<{ name: string; size_bytes: number; size_human: string }>
  metrics: Record<string, unknown>
  completed_at: string | null; created_at: string | null
}

const LIVE = new Set(['LIVE', 'PAPER', 'RUNNING'])

/* ================================================================
   PORTFOLIO TAB
   ================================================================ */
function PortfolioTab({ id, agent }: { id: string; agent: AgentData }) {
  const queryClient = useQueryClient()
  const { data: positions = [] } = useQuery<Position[]>({
    queryKey: ['positions', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/positions`)).data } catch { return [] } },
    refetchInterval: 10000,
  })
  const { data: pnlCurve = [] } = useQuery<Array<{ date: string; pnl: number }>>({
    queryKey: ['pnl-curve', id],
    queryFn: async () => {
      try {
        const d = (await api.get(`/api/v2/agents/${id}/metrics/history`)).data
        let cum = 0
        return Array.isArray(d) ? d.map((m: Record<string, unknown>) => {
          cum += Number(m.daily_pnl ?? 0)
          return { date: String(m.timestamp ?? '').slice(0, 10), pnl: Math.round(cum * 100) / 100 }
        }) : []
      } catch { return [] }
    },
    refetchInterval: 30000,
  })

  const cmdMut = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/api/v2/agents/${id}/command`, body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['positions', id] }); toast.success('Command sent') },
    onError: () => toast.error('Command failed'),
  })

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
        <MetricCard title="Total P&L" value={`$${(agent.total_pnl ?? 0).toLocaleString()}`} trend={(agent.total_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        <MetricCard title="Today P&L" value={`$${(agent.daily_pnl ?? 0).toLocaleString()}`} trend={(agent.daily_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        <MetricCard title="Open Positions" value={positions.length} />
        <MetricCard title="Win Rate" value={`${((agent.win_rate ?? 0) * 100).toFixed(1)}%`} />
      </div>

      {pnlCurve.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Cumulative P&L</CardTitle></CardHeader>
          <CardContent>
            <AreaChart data={pnlCurve as Record<string, unknown>[]} index="date" categories={['pnl']} colors={['hsl(var(--chart-1))']} showLegend={false} valueFormatter={(v) => `$${v.toLocaleString()}`} className="h-48 sm:h-64" />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Open Positions ({positions.length})</CardTitle></CardHeader>
        <CardContent>
          {positions.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No open positions.</p>
          ) : (
            <div className="space-y-2">
              {positions.map(p => (
                <div key={p.id} className="flex items-center gap-3 rounded-lg border p-3">
                  <div className="flex-1 min-w-0">
                    <p className="font-mono font-semibold text-sm">{p.ticker}</p>
                    <p className="text-xs text-muted-foreground">{p.side} &middot; {p.quantity} @ ${p.entry_price.toFixed(2)}</p>
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'close_position', ticker: p.ticker, pct: 50 })} disabled={cmdMut.isPending}>50%</Button>
                    <Button size="sm" variant="destructive" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'close_position', ticker: p.ticker, pct: 100 })} disabled={cmdMut.isPending}>Close</Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ================================================================
   TRADES TAB
   ================================================================ */
function TradesTab({ id }: { id: string }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const { data: trades = [] } = useQuery<Trade[]>({
    queryKey: ['trades', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/live-trades`)).data } catch { return [] } },
    refetchInterval: 10000,
  })

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Trade History ({trades.length})</CardTitle></CardHeader>
        <CardContent>
          {trades.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No trades recorded yet.</p>
          ) : (
            <div className="space-y-1">
              {trades.map(t => (
                <div key={t.id}>
                  <div className="flex items-center gap-3 p-2 rounded hover:bg-muted/50 cursor-pointer" onClick={() => setExpanded(expanded === t.id ? null : t.id)}>
                    <div className="w-16 text-xs text-muted-foreground">{t.entry_time ? new Date(t.entry_time).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '—'}</div>
                    <span className="font-mono font-semibold text-sm w-24 truncate">{t.ticker}</span>
                    <Badge variant={t.side === 'buy' ? 'default' : 'destructive'} className="text-[10px] uppercase w-12 justify-center">{t.side}</Badge>
                    <span className="font-mono text-xs w-16 text-right">${t.entry_price?.toFixed(2) ?? '—'}</span>
                    <span className="font-mono text-xs w-16 text-right">{t.exit_price ? `$${t.exit_price.toFixed(2)}` : '—'}</span>
                    <span className={cn('font-mono text-xs font-medium w-20 text-right', (t.pnl_dollar ?? 0) >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
                      {t.pnl_dollar != null ? `${t.pnl_dollar >= 0 ? '+' : ''}$${t.pnl_dollar.toFixed(2)}` : '—'}
                    </span>
                    <span className="text-xs w-12 text-right">{t.model_confidence != null ? `${(t.model_confidence * 100).toFixed(0)}%` : '—'}</span>
                    <StatusBadge status={t.status} />
                    {expanded === t.id ? <ChevronUp className="h-3.5 w-3.5 ml-auto" /> : <ChevronDown className="h-3.5 w-3.5 ml-auto" />}
                  </div>
                  {expanded === t.id && (
                    <div className="ml-4 mb-3 p-3 rounded-lg bg-muted/30 border text-xs space-y-2">
                      {t.signal_raw && <div><span className="font-semibold">Signal:</span> <span className="font-mono">{t.signal_raw}</span></div>}
                      {t.reasoning && <div><span className="font-semibold">Reasoning:</span> {t.reasoning}</div>}
                      {t.pattern_matches != null && <div><span className="font-semibold">Pattern Matches:</span> {t.pattern_matches}</div>}
                      {t.option_type && <div><span className="font-semibold">Option:</span> {t.option_type} {t.strike && `$${t.strike}`}</div>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ================================================================
   CHAT TAB
   ================================================================ */
function ChatTab({ id, agentName }: { id: string; agentName: string }) {
  const [message, setMessage] = useState('')
  const queryClient = useQueryClient()
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data: chatHistory = [] } = useQuery<ChatMsg[]>({
    queryKey: ['agent-chat', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/chat`)).data } catch { return [] } },
    refetchInterval: 5000,
  })

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chatHistory.length])

  const sendMut = useMutation({
    mutationFn: async (msg: string) => (await api.post(`/api/v2/agents/${id}/chat`, { message: msg })).data,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['agent-chat', id] }); setMessage('') },
    onError: () => toast.error('Failed to send message'),
  })

  const cmdMut = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/api/v2/agents/${id}/command`, body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['agent-chat', id] }); toast.success('Command sent') },
    onError: () => toast.error('Command failed'),
  })

  const handleSend = () => { const t = message.trim(); if (t && !sendMut.isPending) sendMut.mutate(t) }

  return (
    <div>
      <Card className="flex flex-col" style={{ height: 'calc(100vh - 380px)', minHeight: '400px' }}>
        <CardHeader className="pb-2 shrink-0">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-primary" />
            Chat with {agentName}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col overflow-hidden p-4 pt-0">
          <div className="flex gap-1.5 mb-3 flex-wrap shrink-0">
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'switch_mode', mode: 'aggressive' })}>Aggressive</Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'switch_mode', mode: 'conservative' })}>Conservative</Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'pause' })}>Pause</Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'resume' })}>Resume</Button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-3 pr-1 mb-4">
            {chatHistory.length === 0 && (
              <div className="text-center py-12 text-muted-foreground">
                <MessageSquare className="h-8 w-8 mx-auto mb-3 opacity-50" />
                <p className="text-sm">No messages yet.</p>
                <p className="text-xs mt-1">Send a message to communicate with this Claude Code agent.</p>
              </div>
            )}
            {chatHistory.map(msg => (
              <div key={msg.id} className={cn('flex gap-2.5 max-w-[85%]', msg.role === 'user' ? 'ml-auto flex-row-reverse' : '')}>
                <div className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full', msg.role === 'user' ? 'bg-primary/10' : 'bg-emerald-500/10')}>
                  {msg.role === 'user' ? <User className="h-3.5 w-3.5 text-primary" /> : <Bot className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />}
                </div>
                <div className={cn('rounded-lg px-3 py-2 text-sm', msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted')}>
                  {msg.message_type === 'trade_proposal' && (
                    <div className="mb-2 p-2 rounded bg-background/50 border border-primary/20">
                      <p className="text-xs font-semibold text-primary mb-1">Trade Proposal</p>
                      <div className="flex gap-2 mt-2">
                        <Button size="sm" className="text-xs h-6" onClick={() => cmdMut.mutate({ action: 'approve_trade', trade: msg.metadata })}><Check className="h-3 w-3 mr-1" />Approve</Button>
                        <Button size="sm" variant="outline" className="text-xs h-6"><X className="h-3 w-3 mr-1" />Reject</Button>
                      </div>
                    </div>
                  )}
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  <p className={cn('text-[10px] mt-1', msg.role === 'user' ? 'text-primary-foreground/60' : 'text-muted-foreground')}>
                    {new Date(msg.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                  </p>
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          <div className="flex gap-2 shrink-0">
            <Input value={message} onChange={e => setMessage(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }} placeholder={`Message ${agentName}...`} disabled={sendMut.isPending} className="flex-1" />
            <Button size="icon" onClick={handleSend} disabled={!message.trim() || sendMut.isPending}><Send className="h-4 w-4" /></Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/* ================================================================
   INTELLIGENCE TAB
   ================================================================ */
function IntelligenceTab({ id }: { id: string }) {
  const { data: manifestData } = useQuery<ManifestData>({
    queryKey: ['manifest', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/manifest`)).data } catch { return { agent_id: id, manifest: {}, current_mode: 'conservative', rules_version: 1 } } },
  })
  const { data: btDetail } = useQuery<Record<string, unknown>>({
    queryKey: ['backtest-detail', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/backtest`)).data } catch { return {} } },
  })

  const manifest = manifestData?.manifest ?? {}
  const rules = (manifest.rules ?? (btDetail?.metrics as Record<string, unknown>)?.rules ?? []) as Rule[]
  const knowledge = manifest.knowledge as Record<string, unknown> | undefined
  const analystProfile = knowledge?.analyst_profile as Record<string, unknown> | undefined
  const topFeatures = (knowledge?.top_features ?? []) as Array<{ name: string; importance: number }>
  const models = manifest.models as Record<string, unknown> | undefined

  return (
    <div className="space-y-4">
      {models && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Model</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-lg border p-3"><p className="text-[10px] text-muted-foreground uppercase">Primary</p><p className="text-lg font-bold font-mono mt-0.5">{String(models.primary ?? '—')}</p></div>
              <div className="rounded-lg border p-3"><p className="text-[10px] text-muted-foreground uppercase">Accuracy</p><p className="text-lg font-bold font-mono mt-0.5">{models.accuracy ? `${(Number(models.accuracy) * 100).toFixed(1)}%` : '—'}</p></div>
              <div className="rounded-lg border p-3"><p className="text-[10px] text-muted-foreground uppercase">AUC-ROC</p><p className="text-lg font-bold font-mono mt-0.5">{models.auc_roc ? Number(models.auc_roc).toFixed(3) : '—'}</p></div>
              <div className="rounded-lg border p-3"><p className="text-[10px] text-muted-foreground uppercase">Version</p><p className="text-lg font-bold font-mono mt-0.5">{String(models.version ?? '—')}</p></div>
            </div>
          </CardContent>
        </Card>
      )}

      {analystProfile && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Analyst Profile</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Win Rate', value: analystProfile.win_rate != null ? `${(Number(analystProfile.win_rate) * 100).toFixed(1)}%` : '—' },
                { label: 'Avg Hold', value: analystProfile.avg_hold_hours != null ? `${Number(analystProfile.avg_hold_hours).toFixed(1)}h` : '—' },
                { label: 'Trades/Day', value: analystProfile.avg_trades_per_day ?? '—' },
                { label: 'Swing Trader', value: analystProfile.is_swing_trader ? 'Yes' : 'No' },
              ].map(item => (
                <div key={item.label} className="rounded-lg border p-3">
                  <p className="text-[10px] text-muted-foreground uppercase">{item.label}</p>
                  <p className="text-lg font-bold font-mono mt-0.5">{String(item.value)}</p>
                </div>
              ))}
            </div>
            {(analystProfile.best_tickers as string[] | undefined)?.length ? (
              <div className="mt-3"><span className="text-xs text-muted-foreground">Best Tickers: </span>{(analystProfile.best_tickers as string[]).map(t => <Badge key={t} variant="outline" className="text-xs mr-1">{t}</Badge>)}</div>
            ) : null}
          </CardContent>
        </Card>
      )}

      {rules.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium flex items-center gap-2"><Shield className="h-4 w-4 text-primary" />Learned Rules ({rules.length})</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {rules.slice(0, 30).map((rule, i) => (
                <div key={i} className="flex items-center gap-3 rounded-lg border p-3">
                  <div className={cn('h-2 w-2 rounded-full shrink-0', rule.weight > 0.3 ? 'bg-emerald-500' : rule.weight < -0.3 ? 'bg-red-500' : 'bg-yellow-500')} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{rule.description || rule.name}</p>
                    <p className="text-xs text-muted-foreground font-mono">{rule.condition}</p>
                  </div>
                  <Badge variant="outline" className="text-[10px]">{rule.source ?? 'backtesting'}</Badge>
                  <div className={cn('text-xs font-mono font-bold px-2 py-0.5 rounded', rule.weight > 0 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500')}>
                    {rule.weight > 0 ? '+' : ''}{rule.weight.toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {topFeatures.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Top Predictive Features</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {topFeatures.slice(0, 15).map((f, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground w-5 text-right">{i + 1}.</span>
                  <span className="text-xs font-mono flex-1 truncate">{f.name}</span>
                  <div className="w-32 h-2 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full" style={{ width: `${Math.min(100, f.importance * 100)}%` }} />
                  </div>
                  <span className="text-[10px] font-mono w-10 text-right">{f.importance.toFixed(3)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {!rules.length && !topFeatures.length && !analystProfile && (
        <Card className="border-dashed">
          <CardContent className="p-8 text-center text-muted-foreground">
            <Shield className="h-8 w-8 mx-auto mb-3 opacity-50" />
            <p className="text-sm">No intelligence data available yet.</p>
            <p className="text-xs mt-1">Complete a backtest to see learned patterns, rules, and trade analysis.</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/* ================================================================
   LOGS TAB
   ================================================================ */
function LogsTab({ id }: { id: string }) {
  const [level, setLevel] = useState<string>('ALL')
  const [search, setSearch] = useState('')

  const { data: logs = [] } = useQuery<LogEntry[]>({
    queryKey: ['agent-logs', id, level],
    queryFn: async () => {
      try {
        const params: Record<string, string> = { limit: '200' }
        if (level !== 'ALL') params.level = level
        return (await api.get(`/api/v2/agents/${id}/logs`, { params })).data
      } catch { return [] }
    },
    refetchInterval: 5000,
  })

  const filteredLogs = search ? logs.filter(l => l.message.toLowerCase().includes(search.toLowerCase())) : logs

  const levelColor = (l: string) => {
    switch (l) {
      case 'ERROR': return 'text-red-500'
      case 'WARN': return 'text-yellow-500'
      case 'INFO': return 'text-blue-500'
      default: return 'text-muted-foreground'
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm font-medium flex-1">Agent Logs</CardTitle>
            <Select value={level} onValueChange={setLevel}>
              <SelectTrigger className="w-28 h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All</SelectItem>
                <SelectItem value="INFO">Info</SelectItem>
                <SelectItem value="WARN">Warn</SelectItem>
                <SelectItem value="ERROR">Error</SelectItem>
              </SelectContent>
            </Select>
            <Input placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)} className="w-48 h-8 text-xs" />
          </div>
        </CardHeader>
        <CardContent>
          <div className="max-h-[60vh] overflow-y-auto font-mono text-xs space-y-0.5">
            {filteredLogs.length === 0 ? (
              <p className="text-center text-muted-foreground py-8">No logs found.</p>
            ) : (
              filteredLogs.map(log => (
                <div key={log.id} className="flex gap-2 p-1 hover:bg-muted/30 rounded">
                  <span className="text-muted-foreground shrink-0 w-36">{new Date(log.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                  <span className={cn('shrink-0 w-12 font-bold', levelColor(log.level))}>{log.level}</span>
                  <span className="flex-1 break-all">{log.message}</span>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/* ================================================================
   RULES TAB
   ================================================================ */
function RulesTab({ id }: { id: string }) {
  const queryClient = useQueryClient()
  const { data: manifestData } = useQuery<ManifestData>({
    queryKey: ['manifest', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/manifest`)).data } catch { return { agent_id: id, manifest: {}, current_mode: 'conservative', rules_version: 1 } } },
  })

  const manifest = manifestData?.manifest ?? {}
  const rules = ((manifest.rules ?? []) as Rule[])
  const risk = (manifest.risk ?? {}) as Record<string, unknown>
  const modes = (manifest.modes ?? {}) as Record<string, Record<string, unknown>>

  const [editRules, setEditRules] = useState<Rule[] | null>(null)
  const [editRisk, setEditRisk] = useState<Record<string, unknown> | null>(null)
  const [showAddRule, setShowAddRule] = useState(false)
  const [newRule, setNewRule] = useState<Rule>({ name: '', condition: '', weight: 0, source: 'user', enabled: true, description: '' })

  const activeRules = editRules ?? rules
  const activeRisk = editRisk ?? risk

  const saveMut = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = {}
      if (editRules) payload.rules = editRules
      if (editRisk) payload.risk = editRisk
      return (await api.put(`/api/v2/agents/${id}/manifest`, payload)).data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['manifest', id] })
      setEditRules(null)
      setEditRisk(null)
      toast.success('Rules saved')
    },
    onError: () => toast.error('Failed to save'),
  })

  const hasChanges = editRules != null || editRisk != null
  const toggleRule = (idx: number) => { const r = [...(editRules ?? rules)]; r[idx] = { ...r[idx], enabled: !r[idx].enabled }; setEditRules(r) }
  const deleteRule = (idx: number) => { const r = [...(editRules ?? rules)]; r.splice(idx, 1); setEditRules(r) }
  const addRule = () => { if (!newRule.name || !newRule.condition) return; setEditRules([...(editRules ?? rules), { ...newRule }]); setNewRule({ name: '', condition: '', weight: 0, source: 'user', enabled: true, description: '' }); setShowAddRule(false) }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm font-medium flex-1">Trading Rules ({activeRules.length})</CardTitle>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => setShowAddRule(!showAddRule)}>+ Add Rule</Button>
            {hasChanges && <Button size="sm" className="text-xs h-7" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>Save Changes</Button>}
          </div>
        </CardHeader>
        <CardContent>
          {showAddRule && (
            <div className="mb-4 p-3 rounded-lg border bg-muted/20 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div><Label className="text-xs">Name</Label><Input value={newRule.name} onChange={e => setNewRule(r => ({ ...r, name: e.target.value }))} className="h-8 text-xs" placeholder="e.g. high_vix_caution" /></div>
                <div><Label className="text-xs">Condition</Label><Input value={newRule.condition} onChange={e => setNewRule(r => ({ ...r, condition: e.target.value }))} className="h-8 text-xs" placeholder="e.g. market_vix > 25" /></div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label className="text-xs">Weight</Label><Input type="number" step="0.1" value={newRule.weight} onChange={e => setNewRule(r => ({ ...r, weight: parseFloat(e.target.value) || 0 }))} className="h-8 text-xs" /></div>
                <div><Label className="text-xs">Description</Label><Input value={newRule.description ?? ''} onChange={e => setNewRule(r => ({ ...r, description: e.target.value }))} className="h-8 text-xs" placeholder="Optional" /></div>
              </div>
              <div className="flex gap-2"><Button size="sm" className="text-xs h-7" onClick={addRule}>Add</Button><Button size="sm" variant="outline" className="text-xs h-7" onClick={() => setShowAddRule(false)}>Cancel</Button></div>
            </div>
          )}
          <div className="space-y-1.5">
            {activeRules.map((rule, i) => (
              <div key={i} className={cn('flex items-center gap-3 rounded-lg border p-2', rule.enabled === false && 'opacity-50')}>
                <button className={cn('h-4 w-4 rounded border flex items-center justify-center shrink-0', rule.enabled !== false ? 'bg-primary border-primary' : 'border-muted-foreground')} onClick={() => toggleRule(i)}>
                  {rule.enabled !== false && <Check className="h-2.5 w-2.5 text-primary-foreground" />}
                </button>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium">{rule.name}</p>
                  <p className="text-[10px] text-muted-foreground font-mono truncate">{rule.condition}</p>
                </div>
                <Badge variant="outline" className="text-[10px]">{rule.source ?? 'backtesting'}</Badge>
                <span className={cn('text-xs font-mono font-bold', rule.weight > 0 ? 'text-emerald-500' : 'text-red-500')}>
                  {rule.weight > 0 ? '+' : ''}{rule.weight.toFixed(2)}
                </span>
                <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-muted-foreground hover:text-red-500" onClick={() => deleteRule(i)}><X className="h-3 w-3" /></Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Risk Parameters</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { key: 'max_position_size_pct', label: 'Max Position %', step: 0.5 },
              { key: 'max_daily_loss_pct', label: 'Max Daily Loss %', step: 0.5 },
              { key: 'max_concurrent_positions', label: 'Max Concurrent', step: 1 },
            ].map(item => (
              <div key={item.key}>
                <Label className="text-xs text-muted-foreground">{item.label}</Label>
                <Input type="number" step={item.step} value={activeRisk[item.key] as number ?? 0} onChange={e => setEditRisk({ ...(editRisk ?? risk), [item.key]: parseFloat(e.target.value) || 0 })} className="h-8 text-xs mt-1" />
              </div>
            ))}
          </div>
          {hasChanges && <Button size="sm" className="text-xs h-7 mt-3" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>Save Risk Config</Button>}
        </CardContent>
      </Card>

      {Object.keys(modes).length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Mode Settings</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {Object.entries(modes).map(([modeName, cfg]) => (
                <div key={modeName} className="rounded-lg border p-3">
                  <p className="text-sm font-semibold capitalize mb-2">{modeName}</p>
                  <div className="space-y-1 text-xs">
                    {Object.entries(cfg).map(([k, v]) => (
                      <div key={k} className="flex justify-between"><span className="text-muted-foreground">{k.replace(/_/g, ' ')}</span><span className="font-mono">{String(v)}</span></div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/* ================================================================
   BACKTESTING — PIPELINE PROGRESS
   ================================================================ */

interface BacktestLogEntry {
  id: string; step: string; message: string; progress_pct: number | null
  level: string; created_at: string; details?: Record<string, unknown>
}

const PIPELINE_STEPS = [
  { key: 'transform', label: 'Transform', pct: 15 },
  { key: 'enrich', label: 'Enrich', pct: 30 },
  { key: 'preprocess', label: 'Preprocess', pct: 35 },
  { key: 'train', label: 'Train Models', pct: 60 },
  { key: 'evaluate', label: 'Evaluate', pct: 70 },
  { key: 'patterns', label: 'Patterns', pct: 80 },
  { key: 'explainability', label: 'Explainability', pct: 85 },
  { key: 'create_live_agent', label: 'Create Agent', pct: 95 },
]

function BacktestPipelineProgress({ id, status, artifacts }: { id: string; status: string; artifacts?: BacktestArtifacts }) {
  const { data: logs = [] } = useQuery<BacktestLogEntry[]>({
    queryKey: ['backtest-logs', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/logs?source=backtest&limit=50`)).data } catch { return [] } },
    enabled: !!id,
    refetchInterval: status === 'BACKTESTING' ? 5000 : 30000,
  })

  const progressPct = artifacts?.progress_pct ?? 0
  const currentStep = artifacts?.current_step ?? ''
  const isRunning = status === 'BACKTESTING'
  const isComplete = status === 'BACKTEST_COMPLETE' || artifacts?.status === 'COMPLETED'
  const activeStepIdx = PIPELINE_STEPS.findIndex(s => currentStep.toLowerCase().includes(s.key))

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          {isRunning ? (
            <>
              <div className="h-4 w-4 rounded-full border-2 border-amber-500 border-t-transparent animate-spin" />
              <span className="text-amber-600 dark:text-amber-400">Backtesting in Progress</span>
            </>
          ) : isComplete ? (
            <>
              <div className="h-4 w-4 rounded-full bg-emerald-500 flex items-center justify-center">
                <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 12 12"><path d="M3.5 6L5.5 8L8.5 4" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </div>
              <span className="text-emerald-600 dark:text-emerald-400">Backtesting Complete</span>
            </>
          ) : (
            <span>Backtesting</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="flex justify-between text-xs text-muted-foreground mb-1.5">
            <span>{currentStep ? currentStep.replace(/_/g, ' ') : 'Starting...'}</span>
            <span className="font-mono">{progressPct}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div className={cn('h-full rounded-full transition-all duration-500', isComplete ? 'bg-emerald-500' : 'bg-amber-500', isRunning && 'animate-pulse')} style={{ width: `${Math.max(progressPct, 2)}%` }} />
          </div>
        </div>

        <div className="flex items-center gap-1 overflow-x-auto pb-1">
          {PIPELINE_STEPS.map((step, idx) => {
            const isDone = progressPct >= step.pct
            const isCurrent = activeStepIdx === idx
            return (
              <div key={step.key} className="flex items-center">
                <div className={cn(
                  'flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap border',
                  isDone ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400' :
                  isCurrent ? 'bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400' :
                  'bg-muted/50 border-border text-muted-foreground',
                )}>
                  {isDone && <svg className="h-2.5 w-2.5" viewBox="0 0 12 12"><path d="M3.5 6L5.5 8L8.5 4" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                  {isCurrent && !isDone && <div className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />}
                  {step.label}
                </div>
                {idx < PIPELINE_STEPS.length - 1 && <div className={cn('h-px w-2 mx-0.5', isDone ? 'bg-emerald-500/40' : 'bg-border')} />}
              </div>
            )
          })}
        </div>

        {logs.length > 0 && (
          <div className="max-h-40 overflow-y-auto space-y-1 rounded-lg border bg-muted/20 p-2">
            {logs.slice(-15).map(log => (
              <div key={log.id} className="flex items-start gap-2 text-[11px]">
                <span className="text-muted-foreground shrink-0 w-14 font-mono">
                  {log.created_at ? new Date(log.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}
                </span>
                <span className={cn('shrink-0 w-12 uppercase font-medium', log.level === 'ERROR' ? 'text-red-500' : log.level === 'WARN' ? 'text-amber-500' : 'text-muted-foreground')}>
                  {log.step || log.level}
                </span>
                <span className="text-foreground">{log.message}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ================================================================
   BACKTESTING — MODEL COMPARISON TAB
   ================================================================ */
function BacktestModelsTab({ artifacts }: { artifacts: BacktestArtifacts }) {
  const models = artifacts.all_model_results
  const [sortCol, setSortCol] = useState<string>('score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const sorted = [...models].sort((a, b) => {
    const av = Number((a as Record<string, unknown>)[sortCol] ?? 0)
    const bv = Number((b as Record<string, unknown>)[sortCol] ?? 0)
    return sortDir === 'desc' ? bv - av : av - bv
  })

  const toggleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortCol(col); setSortDir('desc') }
  }

  const best = artifacts.metrics?.best_model as string | undefined

  const cols = [
    { key: 'model_name', label: 'Model', fmt: (v: unknown) => String(v) },
    { key: 'accuracy', label: 'Accuracy', fmt: (v: unknown) => v != null ? `${(Number(v) * 100).toFixed(1)}%` : '—' },
    { key: 'auc_roc', label: 'AUC-ROC', fmt: (v: unknown) => v != null ? Number(v).toFixed(4) : '—' },
    { key: 'f1_score', label: 'F1', fmt: (v: unknown) => v != null ? Number(v).toFixed(4) : '—' },
    { key: 'precision', label: 'Precision', fmt: (v: unknown) => v != null ? `${(Number(v) * 100).toFixed(1)}%` : '—' },
    { key: 'recall', label: 'Recall', fmt: (v: unknown) => v != null ? `${(Number(v) * 100).toFixed(1)}%` : '—' },
    { key: 'profit_factor', label: 'Profit Factor', fmt: (v: unknown) => v != null ? Number(v).toFixed(2) : '—' },
    { key: 'sharpe_ratio', label: 'Sharpe', fmt: (v: unknown) => v != null ? Number(v).toFixed(2) : '—' },
    { key: 'score', label: 'Score', fmt: (v: unknown) => v != null ? Number(v).toFixed(4) : '—' },
  ]

  if (models.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="p-8 text-center text-muted-foreground">
          <Brain className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No model results available yet.</p>
          <p className="text-xs mt-1">Model metrics appear once the training and evaluation steps complete.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-primary" />
          Model Comparison ({models.length} models)
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b">
                {cols.map(col => (
                  <th key={col.key} className="text-left p-2 font-medium text-muted-foreground cursor-pointer hover:text-foreground whitespace-nowrap" onClick={() => col.key !== 'model_name' && toggleSort(col.key)}>
                    {col.label}
                    {sortCol === col.key && <span className="ml-1">{sortDir === 'desc' ? '↓' : '↑'}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((m, i) => (
                <tr key={i} className={cn('border-b last:border-0 hover:bg-muted/30', m.model_name === best && 'bg-emerald-500/5')}>
                  {cols.map(col => (
                    <td key={col.key} className={cn('p-2 font-mono', col.key === 'model_name' && 'font-semibold')}>
                      <span className="flex items-center gap-1.5">
                        {col.key === 'model_name' && m.model_name === best && (
                          <span className="inline-flex items-center justify-center h-4 w-4 rounded-full bg-emerald-500 text-white text-[8px] font-bold shrink-0">1</span>
                        )}
                        {col.fmt((m as Record<string, unknown>)[col.key])}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

/* ================================================================
   BACKTESTING — FEATURES TAB
   ================================================================ */
function BacktestFeaturesTab({ artifacts }: { artifacts: BacktestArtifacts }) {
  const [search, setSearch] = useState('')
  const features = artifacts.feature_names
  const summary = artifacts.preprocessing_summary
  const filtered = search ? features.filter(f => f.toLowerCase().includes(search.toLowerCase())) : features

  const categories: Record<string, string[]> = {}
  for (const f of features) {
    let cat = 'Other'
    if (/^(close_|return_|gap_|range_|atr|high_|low_|fib_|dist_to_fib|hh_count|ll_count|inside_bar|is_doji|is_hammer|is_engulfing)/.test(f)) cat = 'Price Action'
    else if (/^(rsi|macd|bollinger|stoch|adx|cci|obv|williams|roc_|mfi|trix|keltner|donchian|ichimoku|parabolic|cmf|stoch_rsi)/.test(f)) cat = 'Technical Indicators'
    else if (/^(sma_|ema_|dist_to_sma|above_all_sma|golden_cross|death_cross)/.test(f)) cat = 'Moving Averages'
    else if (/^(volume|vol_|up_vol|vwap_|ad_line|force_index)/.test(f)) cat = 'Volume'
    else if (/^(spy_|qqq_|iwm_|dia_|vix_|sector_|tlt_|gld_|spy_corr)/.test(f)) cat = 'Market Context'
    else if (/^(hour|minute|day_|month|quarter|is_pre_market|is_first|is_last|is_power|is_opex|is_quad|days_to|nfp)/.test(f)) cat = 'Calendar'
    else if (/^(intraday_|price_vs_intraday)/.test(f)) cat = 'Intraday'
    else if (/^(analyst_|realized_vol|parkinson_vol|garman_klass|atr_percentile)/.test(f)) cat = 'Derived / Volatility'
    else if (/^(entry_price|target_price|stop_loss|exit_pct|weighted_exit|pnl_pct|hold_duration|strike)/.test(f)) cat = 'Trade Attributes'
    if (!categories[cat]) categories[cat] = []
    categories[cat].push(f)
  }

  return (
    <div className="space-y-4">
      {Object.keys(summary).length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Preprocessing Summary</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Total Rows', value: summary.total_rows ?? '—' },
                { label: 'Train', value: summary.train_rows ?? '—' },
                { label: 'Validation', value: summary.val_rows ?? '—' },
                { label: 'Test', value: summary.test_rows ?? '—' },
                { label: 'Tabular Features', value: summary.tabular_features ?? features.length },
                { label: 'Has Candles', value: summary.has_candles ? 'Yes' : 'No' },
                { label: 'Has Text Emb.', value: summary.has_text ? 'Yes' : 'No' },
                { label: 'Categoricals', value: summary.categorical_features ?? 0 },
              ].map(item => (
                <div key={item.label} className="rounded-lg border p-3">
                  <p className="text-[10px] text-muted-foreground uppercase">{item.label}</p>
                  <p className="text-lg font-bold font-mono mt-0.5">{String(item.value)}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm font-medium flex-1 flex items-center gap-2">
              <Columns3 className="h-4 w-4 text-primary" />
              Features ({features.length})
            </CardTitle>
            <Input placeholder="Search features..." value={search} onChange={e => setSearch(e.target.value)} className="w-56 h-8 text-xs" />
          </div>
        </CardHeader>
        <CardContent>
          {features.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Database className="h-8 w-8 mx-auto mb-3 opacity-50" />
              <p className="text-sm">No feature data available.</p>
              <p className="text-xs mt-1">Feature names are reported after the preprocessing step completes.</p>
            </div>
          ) : search ? (
            <div className="max-h-96 overflow-y-auto">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-1">
                {filtered.map((f, i) => (
                  <div key={i} className="px-2 py-1 rounded text-xs font-mono bg-muted/40 border border-border/50 truncate" title={f}>{f}</div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-2">{filtered.length} of {features.length} features match</p>
            </div>
          ) : (
            <div className="space-y-4">
              {Object.entries(categories).sort((a, b) => b[1].length - a[1].length).map(([cat, feats]) => (
                <div key={cat}>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">{cat} ({feats.length})</p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-1">
                    {feats.map((f, i) => (
                      <div key={i} className="px-2 py-1 rounded text-xs font-mono bg-muted/40 border border-border/50 truncate" title={f}>{f}</div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ================================================================
   BACKTESTING — DOWNLOADS TAB
   ================================================================ */
function BacktestDownloadsTab({ id, artifacts }: { id: string; artifacts: BacktestArtifacts }) {
  const files = artifacts.downloadable_files
  const baseUrl = api.defaults.baseURL || ''

  const getIcon = (name: string) => {
    if (name.endsWith('.json')) return <FileJson className="h-4 w-4 text-yellow-500" />
    if (name.endsWith('.parquet') || name.endsWith('.csv')) return <FileSpreadsheet className="h-4 w-4 text-green-500" />
    if (name.endsWith('.npy') || name.endsWith('.pkl')) return <Database className="h-4 w-4 text-blue-500" />
    return <FileDown className="h-4 w-4 text-muted-foreground" />
  }

  const parquetFiles = files.filter(f => f.name.endsWith('.parquet'))

  if (files.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="p-8 text-center text-muted-foreground">
          <Download className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No downloadable files available.</p>
          <p className="text-xs mt-1">Files become available after backtesting completes on this server.</p>
        </CardContent>
      </Card>
    )
  }

  const grouped: Record<string, typeof files> = {}
  for (const f of files) {
    const dir = f.name.includes('/') ? f.name.split('/')[0] : 'root'
    if (!grouped[dir]) grouped[dir] = []
    grouped[dir].push(f)
  }

  return (
    <div className="space-y-4">
      {parquetFiles.length > 0 && (
        <Card className="border-green-500/30 bg-green-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-green-500" />
              Download as CSV
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {parquetFiles.map(f => (
                <a
                  key={f.name}
                  href={`${baseUrl}/api/v2/agents/${id}/backtest-csv/${f.name}`}
                  download
                  className="inline-flex items-center gap-2 rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 hover:bg-green-500/20 transition-colors text-xs font-mono"
                >
                  <FileSpreadsheet className="h-3.5 w-3.5 text-green-500" />
                  {f.name.replace('.parquet', '.csv')}
                  <Download className="h-3 w-3 text-green-500" />
                </a>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Download className="h-4 w-4 text-primary" />
            All Backtesting Files ({files.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
        <div className="space-y-4">
          {Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([dir, dirFiles]) => (
            <div key={dir}>
              {dir !== 'root' && <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">{dir}/</p>}
              <div className="space-y-1">
                {dirFiles.map(f => (
                  <a
                    key={f.name}
                    href={`${baseUrl}/api/v2/agents/${id}/backtest-files/${f.name}`}
                    download
                    className="flex items-center gap-3 rounded-lg border p-2.5 hover:bg-muted/30 transition-colors group"
                  >
                    {getIcon(f.name)}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-mono truncate">{f.name.includes('/') ? f.name.split('/').slice(1).join('/') : f.name}</p>
                    </div>
                    <span className="text-[10px] text-muted-foreground">{f.size_human}</span>
                    <Download className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
    </div>
  )
}

/* ================================================================
   BACKTESTING SECTION (wraps all backtesting sub-tabs)
   ================================================================ */
function BacktestingSection({ id, status }: { id: string; status: string }) {
  const { data: artifacts } = useQuery<BacktestArtifacts>({
    queryKey: ['backtest-artifacts', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/backtest-artifacts`)).data } catch { return null } },
    refetchInterval: status === 'BACKTESTING' ? 5000 : 30000,
  })

  if (!artifacts) {
    return (
      <Card className="border-dashed">
        <CardContent className="p-12 text-center text-muted-foreground">
          <FlaskConical className="h-10 w-10 mx-auto mb-4 opacity-50" />
          <p className="text-sm font-medium">No backtesting data available</p>
          <p className="text-xs mt-1">Backtesting data appears once the pipeline starts running.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <BacktestPipelineProgress id={id} status={status} artifacts={artifacts} />

      {(artifacts.total_trades > 0 || artifacts.all_model_results.length > 0 || (artifacts.preprocessing_summary as Record<string, number>)?.total_rows > 0) && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          <MetricCard title="Total Trades" value={artifacts.total_trades || (artifacts.preprocessing_summary as Record<string, number>)?.total_rows || 0} />
          <MetricCard title="Win Rate" value={artifacts.win_rate != null ? `${(artifacts.win_rate * 100).toFixed(1)}%` : '—'} trend={artifacts.win_rate != null ? (artifacts.win_rate >= 0.5 ? 'up' : 'down') : undefined} />
          <MetricCard title="Sharpe Ratio" value={artifacts.sharpe_ratio?.toFixed(2) ?? '—'} trend={artifacts.sharpe_ratio != null ? (artifacts.sharpe_ratio >= 1 ? 'up' : 'neutral') : undefined} />
          <MetricCard title="Max Drawdown" value={artifacts.max_drawdown != null ? `${artifacts.max_drawdown.toFixed(1)}%` : '—'} />
          <MetricCard title="Total Return" value={artifacts.total_return != null ? `${artifacts.total_return.toFixed(1)}%` : '—'} trend={artifacts.total_return != null ? (artifacts.total_return >= 0 ? 'up' : 'down') : undefined} />
          {artifacts.all_model_results.length > 0 && (() => {
            const best = artifacts.all_model_results.reduce((a, b) => (a.auc_roc ?? 0) >= (b.auc_roc ?? 0) ? a : b)
            return <>
              <MetricCard title="Best Model" value={best.model_name} />
              <MetricCard title="AUC-ROC" value={best.auc_roc?.toFixed(3) ?? '—'} trend={(best.auc_roc ?? 0) >= 0.7 ? 'up' : 'neutral'} />
              <MetricCard title="Accuracy" value={best.accuracy != null ? `${(best.accuracy * 100).toFixed(1)}%` : '—'} trend={(best.accuracy ?? 0) >= 0.6 ? 'up' : 'neutral'} />
            </>
          })()}
        </div>
      )}

      <Tabs defaultValue="models">
        <TabsList className="grid w-full grid-cols-4 max-w-xl">
          <TabsTrigger value="models" className="text-xs"><BarChart3 className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Models</TabsTrigger>
          <TabsTrigger value="features" className="text-xs"><Columns3 className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Features</TabsTrigger>
          <TabsTrigger value="patterns" className="text-xs"><Brain className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Patterns</TabsTrigger>
          <TabsTrigger value="downloads" className="text-xs"><Download className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Downloads</TabsTrigger>
        </TabsList>

        <TabsContent value="models" className="mt-4">
          <BacktestModelsTab artifacts={artifacts} />
        </TabsContent>
        <TabsContent value="features" className="mt-4">
          <BacktestFeaturesTab artifacts={artifacts} />
        </TabsContent>
        <TabsContent value="patterns" className="mt-4">
          {artifacts.patterns.length > 0 ? (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Discovered Patterns ({artifacts.patterns.length})</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {artifacts.patterns.slice(0, 30).map((p, i) => (
                    <div key={i} className="rounded-lg border p-3">
                      <p className="text-sm font-medium">{String(p.name || p.pattern || `Pattern ${i + 1}`)}</p>
                      {p.description && <p className="text-xs text-muted-foreground mt-0.5">{String(p.description)}</p>}
                      {p.condition && <p className="text-xs font-mono text-muted-foreground mt-1">{String(p.condition)}</p>}
                      <div className="flex gap-3 mt-1.5 text-[10px] text-muted-foreground">
                        {p.support != null && <span>Support: {String(p.support)}</span>}
                        {p.confidence != null && <span>Confidence: {Number(p.confidence).toFixed(2)}</span>}
                        {p.lift != null && <span>Lift: {Number(p.lift).toFixed(2)}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card className="border-dashed">
              <CardContent className="p-8 text-center text-muted-foreground">
                <Brain className="h-8 w-8 mx-auto mb-3 opacity-50" />
                <p className="text-sm">No patterns discovered yet.</p>
              </CardContent>
            </Card>
          )}
        </TabsContent>
        <TabsContent value="downloads" className="mt-4">
          <BacktestDownloadsTab id={id} artifacts={artifacts} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

/* ================================================================
   LIVE SECTION (wraps all live sub-tabs)
   ================================================================ */
function LiveSection({ id, agent }: { id: string; agent: AgentData }) {
  return (
    <Tabs defaultValue="portfolio">
      <TabsList className="grid w-full grid-cols-6 max-w-2xl">
        <TabsTrigger value="portfolio" className="text-xs"><TrendingUp className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Portfolio</TabsTrigger>
        <TabsTrigger value="trades" className="text-xs"><List className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Trades</TabsTrigger>
        <TabsTrigger value="chat" className="text-xs"><MessageSquare className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Chat</TabsTrigger>
        <TabsTrigger value="intelligence" className="text-xs"><Shield className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Intel</TabsTrigger>
        <TabsTrigger value="logs" className="text-xs"><ScrollText className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Logs</TabsTrigger>
        <TabsTrigger value="rules" className="text-xs"><BookOpen className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Rules</TabsTrigger>
      </TabsList>

      <TabsContent value="portfolio" className="mt-4"><PortfolioTab id={id} agent={agent} /></TabsContent>
      <TabsContent value="trades" className="mt-4"><TradesTab id={id} /></TabsContent>
      <TabsContent value="chat" className="mt-4"><ChatTab id={id} agentName={agent.name} /></TabsContent>
      <TabsContent value="intelligence" className="mt-4"><IntelligenceTab id={id} /></TabsContent>
      <TabsContent value="logs" className="mt-4"><LogsTab id={id} /></TabsContent>
      <TabsContent value="rules" className="mt-4"><RulesTab id={id} /></TabsContent>
    </Tabs>
  )
}

/* ================================================================
   MAIN PAGE
   ================================================================ */
export default function AgentDashboardPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [topTab, setTopTab] = useState<string>('backtesting')

  useRealtimeQuery({
    channel: 'agent-status',
    queryKeys: [['agent', id ?? ''], ['agent-metrics', id ?? ''], ['positions', id ?? '']],
    enabled: !!id,
  })

  const { data: agent, isLoading } = useQuery<AgentData>({
    queryKey: ['agent', id],
    queryFn: async () => {
      try { return (await api.get(`/api/v2/agents/${id}`)).data }
      catch { return { id: id ?? '', name: 'Unknown Agent', type: 'trading', status: 'CREATED', config: {}, created_at: new Date().toISOString() } }
    },
    enabled: !!id,
  })

  const pauseMut = useMutation({
    mutationFn: () => api.post(`/api/v2/agents/${id}/pause`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['agent', id] }); toast.success('Agent paused') },
  })
  const resumeMut = useMutation({
    mutationFn: () => api.post(`/api/v2/agents/${id}/resume`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['agent', id] }); toast.success('Agent resumed') },
  })
  const modeMut = useMutation({
    mutationFn: (mode: string) => api.post(`/api/v2/agents/${id}/command`, { action: 'switch_mode', mode }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['agent', id] }); toast.success('Mode switched') },
  })

  useEffect(() => {
    if (agent) {
      if (LIVE.has(agent.status) || agent.status === 'PAUSED') setTopTab('live')
      else setTopTab('backtesting')
    }
  }, [agent?.status])

  if (isLoading || !agent) {
    return <div className="space-y-4"><div className="h-10 w-48 bg-muted animate-pulse rounded" /><div className="h-64 bg-muted animate-pulse rounded" /></div>
  }

  const isLive = LIVE.has(agent.status)
  const mode = agent.current_mode ?? 'conservative'

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <Button variant="ghost" size="icon" onClick={() => navigate('/agents')} className="shrink-0"><ArrowLeft className="h-4 w-4" /></Button>
          <Bot className="h-6 w-6 text-primary shrink-0" />
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-bold truncate">{agent.name}</h1>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              <Badge variant="outline" className="text-xs">{agent.type}</Badge>
              <StatusBadge status={agent.status} />
              {agent.channel_name && <span className="text-xs text-muted-foreground">#{agent.channel_name}</span>}
              {agent.analyst_name && <span className="text-xs text-muted-foreground">by {agent.analyst_name}</span>}
            </div>
          </div>
        </div>

        <div className="flex gap-2 flex-wrap items-center">
          <Select value={mode} onValueChange={m => modeMut.mutate(m)}>
            <SelectTrigger className={cn('w-36 h-8 text-xs font-semibold', mode === 'aggressive' ? 'border-red-500/50 text-red-500' : 'border-emerald-500/50 text-emerald-500')}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="aggressive">Aggressive</SelectItem>
              <SelectItem value="conservative">Conservative</SelectItem>
            </SelectContent>
          </Select>
          {isLive ? (
            <Button variant="outline" size="sm" onClick={() => pauseMut.mutate()} disabled={pauseMut.isPending}><Pause className="h-4 w-4 mr-1" />Pause</Button>
          ) : agent.status === 'PAUSED' ? (
            <Button size="sm" onClick={() => resumeMut.mutate()} disabled={resumeMut.isPending}><Play className="h-4 w-4 mr-1" />Resume</Button>
          ) : null}
        </div>
      </div>

      {/* Metrics bar */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        <MetricCard title="Total P&L" value={`$${(agent.total_pnl ?? 0).toLocaleString()}`} trend={(agent.total_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        <MetricCard title="Win Rate" value={`${((agent.win_rate ?? 0) * 100).toFixed(1)}%`} />
        <MetricCard title="Trades" value={agent.total_trades ?? 0} />
        <MetricCard title="Confidence" value={agent.model_accuracy ? `${(agent.model_accuracy * 100).toFixed(0)}%` : '—'} />
        <MetricCard title="Today P&L" value={`$${(agent.daily_pnl ?? 0).toLocaleString()}`} trend={(agent.daily_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        <MetricCard title="Heartbeat" value={agent.last_signal_at ? `${Math.round((Date.now() - new Date(agent.last_signal_at).getTime()) / 60000)}m` : '—'} />
      </div>

      {/* Top-level Live / Backtesting toggle */}
      <div className="flex items-center gap-1 border-b pb-0">
        <button
          className={cn(
            'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px',
            topTab === 'live' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
          onClick={() => setTopTab('live')}
        >
          <Zap className="h-4 w-4" />
          Live
        </button>
        <button
          className={cn(
            'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px',
            topTab === 'backtesting' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
          onClick={() => setTopTab('backtesting')}
        >
          <FlaskConical className="h-4 w-4" />
          Backtesting
        </button>
      </div>

      {/* Section content */}
      {topTab === 'live' && <LiveSection id={id!} agent={agent} />}
      {topTab === 'backtesting' && <BacktestingSection id={id!} status={agent.status} />}
    </div>
  )
}
