import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Send, Loader2, Bot, User, Sparkles, Rocket, Trash2,
  ChevronRight, CheckCircle2, AlertCircle, Brain, TrendingUp, Code,
  FlaskConical, Settings2, ShieldCheck, XCircle, Zap, BarChart3,
  RefreshCw, MessageSquarePlus, ArrowLeft, Activity, Target,
  Calendar, DollarSign, Percent, TrendingDown, Signal, Database,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip as RTooltip,
  CartesianGrid,
} from 'recharts'

interface Strategy {
  id: string
  name: string
  strategy_text: string
  parsed_config: Record<string, unknown>
  backtest_summary: Record<string, unknown> | null
  status: string
  created_at: string
  updated_at: string
}

interface AgentStep {
  type: 'thinking' | 'action' | 'response' | 'error' | 'approval_required' | 'done'
  content?: string
  tool?: string
  status?: string
  result?: Record<string, unknown>
  error?: string
  params?: Record<string, unknown>
  iteration?: number
  message?: string
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  steps?: AgentStep[]
  timestamp: string
  isStreaming?: boolean
}

const SUGGESTIONS = [
  'Create a momentum strategy for AAPL that buys on bullish sentiment',
  'Build a mean reversion strategy for SPY with tight stop losses',
  'Design a strategy that trades options based on Discord sentiment signals',
  'Backtest a simple SMA crossover strategy on TSLA for the last 2 years',
  'Create an aggressive options strategy for NVDA earnings plays',
]

const TOOL_ICONS: Record<string, typeof Brain> = {
  create_strategy: Sparkles,
  parse_strategy: Code,
  backtest: FlaskConical,
  modify_strategy: Settings2,
  analyze_sentiment: TrendingUp,
  fetch_market_data: BarChart3,
  analyze_portfolio: TrendingUp,
  deploy: Rocket,
}

const STATUS_COLORS: Record<string, { dot: string; badge: string }> = {
  draft: { dot: 'bg-gray-400', badge: 'bg-gray-500/10 text-gray-600 border-gray-300' },
  backtested: { dot: 'bg-blue-500', badge: 'bg-blue-500/10 text-blue-600 border-blue-300' },
  backtesting: { dot: 'bg-amber-500 animate-pulse', badge: 'bg-amber-500/10 text-amber-600 border-amber-300' },
  deployed: { dot: 'bg-green-500', badge: 'bg-green-500/10 text-green-600 border-green-300' },
  ready: { dot: 'bg-emerald-500', badge: 'bg-emerald-500/10 text-emerald-600 border-emerald-300' },
  failed: { dot: 'bg-red-500', badge: 'bg-red-500/10 text-red-600 border-red-300' },
}

function extractTicker(strategy: Strategy): string | null {
  const config = strategy.parsed_config as Record<string, unknown>
  if (config?.ticker) return String(config.ticker)
  const match = strategy.strategy_text?.match(/\b([A-Z]{1,5})\b/)
  return match?.[1] || null
}

