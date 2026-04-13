/**
 * Watchlist page -- persistent ticker watchlist with live-ish quotes.
 *
 * Features: server-side persistence (falls back to localStorage),
 * multiple named watchlists, fundamentals columns (P/E, EPS, div yield, earnings),
 * one-click trade button (disabled), bulk add tickers.
 */
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Eye, Plus, Trash2, Bell, ArrowUpDown, ExternalLink, ShoppingCart, Edit2, X, FolderPlus } from 'lucide-react'
import { cn } from '@/lib/utils'

const WATCHLIST_KEY = 'phoenix-watchlist-tickers'
const ACTIVE_LIST_KEY = 'phoenix-watchlist-active'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface QuoteData {
  symbol: string
  last_price: number | null
  change: number | null
  change_pct: number | null
  volume: number | null
  market_cap: number | null
  high_52w: number | null
  low_52w: number | null
  sparkline?: number[]
  pe_ratio?: number | null
  eps?: number | null
  dividend_yield?: number | null
  next_earnings?: string | null
}

type SortField = 'symbol' | 'last_price' | 'change' | 'change_pct' | 'volume' | 'market_cap' | 'pe_ratio' | 'eps'
type SortDir = 'asc' | 'desc'

/* ------------------------------------------------------------------ */
/*  LocalStorage helpers (fallback)                                    */
/* ------------------------------------------------------------------ */

function loadTickers(): string[] {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed.filter((t: unknown) => typeof t === 'string')
    }
  } catch { /* noop */ }
  return []
}

function saveTickers(tickers: string[]) {
  try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(tickers)) } catch { /* noop */ }
}

/* ------------------------------------------------------------------ */
/*  Formatting helpers                                                 */
/* ------------------------------------------------------------------ */

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return '--'
  return n.toFixed(decimals)
}

