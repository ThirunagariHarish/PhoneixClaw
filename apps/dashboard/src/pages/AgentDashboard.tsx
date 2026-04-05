/**
 * AgentDashboard — Mission Control for a single agent.
 * Route: /agents/:id
 *
 * Tabs: Portfolio | Trades | Chat | Intelligence | Logs | Rules
 */
import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { MetricCard } from '@/components/ui/MetricCard'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AreaChart } from '@/components/tremor/AreaChart'
import {
  ArrowLeft, Bot, Pause, Play, Send, MessageSquare, User,
  Shield, Settings, TrendingUp, List, ScrollText, BookOpen,
  ChevronDown, ChevronUp, Check, X, AlertTriangle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

/* ---------- Types ---------- */

interface AgentData {
  id: string; name: string; type: string; status: string
  instance_id: string | null; config: Record<string, unknown>
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
    <TabsContent value="portfolio" className="space-y-4 mt-4">
      {/* Account summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
        <MetricCard title="Total P&L" value={`$${(agent.total_pnl ?? 0).toLocaleString()}`} trend={(agent.total_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        <MetricCard title="Today P&L" value={`$${(agent.daily_pnl ?? 0).toLocaleString()}`} trend={(agent.daily_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        <MetricCard title="Open Positions" value={positions.length} />
        <MetricCard title="Win Rate" value={`${((agent.win_rate ?? 0) * 100).toFixed(1)}%`} />
      </div>

      {/* Equity curve */}
      {pnlCurve.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Cumulative P&L</CardTitle></CardHeader>
          <CardContent>
            <AreaChart data={pnlCurve as Record<string, unknown>[]} index="date" categories={['pnl']} colors={['hsl(var(--chart-1))']} showLegend={false} valueFormatter={(v) => `$${v.toLocaleString()}`} className="h-48 sm:h-64" />
          </CardContent>
        </Card>
      )}

      {/* Open positions */}
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
    </TabsContent>
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
    <TabsContent value="trades" className="space-y-4 mt-4">
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
    </TabsContent>
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
    <TabsContent value="chat" className="mt-4">
      <Card className="flex flex-col" style={{ height: 'calc(100vh - 320px)', minHeight: '400px' }}>
        <CardHeader className="pb-2 shrink-0">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-primary" />
            Chat with {agentName}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col overflow-hidden p-4 pt-0">
          {/* Quick commands */}
          <div className="flex gap-1.5 mb-3 flex-wrap shrink-0">
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'switch_mode', mode: 'aggressive' })}>Aggressive</Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'switch_mode', mode: 'conservative' })}>Conservative</Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'pause' })}>Pause</Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={() => cmdMut.mutate({ action: 'resume' })}>Resume</Button>
          </div>

          {/* Messages */}
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
                  {msg.message_type === 'tool_trace' && (
                    <div className="mb-1 px-2 py-1 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400 text-[10px] font-mono">Tool: {(msg.metadata as Record<string, unknown>)?.tool_name as string ?? 'unknown'}</div>
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

          {/* Input */}
          <div className="flex gap-2 shrink-0">
            <Input value={message} onChange={e => setMessage(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }} placeholder={`Message ${agentName}...`} disabled={sendMut.isPending} className="flex-1" />
            <Button size="icon" onClick={handleSend} disabled={!message.trim() || sendMut.isPending}><Send className="h-4 w-4" /></Button>
          </div>
        </CardContent>
      </Card>
    </TabsContent>
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
    <TabsContent value="intelligence" className="space-y-4 mt-4">
      {/* Model info */}
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

      {/* Analyst profile */}
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

      {/* Rules */}
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

      {/* Top features */}
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
    </TabsContent>
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
    <TabsContent value="logs" className="space-y-4 mt-4">
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
    </TabsContent>
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

  const toggleRule = (idx: number) => {
    const r = [...(editRules ?? rules)]
    r[idx] = { ...r[idx], enabled: !r[idx].enabled }
    setEditRules(r)
  }

  const deleteRule = (idx: number) => {
    const r = [...(editRules ?? rules)]
    r.splice(idx, 1)
    setEditRules(r)
  }

  const addRule = () => {
    if (!newRule.name || !newRule.condition) return
    setEditRules([...(editRules ?? rules), { ...newRule }])
    setNewRule({ name: '', condition: '', weight: 0, source: 'user', enabled: true, description: '' })
    setShowAddRule(false)
  }

  return (
    <TabsContent value="rules" className="space-y-4 mt-4">
      {/* Rules table */}
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

      {/* Risk config */}
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

      {/* Mode settings */}
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
    </TabsContent>
  )
}

/* ================================================================
   MAIN PAGE
   ================================================================ */
export default function AgentDashboardPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: agent, isLoading } = useQuery<AgentData>({
    queryKey: ['agent', id],
    queryFn: async () => {
      try { return (await api.get(`/api/v2/agents/${id}`)).data }
      catch { return { id: id ?? '', name: 'Unknown Agent', type: 'trading', status: 'CREATED', instance_id: null, config: {}, created_at: new Date().toISOString() } }
    },
    enabled: !!id,
  })

  const { data: metrics } = useQuery<Record<string, unknown>>({
    queryKey: ['agent-metrics', id],
    queryFn: async () => { try { return (await api.get(`/api/v2/agents/${id}/metrics`)).data } catch { return {} } },
    enabled: !!id,
    refetchInterval: 15000,
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

      {/* Tabs */}
      <Tabs defaultValue="portfolio">
        <TabsList className="grid w-full grid-cols-6 max-w-2xl">
          <TabsTrigger value="portfolio" className="text-xs"><TrendingUp className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Portfolio</TabsTrigger>
          <TabsTrigger value="trades" className="text-xs"><List className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Trades</TabsTrigger>
          <TabsTrigger value="chat" className="text-xs"><MessageSquare className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Chat</TabsTrigger>
          <TabsTrigger value="intelligence" className="text-xs"><Shield className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Intel</TabsTrigger>
          <TabsTrigger value="logs" className="text-xs"><ScrollText className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Logs</TabsTrigger>
          <TabsTrigger value="rules" className="text-xs"><BookOpen className="h-3.5 w-3.5 mr-1 hidden sm:inline" />Rules</TabsTrigger>
        </TabsList>

        <PortfolioTab id={id!} agent={agent} />
        <TradesTab id={id!} />
        <ChatTab id={id!} agentName={agent.name} />
        <IntelligenceTab id={id!} />
        <LogsTab id={id!} />
        <RulesTab id={id!} />
      </Tabs>
    </div>
  )
}