export default function StrategyBuilder() {
  const qc = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [activeStrategyId, setActiveStrategyId] = useState<string | null>(null)
  const [view, setView] = useState<'chat' | 'dashboard'>('chat')
  const [isStreaming, setIsStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const { data: strategies, isLoading: strategiesLoading } = useQuery<Strategy[]>({
    queryKey: ['strategies'],
    queryFn: () => axios.get('/api/v1/strategies').then(r => r.data),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => axios.delete(`/api/v1/strategies/${id}`),
    onSuccess: (_, deletedId) => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
      if (activeStrategyId === deletedId) {
        setActiveStrategyId(null)
        setView('chat')
      }
    },
  })

  const deployAsSourceMutation = useMutation({
    mutationFn: (id: string) =>
      axios.post(`/api/v1/strategies/${id}/deploy-as-source`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
      qc.invalidateQueries({ queryKey: ['sources'] })
    },
  })

  const approveMutation = useMutation({
    mutationFn: (data: { strategy_id: string; approved: boolean }) =>
      axios.post('/api/v1/strategies/agent/approve', data).then(r => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['strategies'] })
      const msg: ChatMessage = {
        role: 'assistant',
        content: data.message || (data.status === 'approved' ? 'Strategy deployed successfully!' : 'Deployment cancelled.'),
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, msg])
    },
  })

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const sendStreamingMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return

    setView('chat')

    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setIsStreaming(true)

    const assistantMsg: ChatMessage = {
      role: 'assistant',
      content: '',
      steps: [],
      timestamp: new Date().toISOString(),
      isStreaming: true,
    }
    setMessages(prev => [...prev, assistantMsg])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await fetch('/api/v1/strategies/agent/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
        },
        body: JSON.stringify({
          message: text,
          conversation_history: messages.slice(-10).map(m => ({
            role: m.role,
            content: m.content,
          })),
          strategy_context: activeStrategyId ? { active_strategy_id: activeStrategyId } : undefined,
        }),
        signal: controller.signal,
      })

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6).trim()
          if (!jsonStr) continue

          try {
            const step: AgentStep = JSON.parse(jsonStr)

            if (step.type === 'done') {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: step.message || last.content,
                    isStreaming: false,
                  }
                }
                return updated
              })
              setTimeout(() => qc.invalidateQueries({ queryKey: ['strategies'] }), 600)
            } else {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last?.role === 'assistant') {
                  const newSteps = [...(last.steps || []), step]
                  let content = last.content
                  if (step.type === 'response') {
                    content = step.content || content
                  }
                  updated[updated.length - 1] = { ...last, steps: newSteps, content }
                }
                return updated
              })
            }
          } catch {
            // skip malformed events
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return

      const fallbackResp = await axios.post('/api/v1/strategies/agent/chat', {
        message: text,
        conversation_history: messages.slice(-10).map(m => ({ role: m.role, content: m.content })),
        strategy_context: activeStrategyId ? { active_strategy_id: activeStrategyId } : undefined,
      }).then(r => r.data).catch(() => ({
        message: 'The agent is temporarily unavailable. Please try again in a moment.',
        steps: [],
      }))

      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          role: 'assistant',
          content: fallbackResp.message || '',
          steps: fallbackResp.steps || [],
          timestamp: new Date().toISOString(),
        }
        return updated
      })
      qc.invalidateQueries({ queryKey: ['strategies'] })
    } finally {
      setIsStreaming(false)
      abortRef.current = null
      setTimeout(() => qc.invalidateQueries({ queryKey: ['strategies'] }), 800)
    }
  }, [messages, activeStrategyId, isStreaming, qc])

  const handleSend = (text?: string) => {
    const msg = text || input.trim()
    if (!msg) return
    sendStreamingMessage(msg)
  }

  const selectStrategy = (id: string) => {
    setActiveStrategyId(id)
    setView('dashboard')
  }

  const goToChat = () => {
    setView('chat')
  }

  const selectedStrategy = strategies?.find(s => s.id === activeStrategyId)
  const report = selectedStrategy?.backtest_summary as Record<string, unknown> | undefined

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* ─── Left sidebar ─── */}
      <div className="w-72 border-r flex flex-col bg-muted/20">
        <div className="p-3 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center">
                <Brain className="h-3.5 w-3.5 text-white" />
              </div>
              <div>
                <h3 className="text-sm font-semibold leading-none">Strategies</h3>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  {strategies?.length || 0} total
                </p>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => { setActiveStrategyId(null); setView('chat'); setMessages([]) }}
              title="New chat"
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {strategiesLoading ? (
              Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)
            ) : !strategies?.length ? (
              <div className="text-center py-10 px-4">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500/10 to-blue-500/10 mb-3">
                  <Sparkles className="h-5 w-5 text-purple-400" />
                </div>
                <p className="text-xs font-medium mb-1">No strategies yet</p>
                <p className="text-[10px] text-muted-foreground leading-relaxed">
                  Chat with the AI agent to create your first trading strategy
                </p>
              </div>
            ) : (
              strategies.map(s => {
                const ticker = extractTicker(s)
                const colors = STATUS_COLORS[s.status] || STATUS_COLORS.draft
                const metrics = (s.backtest_summary as Record<string, unknown>)?.metrics as Record<string, number> | undefined
                const returnPct = metrics?.total_return_pct
                const isActive = activeStrategyId === s.id

                return (
                  <div
                    key={s.id}
                    className={`group rounded-lg border p-2.5 cursor-pointer transition-all ${
                      isActive
                        ? 'border-purple-500/60 bg-purple-500/5 shadow-sm ring-1 ring-purple-500/20'
                        : 'hover:border-muted-foreground/30 hover:bg-muted/30'
                    }`}
                    onClick={() => selectStrategy(s.id)}
                  >
                    <div className="flex items-start gap-2">
                      <div className={`h-2 w-2 rounded-full mt-1.5 shrink-0 ${colors.dot}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-xs font-medium truncate">{s.name}</p>
                          {ticker && (
                            <Badge variant="secondary" className="text-[8px] px-1 py-0 shrink-0 font-mono">
                              {ticker}
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <Badge variant="outline" className={`text-[8px] px-1.5 py-0 ${colors.badge}`}>
                            {s.status}
                          </Badge>
                          {returnPct !== undefined && (
                            <span className={`text-[10px] font-semibold ${returnPct >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                              {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(1)}%
                            </span>
                          )}
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-5 w-5 text-destructive opacity-0 group-hover:opacity-100 shrink-0"
                        onClick={e => { e.stopPropagation(); deleteMutation.mutate(s.id) }}
                      >
                        <Trash2 className="h-2.5 w-2.5" />
                      </Button>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </ScrollArea>
      </div>

      {/* ─── Main content area ─── */}
      {view === 'dashboard' && selectedStrategy ? (
        <StrategyDashboard
          strategy={selectedStrategy}
          report={report}
          onBack={goToChat}
          onDelete={() => deleteMutation.mutate(selectedStrategy.id)}
          onDeployAsSource={() => deployAsSourceMutation.mutate(selectedStrategy.id)}
          deployLoading={deployAsSourceMutation.isPending}
          onBacktest={() => handleSend(`Backtest the strategy "${selectedStrategy.name}"`)}
        />
      ) : (
        <div className="flex-1 flex flex-col">
          {/* Active strategy context chip */}
          {activeStrategyId && selectedStrategy && (
            <div className="border-b bg-purple-500/5 px-4 py-1.5">
              <div className="max-w-3xl mx-auto flex items-center gap-2">
                <Target className="h-3 w-3 text-purple-500" />
                <span className="text-[11px] text-muted-foreground">
                  Context: <span className="font-medium text-foreground">{selectedStrategy.name}</span>
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-4 w-4 ml-1"
                  onClick={() => setActiveStrategyId(null)}
                >
                  <XCircle className="h-3 w-3" />
                </Button>
              </div>
            </div>
          )}

          <div className="flex-1 overflow-auto" ref={scrollRef}>
            <div className="max-w-3xl mx-auto p-4 space-y-4">
              {messages.length === 0 && (
                <div className="text-center py-16">
                  <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500/20 to-blue-500/20 mb-4">
                    <Sparkles className="h-8 w-8 text-purple-500" />
                  </div>
                  <h2 className="text-xl font-bold mb-1">Strategy Agent</h2>
                  <p className="text-sm text-muted-foreground mb-2 max-w-md mx-auto">
                    I'm your autonomous trading strategy agent. Tell me what you want to build
                    and I'll create, backtest, and deploy strategies for you.
                  </p>
                  <div className="flex items-center justify-center gap-1.5 text-[10px] text-muted-foreground mb-6">
                    <Zap className="h-3 w-3 text-purple-400" />
                    <span>Powered by ReAct agent loop with real-time streaming</span>
                  </div>
                  <div className="grid gap-2 max-w-lg mx-auto">
                    {SUGGESTIONS.map((s, i) => (
                      <button
                        key={i}
                        className="text-left text-xs p-3 rounded-lg border hover:border-purple-500/40 hover:bg-purple-500/5 transition-colors"
                        onClick={() => handleSend(s)}
                      >
                        <ChevronRight className="h-3 w-3 inline mr-1.5 text-purple-500" />
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg, idx) => (
                <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                  {msg.role === 'assistant' && (
                    <div className="shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center">
                      <Bot className="h-3.5 w-3.5 text-white" />
                    </div>
                  )}
                  <div className={`max-w-[85%] space-y-2 ${msg.role === 'user' ? 'items-end' : ''}`}>
                    {msg.role === 'user' ? (
                      <div className="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-2.5">
                        <p className="text-sm">{msg.content}</p>
                      </div>
                    ) : (
                      <>
                        {msg.steps?.filter(s => s.type !== 'response' && s.type !== 'done').map((step, si) => (
                          <AgentStepCard
                            key={si}
                            step={step}
                            onApprove={step.type === 'approval_required' && step.params?.strategy_id
                              ? (approved) => approveMutation.mutate({
                                  strategy_id: step.params!.strategy_id as string,
                                  approved,
                                })
                              : undefined
                            }
                          />
                        ))}
                        {msg.content && (
                          <div className="bg-muted/50 rounded-2xl rounded-tl-sm px-4 py-2.5">
                            <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                          </div>
                        )}
                        {msg.isStreaming && !msg.content && (
                          <div className="bg-muted/50 rounded-2xl rounded-tl-sm px-4 py-3">
                            <div className="flex items-center gap-2">
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-purple-500" />
                              <span className="text-xs text-muted-foreground">Agent is thinking...</span>
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <div className="shrink-0 w-7 h-7 rounded-full bg-muted flex items-center justify-center">
                      <User className="h-3.5 w-3.5" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Input */}
          <div className="border-t bg-background p-4">
            <div className="max-w-3xl mx-auto">
              <div className="flex gap-2">
                <Input
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
                  placeholder="Tell the agent what to do... e.g. 'Create a momentum strategy for TSLA'"
                  className="flex-1"
                  disabled={isStreaming}
                />
                <Button
                  onClick={() => handleSend()}
                  disabled={!input.trim() || isStreaming}
                  className="gap-1.5"
                >
                  {isStreaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


// ─── Strategy Dashboard ──────────────────────────────────────────────────────

function StrategyDashboard({
  strategy,
  report,
  onBack,
  onDelete,
  onDeployAsSource,
  deployLoading,
  onBacktest,
}: {
  strategy: Strategy
  report?: Record<string, unknown>
  onBack: () => void
  onDelete: () => void
  onDeployAsSource: () => void
  deployLoading: boolean
  onBacktest: () => void
}) {
  const metrics = report?.metrics as Record<string, number> | undefined
  const equityCurve = (report?.equity_curve as number[])?.map((v, i) => ({ day: i, value: v })) || []
  const ticker = extractTicker(strategy)
  const colors = STATUS_COLORS[strategy.status] || STATUS_COLORS.draft
  const narrative = report?.narrative as string | undefined
  const pseudocode = report?.pseudocode as string | undefined
  const parsedConfig = strategy.parsed_config as Record<string, unknown>

  const metricCards = [
    {
      label: 'Total Return',
      value: metrics?.total_return_pct !== undefined ? `${metrics.total_return_pct >= 0 ? '+' : ''}${metrics.total_return_pct.toFixed(1)}%` : '--',
      icon: TrendingUp,
      color: (metrics?.total_return_pct ?? 0) >= 0 ? 'text-green-600' : 'text-red-500',
    },
    {
      label: 'Sharpe Ratio',
      value: metrics?.sharpe_ratio?.toFixed(2) || '--',
      icon: Activity,
      color: (metrics?.sharpe_ratio ?? 0) >= 1 ? 'text-green-600' : 'text-amber-500',
    },
    {
      label: 'Max Drawdown',
      value: metrics?.max_drawdown_pct !== undefined ? `${metrics.max_drawdown_pct.toFixed(1)}%` : '--',
      icon: TrendingDown,
      color: 'text-red-500',
    },
    {
      label: 'Win Rate',
      value: metrics?.win_rate !== undefined ? `${(metrics.win_rate * 100).toFixed(0)}%` : '--',
      icon: Target,
      color: (metrics?.win_rate ?? 0) >= 0.5 ? 'text-green-600' : 'text-amber-500',
    },
    {
      label: 'Total Trades',
      value: metrics?.total_trades?.toString() || '--',
      icon: BarChart3,
      color: 'text-blue-500',
    },
    {
      label: 'P&L',
      value: metrics?.total_pnl !== undefined ? `$${metrics.total_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '--',
      icon: DollarSign,
      color: (metrics?.total_pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-500',
    },
  ]

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b bg-background px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onBack}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold">{strategy.name}</h2>
                {ticker && (
                  <Badge variant="secondary" className="font-mono text-xs">{ticker}</Badge>
                )}
                <Badge variant="outline" className={`text-[10px] ${colors.badge}`}>
                  <span className={`inline-block h-1.5 w-1.5 rounded-full mr-1.5 ${colors.dot}`} />
                  {strategy.status}
                </Badge>
              </div>
              <div className="flex items-center gap-3 mt-0.5">
                <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {strategy.created_at ? new Date(strategy.created_at).toLocaleDateString() : 'Unknown'}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {!report && (
              <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={onBacktest}>
                <FlaskConical className="h-3.5 w-3.5" /> Backtest
              </Button>
            )}
            {report && strategy.status !== 'deployed' && (
              <Button
                size="sm"
                variant="default"
                className="gap-1.5 text-xs bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700"
                onClick={onDeployAsSource}
                disabled={deployLoading}
              >
                {deployLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Signal className="h-3.5 w-3.5" />}
                Deploy as Signal Source
              </Button>
            )}
            {strategy.status === 'deployed' && (
              <Badge className="bg-green-500/10 text-green-600 border-green-300 gap-1.5 px-3 py-1.5">
                <Database className="h-3 w-3" /> Live Data Source
              </Badge>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="text-destructive text-xs"
              onClick={onDelete}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {/* Dashboard content */}
      <ScrollArea className="flex-1">
        <div className="p-6 space-y-6 max-w-6xl mx-auto">
          {/* AI Analysis */}
          {narrative && (
            <Card className="border-purple-500/20 bg-gradient-to-r from-purple-500/5 to-blue-500/5">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="h-8 w-8 rounded-lg bg-purple-500/10 flex items-center justify-center shrink-0">
                    <Brain className="h-4 w-4 text-purple-500" />
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-purple-500 mb-1">AI Analysis</p>
                    <p className="text-sm leading-relaxed">{narrative}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Metrics row */}
          {metrics && (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {metricCards.map(m => (
                <Card key={m.label} className="hover:shadow-sm transition-shadow">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <m.icon className={`h-3.5 w-3.5 ${m.color}`} />
                      <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{m.label}</p>
                    </div>
                    <p className={`text-lg font-bold ${m.color}`}>{m.value}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* Equity curve */}
          {equityCurve.length > 0 && (
            <Card>
              <CardHeader className="pb-2 px-4 pt-4">
                <CardTitle className="text-sm font-semibold">Equity Curve</CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={equityCurve}>
                      <defs>
                        <linearGradient id="eqGradDash" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#a855f7" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                      <XAxis dataKey="day" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
                      <YAxis
                        domain={['auto', 'auto']}
                        tick={{ fontSize: 10 }}
                        stroke="hsl(var(--muted-foreground))"
                        tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
                      />
                      <RTooltip
                        formatter={(v: number) => [`$${v.toLocaleString()}`, 'Portfolio']}
                        contentStyle={{ fontSize: 12, borderRadius: 8 }}
                      />
                      <Area
                        type="monotone"
                        dataKey="value"
                        stroke="#a855f7"
                        fill="url(#eqGradDash)"
                        strokeWidth={2}
                        dot={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Two-column bottom: Logic + Data */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Strategy Logic */}
            <Card>
              <CardHeader className="pb-2 px-4 pt-4">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Code className="h-4 w-4 text-purple-500" />
                  Strategy Logic
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4 space-y-3">
                {pseudocode && (
                  <pre className="text-[11px] font-mono bg-muted p-3 rounded-lg overflow-auto max-h-52 whitespace-pre-wrap leading-relaxed">
                    {pseudocode}
                  </pre>
                )}
                {!pseudocode && strategy.strategy_text && (
                  <p className="text-sm text-muted-foreground leading-relaxed">{strategy.strategy_text}</p>
                )}
                {parsedConfig && Object.keys(parsedConfig).length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-[10px] font-semibold uppercase text-muted-foreground">Parsed Config</p>
                    {Object.entries(parsedConfig).map(([k, v]) => (
                      <div key={k} className="flex items-center justify-between text-xs bg-muted/50 rounded px-2.5 py-1.5">
                        <span className="text-muted-foreground">{k.replace(/_/g, ' ')}</span>
                        <span className="font-medium font-mono">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                      </div>
                    ))}
                  </div>
                )}
                {!pseudocode && !strategy.strategy_text && Object.keys(parsedConfig || {}).length === 0 && (
                  <p className="text-xs text-muted-foreground italic">No strategy logic parsed yet. Run a backtest to generate.</p>
                )}
              </CardContent>
            </Card>

            {/* Strategy Data / Monitoring */}
            <Card>
              <CardHeader className="pb-2 px-4 pt-4">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Database className="h-4 w-4 text-blue-500" />
                  Data &amp; Signals
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4 space-y-3">
                {ticker && (
                  <div className="flex items-center justify-between text-xs bg-muted/50 rounded px-2.5 py-2">
                    <span className="text-muted-foreground flex items-center gap-1.5">
                      <BarChart3 className="h-3 w-3" /> Ticker
                    </span>
                    <span className="font-bold font-mono">{ticker}</span>
                  </div>
                )}
                <div className="flex items-center justify-between text-xs bg-muted/50 rounded px-2.5 py-2">
                  <span className="text-muted-foreground flex items-center gap-1.5">
                    <Signal className="h-3 w-3" /> Status
                  </span>
                  <Badge variant="outline" className={`text-[9px] ${colors.badge}`}>{strategy.status}</Badge>
                </div>
                {report && (
                  <>
                    <div className="flex items-center justify-between text-xs bg-muted/50 rounded px-2.5 py-2">
                      <span className="text-muted-foreground flex items-center gap-1.5">
                        <Percent className="h-3 w-3" /> Benchmark
                      </span>
                      <span className="font-medium">
                        {(report.benchmark as Record<string, number>)?.total_return_pct !== undefined
                          ? `${((report.benchmark as Record<string, number>).total_return_pct).toFixed(1)}%`
                          : 'N/A'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs bg-muted/50 rounded px-2.5 py-2">
                      <span className="text-muted-foreground flex items-center gap-1.5">
                        <Calendar className="h-3 w-3" /> Period
                      </span>
                      <span className="font-medium">
                        {(report.period as string) || '2 years'}
                      </span>
                    </div>
                  </>
                )}

                {strategy.status === 'deployed' && (
                  <div className="mt-2 rounded-lg border border-green-500/30 bg-green-500/5 p-3">
                    <div className="flex items-center gap-2 mb-1">
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                      <span className="text-xs font-semibold text-green-600">Live Signal Source</span>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      This strategy is deployed as a data source and will generate trade signals
                      when conditions are met.
                    </p>
                  </div>
                )}

                {strategy.status !== 'deployed' && report && (
                  <div className="mt-2 rounded-lg border border-dashed border-muted-foreground/30 p-3">
                    <p className="text-[10px] text-muted-foreground text-center">
                      Deploy this strategy as a signal source to start generating live trade signals.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}


// ─── Agent Step Card ─────────────────────────────────────────────────────────

function AgentStepCard({
  step,
  onApprove,
}: {
  step: AgentStep
  onApprove?: (approved: boolean) => void
}) {
  if (step.type === 'thinking') {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-[11px] text-muted-foreground animate-in fade-in slide-in-from-left-2 duration-300">
        <Brain className="h-3 w-3 text-purple-400 animate-pulse" />
        <span className="italic">{step.content}</span>
        {step.iteration && (
          <Badge variant="outline" className="text-[7px] px-1 ml-auto">
            step {step.iteration}
          </Badge>
        )}
      </div>
    )
  }

  if (step.type === 'action') {
    const isSuccess = step.status === 'success'
    const Icon = (step.tool && TOOL_ICONS[step.tool]) || Zap
    return (
      <div className={`rounded-lg border px-3 py-2 animate-in fade-in slide-in-from-left-2 duration-300 ${
        isSuccess ? 'border-green-500/30 bg-green-500/5' : 'border-red-500/30 bg-red-500/5'
      }`}>
        <div className="flex items-center gap-2">
          {isSuccess ? (
            <CheckCircle2 className="h-3 w-3 text-green-500" />
          ) : (
            <AlertCircle className="h-3 w-3 text-red-500" />
          )}
          <Icon className="h-3 w-3 text-muted-foreground" />
          <span className="text-[11px] font-medium">{step.tool?.replace(/_/g, ' ')}</span>
          <Badge variant="outline" className="text-[8px]">{step.status}</Badge>
          {step.iteration && (
            <Badge variant="outline" className="text-[7px] px-1 ml-auto">
              step {step.iteration}
            </Badge>
          )}
        </div>
        {step.result && (
          <details className="mt-1.5">
            <summary className="text-[10px] text-muted-foreground cursor-pointer hover:text-foreground">
              View result
            </summary>
            <pre className="text-[9px] font-mono bg-muted/50 rounded p-1.5 mt-1 overflow-auto max-h-24 whitespace-pre-wrap">
              {JSON.stringify(step.result, null, 2)}
            </pre>
          </details>
        )}
        {step.error && (
          <div className="flex items-center gap-1.5 mt-1.5">
            <RefreshCw className="h-2.5 w-2.5 text-amber-500" />
            <p className="text-[10px] text-red-500">{step.error}</p>
          </div>
        )}
      </div>
    )
  }

  if (step.type === 'approval_required') {
    return (
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-3 animate-in fade-in slide-in-from-left-2 duration-300">
        <div className="flex items-center gap-2 mb-2">
          <ShieldCheck className="h-4 w-4 text-amber-500" />
          <span className="text-[12px] font-semibold text-amber-700 dark:text-amber-400">Approval Required</span>
        </div>
        <p className="text-[11px] text-muted-foreground mb-3">{step.content}</p>
        {step.params && (
          <pre className="text-[9px] font-mono bg-muted/50 rounded p-1.5 mb-3 overflow-auto max-h-16 whitespace-pre-wrap">
            {JSON.stringify(step.params, null, 2)}
          </pre>
        )}
        {onApprove && (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="default"
              className="gap-1.5 text-xs bg-green-600 hover:bg-green-700"
              onClick={() => onApprove(true)}
            >
              <CheckCircle2 className="h-3 w-3" /> Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 text-xs border-red-300 text-red-600 hover:bg-red-50"
              onClick={() => onApprove(false)}
            >
              <XCircle className="h-3 w-3" /> Reject
            </Button>
          </div>
        )}
      </div>
    )
  }

  if (step.type === 'error') {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 animate-in fade-in duration-300">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-3 w-3 text-red-500" />
          <span className="text-[11px] text-red-500">{step.content}</span>
        </div>
      </div>
    )
  }

  return null
}