function fmtLarge(n: number | null | undefined): string {
  if (n == null) return '--'
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(1)}T`
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(0)
}

function pnlColor(v: number | null | undefined): string {
  if (v == null || v === 0) return ''
  return v > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
}

/* ------------------------------------------------------------------ */
/*  Sparkline mini-chart (SVG)                                         */
/* ------------------------------------------------------------------ */

function Sparkline({ data, className }: { data?: number[]; className?: string }) {
  if (!data || data.length < 2) return <span className="text-xs text-muted-foreground">--</span>

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const w = 80
  const h = 24
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w
    const y = h - ((v - min) / range) * h
    return `${x},${y}`
  }).join(' ')

  const trending = data[data.length - 1] >= data[0]
  const color = trending ? 'stroke-emerald-500' : 'stroke-red-500'

  return (
    <svg width={w} height={h} className={cn('inline-block', className)} viewBox={`0 0 ${w} ${h}`}>
      <polyline
        points={points}
        fill="none"
        className={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/*  52-week range bar                                                  */
/* ------------------------------------------------------------------ */

function RangeBar({ current, low, high }: { current: number | null; low: number | null; high: number | null }) {
  if (current == null || low == null || high == null || high === low) {
    return <span className="text-xs text-muted-foreground">--</span>
  }
  const pct = Math.max(0, Math.min(100, ((current - low) / (high - low)) * 100))
  return (
    <div className="flex items-center gap-1.5 min-w-[120px]">
      <span className="text-[10px] text-muted-foreground tabular-nums">{fmt(low, 0)}</span>
      <div className="relative flex-1 h-1.5 rounded-full bg-muted">
        <div
          className="absolute top-0 left-0 h-full rounded-full bg-primary/40"
          style={{ width: `${pct}%` }}
        />
        <div
          className="absolute top-1/2 -translate-y-1/2 h-3 w-1 rounded-full bg-primary"
          style={{ left: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] text-muted-foreground tabular-nums">{fmt(high, 0)}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function WatchlistPage() {
  const qc = useQueryClient()
  const [tickers, setTickers] = useState<string[]>(loadTickers)
  const [inputValue, setInputValue] = useState('')
  const [sortField, setSortField] = useState<SortField>('symbol')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [serverAvailable, setServerAvailable] = useState(true)

  // Multiple watchlists
  const [watchlists, setWatchlists] = useState<Record<string, string[]>>({})
  const [activeList, setActiveList] = useState<string>(() => {
    try { return localStorage.getItem(ACTIVE_LIST_KEY) ?? 'Default' } catch { return 'Default' }
  })
  const [showNewList, setShowNewList] = useState(false)
  const [newListName, setNewListName] = useState('')
  const [renamingList, setRenamingList] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deletingList, setDeletingList] = useState<string | null>(null)

  // Persist active list name
  useEffect(() => {
    try { localStorage.setItem(ACTIVE_LIST_KEY, activeList) } catch { /* noop */ }
  }, [activeList])

  // Fetch server-side watchlists
  const { data: serverLists } = useQuery<{ watchlists: Record<string, string[]> }>({
    queryKey: ['watchlist-lists'],
    queryFn: async () => {
      try {
        // Auto-sync broker gateway watchlist on load
        try { await api.post('/api/v2/watchlist/sync-broker') } catch { /* noop */ }
        const res = await api.get('/api/v2/watchlist/lists')
        setServerAvailable(true)
        return res.data
      } catch {
        setServerAvailable(false)
        return { watchlists: {} }
      }
    },
    refetchInterval: 30000,
  })

  // Sync server lists to local state
  useEffect(() => {
    if (serverLists?.watchlists && Object.keys(serverLists.watchlists).length > 0) {
      setWatchlists(serverLists.watchlists)
      const activeTickers = serverLists.watchlists[activeList] ?? []
      setTickers(activeTickers)
      saveTickers(activeTickers)
    }
  }, [serverLists]) // eslint-disable-line react-hooks/exhaustive-deps

  // If no server lists, use localStorage tickers for "Default"
  useEffect(() => {
    if (!serverAvailable && Object.keys(watchlists).length === 0) {
      const localTickers = loadTickers()
      if (localTickers.length > 0) {
        setWatchlists({ Default: localTickers })
        setTickers(localTickers)
      }
    }
  }, [serverAvailable]) // eslint-disable-line react-hooks/exhaustive-deps

  const watchlistNames = useMemo(() => {
    const names = Object.keys(watchlists)
    if (names.length === 0) return ['Default']
    return names
  }, [watchlists])

  // Server mutations
  const addMutation = useMutation({
    mutationFn: async ({ symbols, listName }: { symbols: string[]; listName: string }) => {
      if (serverAvailable) {
        await api.post('/api/v2/watchlist/lists', { symbols, watchlist_name: listName })
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist-lists'] }),
  })

  const removeMutation = useMutation({
    mutationFn: async ({ symbol, listName }: { symbol: string; listName: string }) => {
      if (serverAvailable) {
        await api.delete(`/api/v2/watchlist/lists/${encodeURIComponent(listName)}/symbols/${symbol}`)
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist-lists'] }),
  })

  const renameMutation = useMutation({
    mutationFn: async ({ oldName, newName }: { oldName: string; newName: string }) => {
      if (serverAvailable) {
        await api.post('/api/v2/watchlist/lists/rename', { old_name: oldName, new_name: newName })
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist-lists'] }),
  })

  const deleteListMutation = useMutation({
    mutationFn: async (listName: string) => {
      if (serverAvailable) {
        await api.delete(`/api/v2/watchlist/lists/${encodeURIComponent(listName)}`)
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist-lists'] }),
  })

  // Persist tickers to localStorage as fallback
  useEffect(() => { saveTickers(tickers) }, [tickers])

  // Fetch quotes for all tickers
  const { data: quotes = [], isLoading, isError } = useQuery<QuoteData[]>({
    queryKey: ['watchlist-quotes', tickers],
    queryFn: async () => {
      if (tickers.length === 0) return []
      try {
        const res = await api.get('/api/v2/watchlist/quotes', {
          params: { symbols: tickers.join(',') },
        })
        // Map API response fields to component fields
        return (res.data ?? []).map((q: Record<string, unknown>) => ({
          symbol: q.symbol as string,
          last_price: (q.last_price ?? q.price ?? null) as number | null,
          change: (q.change ?? null) as number | null,
          change_pct: (q.change_pct ?? null) as number | null,
          volume: (q.volume ?? null) as number | null,
          market_cap: (q.market_cap ?? null) as number | null,
          high_52w: (q.high_52w ?? q.fifty_two_week_high ?? null) as number | null,
          low_52w: (q.low_52w ?? q.fifty_two_week_low ?? null) as number | null,
          sparkline: q.sparkline as number[] | undefined,
          pe_ratio: (q.pe_ratio ?? null) as number | null,
          eps: (q.eps ?? null) as number | null,
          dividend_yield: (q.dividend_yield ?? null) as number | null,
          next_earnings: (q.next_earnings ?? null) as string | null,
        }))
      } catch {
        return tickers.map((symbol) => ({
          symbol,
          last_price: null,
          change: null,
          change_pct: null,
          volume: null,
          market_cap: null,
          high_52w: null,
          low_52w: null,
          sparkline: undefined,
          pe_ratio: null,
          eps: null,
          dividend_yield: null,
          next_earnings: null,
        }))
      }
    },
    refetchInterval: 60_000,
    enabled: tickers.length > 0,
  })

  // Build a map for quick lookup
  const quoteMap = useMemo(() => {
    const m = new Map<string, QuoteData>()
    for (const q of quotes) m.set(q.symbol.toUpperCase(), q)
    return m
  }, [quotes])

  // Merge tickers with quote data and sort
  const rows = useMemo(() => {
    const merged = tickers.map((t) => {
      const q = quoteMap.get(t.toUpperCase())
      return {
        symbol: t.toUpperCase(),
        last_price: q?.last_price ?? null,
        change: q?.change ?? null,
        change_pct: q?.change_pct ?? null,
        volume: q?.volume ?? null,
        market_cap: q?.market_cap ?? null,
        high_52w: q?.high_52w ?? null,
        low_52w: q?.low_52w ?? null,
        sparkline: q?.sparkline,
        pe_ratio: q?.pe_ratio ?? null,
        eps: q?.eps ?? null,
        dividend_yield: q?.dividend_yield ?? null,
        next_earnings: q?.next_earnings ?? null,
      }
    })

    merged.sort((a, b) => {
      let cmp = 0
      if (sortField === 'symbol') {
        cmp = a.symbol.localeCompare(b.symbol)
      } else {
        const av = a[sortField] ?? -Infinity
        const bv = b[sortField] ?? -Infinity
        cmp = av < bv ? -1 : av > bv ? 1 : 0
      }
      return sortDir === 'asc' ? cmp : -cmp
    })

    return merged
  }, [tickers, quoteMap, sortField, sortDir])

  // Add ticker(s)
  const addTickers = useCallback((input: string) => {
    // Support comma-separated bulk add
    const symbols = input.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean)
    const existingSet = new Set(tickers.map((t) => t.toUpperCase()))
    const newSymbols = symbols.filter((s) => !existingSet.has(s))

    if (newSymbols.length === 0) {
      setInputValue('')
      return
    }

    setTickers((prev) => [...prev, ...newSymbols])
    setInputValue('')

    // Update local watchlists state
    setWatchlists((prev) => ({
      ...prev,
      [activeList]: [...(prev[activeList] ?? []), ...newSymbols],
    }))

    // Sync to server
    addMutation.mutate({ symbols: newSymbols, listName: activeList })
    qc.invalidateQueries({ queryKey: ['watchlist-quotes'] })
  }, [inputValue, tickers, activeList, addMutation, qc])

  // Remove ticker
  const removeTicker = useCallback((sym: string) => {
    setTickers((prev) => prev.filter((t) => t.toUpperCase() !== sym.toUpperCase()))
    setWatchlists((prev) => ({
      ...prev,
      [activeList]: (prev[activeList] ?? []).filter((t) => t.toUpperCase() !== sym.toUpperCase()),
    }))
    removeMutation.mutate({ symbol: sym.toUpperCase(), listName: activeList })
  }, [activeList, removeMutation])

  // Toggle sort
  const toggleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }, [sortField])

  // Switch active list
  const switchList = useCallback((name: string) => {
    setActiveList(name)
    const listTickers = watchlists[name] ?? []
    setTickers(listTickers)
    saveTickers(listTickers)
  }, [watchlists])

  // Create new watchlist
  const createList = useCallback(() => {
    const name = newListName.trim()
    if (!name || watchlistNames.includes(name)) return
    setWatchlists((prev) => ({ ...prev, [name]: [] }))
    setActiveList(name)
    setTickers([])
    saveTickers([])
    setShowNewList(false)
    setNewListName('')
    // Server will create on first add
  }, [newListName, watchlistNames])

  // Rename watchlist
  const doRename = useCallback(() => {
    const newName = renameValue.trim()
    if (!newName || !renamingList || newName === renamingList) return
    setWatchlists((prev) => {
      const updated = { ...prev }
      updated[newName] = updated[renamingList] ?? []
      delete updated[renamingList]
      return updated
    })
    if (activeList === renamingList) setActiveList(newName)
    renameMutation.mutate({ oldName: renamingList, newName })
    setRenamingList(null)
    setRenameValue('')
  }, [renameValue, renamingList, activeList, renameMutation])

  const SortHeader = ({ field, label }: { field: SortField; label: string }) => (
    <TableHead
      className="cursor-pointer select-none hover:text-foreground transition-colors"
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortField === field && (
          <ArrowUpDown className="h-3 w-3 text-primary" />
        )}
      </span>
    </TableHead>
  )

  // Summary metrics
  const gainers = rows.filter((r) => (r.change_pct ?? 0) > 0).length
  const losers = rows.filter((r) => (r.change_pct ?? 0) < 0).length

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Eye} title="Watchlist" description="Track tickers with live quotes">
        <form
          className="flex gap-2"
          onSubmit={(e) => { e.preventDefault(); addTickers(inputValue) }}
        >
          <Input
            placeholder="AAPL, TSLA, NVDA..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value.toUpperCase())}
            className="w-44 sm:w-56 font-mono uppercase"
          />
          <Button type="submit" size="sm" disabled={!inputValue.trim()}>
            <Plus className="h-4 w-4 mr-1" /> Add
          </Button>
        </form>
      </PageHeader>

      {/* Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
        <MetricCard title="Watching" value={tickers.length} />
        <MetricCard title="Gainers" value={gainers} trend={gainers > 0 ? 'up' : 'neutral'} />
        <MetricCard title="Losers" value={losers} trend={losers > 0 ? 'down' : 'neutral'} />
        <MetricCard title="Refresh" value="60s" subtitle="Auto-refresh interval" />
      </div>

      {/* Watchlist Tabs */}
      <div className="flex items-center gap-2 flex-wrap border-b pb-2">
        {watchlistNames.map((name) => (
          <div key={name} className="flex items-center gap-0.5">
            <Button
              variant={activeList === name ? 'default' : 'ghost'}
              size="sm"
              className="text-xs h-7"
              onClick={() => switchList(name)}
            >
              {name}
              {activeList === name && ` (${tickers.length})`}
            </Button>
            {activeList === name && watchlistNames.length > 1 && (
              <div className="flex">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => { setRenamingList(name); setRenameValue(name) }}
                >
                  <Edit2 className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-destructive"
                  onClick={() => setDeletingList(name)}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            )}
          </div>
        ))}
        <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => setShowNewList(true)}>
          <FolderPlus className="h-3 w-3" /> New List
        </Button>
      </div>

      {/* Watchlist table */}
      {tickers.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Eye className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-muted-foreground">Your watchlist is empty.</p>
            <p className="text-sm text-muted-foreground mt-1">Add tickers above (comma-separated for bulk add).</p>
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-xl border border-border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <SortHeader field="symbol" label="Symbol" />
                <TableHead>5D Trend</TableHead>
                <SortHeader field="last_price" label="Last Price" />
                <SortHeader field="change" label="Change $" />
                <SortHeader field="change_pct" label="Change %" />
                <SortHeader field="volume" label="Volume" />
                <SortHeader field="market_cap" label="Mkt Cap" />
                <SortHeader field="pe_ratio" label="P/E" />
                <SortHeader field="eps" label="EPS" />
                <TableHead>Div Yield</TableHead>
                <TableHead>Earnings</TableHead>
                <TableHead>52W Range</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: Math.min(tickers.length, 5) }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 13 }).map((__, j) => (
                      <TableCell key={j}><Skeleton className="h-6 w-full" /></TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                rows.map((row) => (
                  <TableRow key={row.symbol}>
                    {/* Symbol */}
                    <TableCell>
                      <a
                        href={`https://www.tradingview.com/symbols/${row.symbol}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-mono font-semibold text-primary hover:underline inline-flex items-center gap-1"
                      >
                        {row.symbol}
                        <ExternalLink className="h-3 w-3 opacity-50" />
                      </a>
                    </TableCell>

                    {/* Sparkline */}
                    <TableCell>
                      <Sparkline data={row.sparkline} />
                    </TableCell>

                    {/* Last Price */}
                    <TableCell className="tabular-nums font-medium">
                      {row.last_price != null ? `$${fmt(row.last_price)}` : '--'}
                    </TableCell>

                    {/* Change $ */}
                    <TableCell className={cn('tabular-nums', pnlColor(row.change))}>
                      {row.change != null ? `${row.change >= 0 ? '+' : ''}$${fmt(row.change)}` : '--'}
                    </TableCell>

                    {/* Change % */}
                    <TableCell className={cn('tabular-nums', pnlColor(row.change_pct))}>
                      {row.change_pct != null ? `${row.change_pct >= 0 ? '+' : ''}${fmt(row.change_pct)}%` : '--'}
                    </TableCell>

                    {/* Volume */}
                    <TableCell className="tabular-nums">
                      {fmtLarge(row.volume)}
                    </TableCell>

                    {/* Market Cap */}
                    <TableCell className="tabular-nums">
                      {fmtLarge(row.market_cap)}
                    </TableCell>

                    {/* P/E Ratio */}
                    <TableCell className="tabular-nums text-xs">
                      {row.pe_ratio != null ? fmt(row.pe_ratio, 1) : '--'}
                    </TableCell>

                    {/* EPS */}
                    <TableCell className="tabular-nums text-xs">
                      {row.eps != null ? `$${fmt(row.eps)}` : '--'}
                    </TableCell>

                    {/* Dividend Yield */}
                    <TableCell className="tabular-nums text-xs">
                      {row.dividend_yield != null ? `${(row.dividend_yield * 100).toFixed(2)}%` : '--'}
                    </TableCell>

                    {/* Next Earnings */}
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {row.next_earnings ?? '--'}
                    </TableCell>

                    {/* 52W Range */}
                    <TableCell>
                      <RangeBar current={row.last_price} low={row.low_52w} high={row.high_52w} />
                    </TableCell>

                    {/* Actions */}
                    <TableCell className="text-right">
                      <div className="inline-flex items-center gap-1">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-7 w-7" disabled>
                              <ShoppingCart className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Coming soon: One-click trade</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-7 w-7" disabled>
                              <Bell className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Coming soon: price alerts</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-destructive hover:text-destructive"
                              onClick={() => removeTicker(row.symbol)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Remove from watchlist</TooltipContent>
                        </Tooltip>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          {isError && (
            <div className="p-4 text-center text-sm text-muted-foreground">
              Could not fetch quotes. Showing cached data or placeholders.
            </div>
          )}
        </div>
      )}

      {/* New Watchlist Dialog */}
      <Dialog open={showNewList} onOpenChange={setShowNewList}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Watchlist</DialogTitle>
          </DialogHeader>
          <Input
            placeholder="Watchlist name..."
            value={newListName}
            onChange={(e) => setNewListName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') createList() }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewList(false)}>Cancel</Button>
            <Button onClick={createList} disabled={!newListName.trim()}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rename Watchlist Dialog */}
      <Dialog open={!!renamingList} onOpenChange={() => setRenamingList(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Watchlist</DialogTitle>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') doRename() }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenamingList(null)}>Cancel</Button>
            <Button onClick={doRename} disabled={!renameValue.trim()}>Rename</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Watchlist Confirm */}
      <ConfirmDialog
        open={!!deletingList}
        onOpenChange={() => setDeletingList(null)}
        title="Delete Watchlist"
        description={`Delete "${deletingList}" and all its tickers?`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={async () => {
          if (!deletingList) return
          deleteListMutation.mutate(deletingList)
          setWatchlists((prev) => {
            const updated = { ...prev }
            delete updated[deletingList]
            return updated
          })
          const remaining = watchlistNames.filter((n) => n !== deletingList)
          const next = remaining[0] ?? 'Default'
          switchList(next)
          setDeletingList(null)
        }}
      />
    </div>
  )
}
