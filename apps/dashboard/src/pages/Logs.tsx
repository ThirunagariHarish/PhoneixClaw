/**
 * Logs — Unified system log viewer for client, server, and agent logs.
 */
import { useState, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import {
  Terminal, RefreshCw, ChevronDown, ChevronRight,
  AlertCircle, AlertTriangle, Info, Bug, Download, Calendar,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const SOURCE_TABS = ['all', 'client', 'server', 'agent', 'backtest'] as const
const LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARN', 'ERROR'] as const

const LEVEL_STYLES: Record<string, { bg: string; text: string; icon: typeof Info; chartColor: string }> = {
  DEBUG: { bg: 'bg-zinc-500/20', text: 'text-zinc-400', icon: Bug, chartColor: '#71717a' },
  INFO: { bg: 'bg-blue-500/20', text: 'text-blue-400', icon: Info, chartColor: '#3b82f6' },
  WARN: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: AlertTriangle, chartColor: '#eab308' },
  ERROR: { bg: 'bg-red-500/20', text: 'text-red-400', icon: AlertCircle, chartColor: '#ef4444' },
}

interface LogEntry {
  id: string
  source: string
  level: string
  service: string
  agent_id: string | null
  backtest_id: string | null
  message: string
  details: Record<string, unknown>
  step: string | null
  progress_pct: number | null
  created_at: string
}

export default function Logs() {
  const [source, setSource] = useState<string>('all')
  const [level, setLevel] = useState<string>('ALL')
  const [search, setSearch] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // L1: Date/time range picker state
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // L2: Build params for server-side search + date range
  const params = new URLSearchParams()
  if (source !== 'all') params.set('source', source)
  if (level !== 'ALL') params.set('level', level)
  if (search.trim()) params.set('search', search.trim())
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  params.set('limit', '200')

  const { data: logs = [], isLoading } = useQuery({
    queryKey: ['system-logs', source, level, search, dateFrom, dateTo],
    queryFn: () => api.get<LogEntry[]>(`/api/v2/system-logs?${params.toString()}`).then(r => r.data),
    refetchInterval: autoRefresh ? 3000 : false,
  })

  // L4: Error rate histogram data (last 24h bucketed by level)
  const histogramData = useMemo(() => {
    const now = new Date()
    const cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000)
    const levelCounts: Record<string, number> = { DEBUG: 0, INFO: 0, WARN: 0, ERROR: 0 }

    for (const log of logs) {
      const d = new Date(log.created_at)
      if (d >= cutoff && levelCounts[log.level] !== undefined) {
        levelCounts[log.level]++
      }
    }

    return Object.entries(levelCounts).map(([lvl, count]) => ({
      level: lvl,
      count,
      fill: LEVEL_STYLES[lvl]?.chartColor ?? '#71717a',
    }))
  }, [logs])

  // L3: Export current logs as CSV
  function handleExport() {
    const headers = ['Time', 'Source', 'Level', 'Service', 'Message', 'Agent ID', 'Backtest ID', 'Step']
    const rows = logs.map(l => [
      l.created_at,
      l.source,
      l.level,
      l.service,
      `"${(l.message ?? '').replace(/"/g, '""')}"`,
      l.agent_id ?? '',
      l.backtest_id ?? '',
      l.step ?? '',
    ])

    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `phoenix-logs-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Terminal className="h-6 w-6 text-emerald-500" />
            System Logs
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Unified log stream from all services, agents, and backtests
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* L3: Export button */}
          <button
            onClick={handleExport}
            disabled={logs.length === 0}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm border transition-colors',
              'border-border bg-card text-muted-foreground hover:text-foreground',
              logs.length === 0 && 'opacity-50 cursor-not-allowed'
            )}
          >
            <Download className="h-3.5 w-3.5" />
            Export
          </button>
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm border transition-colors',
              autoRefresh
                ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400'
                : 'border-border bg-card text-muted-foreground'
            )}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', autoRefresh && 'animate-spin')} />
            {autoRefresh ? 'Live' : 'Paused'}
          </button>
        </div>
      </div>

      {/* L4: Error rate histogram */}
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
          Log levels (last 24h)
        </h3>
        <div className="h-24">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={histogramData} barSize={40}>
              <XAxis dataKey="level" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis hide />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '8px',
                  fontSize: '12px',
                }}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {histogramData.map((entry, index) => (
                  <Cell key={index} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Source Tabs + Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        {SOURCE_TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setSource(tab)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-sm font-medium capitalize transition-colors',
              source === tab
                ? 'bg-primary text-primary-foreground'
                : 'bg-card border border-border text-muted-foreground hover:text-foreground'
            )}
          >
            {tab}
          </button>
        ))}
        <div className="mx-2 h-6 w-px bg-border" />
        <select
          value={level}
          onChange={e => setLevel(e.target.value)}
          className="bg-card border border-border rounded-lg px-3 py-1.5 text-sm"
        >
          {LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        {/* L2: Server-side search input */}
        <input
          type="text"
          placeholder="Search logs (server-side)..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="bg-card border border-border rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[200px]"
        />
        <span className="text-xs text-muted-foreground">{logs.length} entries</span>
      </div>

      {/* L1: Date/time range picker */}
      <div className="flex items-center gap-3 flex-wrap">
        <Calendar className="h-4 w-4 text-muted-foreground" />
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">From</label>
          <input
            type="datetime-local"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="bg-card border border-border rounded-lg px-3 py-1.5 text-sm"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">To</label>
          <input
            type="datetime-local"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="bg-card border border-border rounded-lg px-3 py-1.5 text-sm"
          />
        </div>
        {(dateFrom || dateTo) && (
          <button
            onClick={() => { setDateFrom(''); setDateTo('') }}
            className="text-xs text-muted-foreground hover:text-foreground underline"
          >
            Clear dates
          </button>
        )}
      </div>

      {/* Log Table */}
      <div ref={scrollRef} className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="grid grid-cols-[140px_70px_70px_120px_1fr] gap-2 px-4 py-2 border-b border-border text-xs font-medium text-muted-foreground uppercase tracking-wider">
          <span>Time</span>
          <span>Source</span>
          <span>Level</span>
          <span>Service</span>
          <span>Message</span>
        </div>
        <div className="divide-y divide-border max-h-[calc(100vh-480px)] overflow-y-auto font-mono text-xs">
          {isLoading && (
            <div className="px-4 py-8 text-center text-muted-foreground">Loading...</div>
          )}
          {!isLoading && logs.length === 0 && (
            <div className="px-4 py-8 text-center text-muted-foreground">No logs found</div>
          )}
          {logs.map(log => {
            const ls = LEVEL_STYLES[log.level] || LEVEL_STYLES.INFO
            const LevelIcon = ls.icon
            const isExpanded = expandedId === log.id
            const time = log.created_at ? new Date(log.created_at).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''
            const date = log.created_at ? new Date(log.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''
            return (
              <div key={log.id}>
                <button
                  onClick={() => setExpandedId(isExpanded ? null : log.id)}
                  className="w-full grid grid-cols-[140px_70px_70px_120px_1fr] gap-2 px-4 py-2 hover:bg-muted/50 transition-colors text-left items-center"
                >
                  <span className="text-muted-foreground">{date} {time}</span>
                  <span className="capitalize text-muted-foreground">{log.source}</span>
                  <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium', ls.bg, ls.text)}>
                    <LevelIcon className="h-3 w-3" />
                    {log.level}
                  </span>
                  <span className="text-muted-foreground truncate">{log.service}</span>
                  <span className="text-foreground truncate flex items-center gap-1">
                    {isExpanded ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
                    {log.step && <span className="text-cyan-400 mr-1">[{log.step}]</span>}
                    {log.message}
                  </span>
                </button>
                {isExpanded && (
                  <div className="px-4 py-3 bg-muted/30 border-t border-border">
                    {log.agent_id && <div className="mb-1"><span className="text-muted-foreground">Agent:</span> <span className="text-cyan-400">{log.agent_id}</span></div>}
                    {log.backtest_id && <div className="mb-1"><span className="text-muted-foreground">Backtest:</span> <span className="text-cyan-400">{log.backtest_id}</span></div>}
                    {log.progress_pct !== null && (
                      <div className="mb-2">
                        <span className="text-muted-foreground">Progress:</span>
                        <div className="mt-1 w-full bg-muted rounded-full h-1.5">
                          <div className="bg-emerald-500 h-1.5 rounded-full transition-all" style={{ width: `${log.progress_pct}%` }} />
                        </div>
                      </div>
                    )}
                    {Object.keys(log.details).length > 0 && (
                      <pre className="mt-2 p-2 bg-black/30 rounded text-[11px] text-zinc-300 overflow-x-auto whitespace-pre-wrap">
                        {JSON.stringify(log.details, null, 2)}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
