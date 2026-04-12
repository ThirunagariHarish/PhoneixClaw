/**
 * Watchlist page -- persistent ticker watchlist with live-ish quotes.
 * Stores tickers in localStorage; fetches quotes from API with 60s auto-refresh.
 */
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Eye, Plus, Trash2, Bell, ArrowUpDown, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'

const WATCHLIST_KEY = 'phoenix-watchlist-tickers'

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
}

type SortField = 'symbol' | 'last_price' | 'change' | 'change_pct' | 'volume' | 'market_cap'
type SortDir = 'asc' | 'desc'

/* ------------------------------------------------------------------ */
/*  LocalStorage helpers                                               */
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

  // Persist tickers whenever they change
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
        return res.data ?? []
      } catch {
        // If the endpoint does not exist, return placeholder data
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

  // Add ticker
  const addTicker = useCallback(() => {
    const sym = inputValue.trim().toUpperCase()
    if (!sym || tickers.map((t) => t.toUpperCase()).includes(sym)) {
      setInputValue('')
      return
    }
    setTickers((prev) => [...prev, sym])
    setInputValue('')
    qc.invalidateQueries({ queryKey: ['watchlist-quotes'] })
  }, [inputValue, tickers, qc])

  // Remove ticker
  const removeTicker = useCallback((sym: string) => {
    setTickers((prev) => prev.filter((t) => t.toUpperCase() !== sym.toUpperCase()))
  }, [])

  // Toggle sort
  const toggleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }, [sortField])

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
          onSubmit={(e) => { e.preventDefault(); addTicker() }}
        >
          <Input
            placeholder="Add ticker (e.g. AAPL)"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value.toUpperCase())}
            className="w-36 sm:w-44 font-mono uppercase"
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

      {/* Watchlist table */}
      {tickers.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Eye className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-muted-foreground">Your watchlist is empty.</p>
            <p className="text-sm text-muted-foreground mt-1">Add a ticker above to start tracking.</p>
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
                <TableHead>52W Range</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: Math.min(tickers.length, 5) }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 9 }).map((__, j) => (
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
    </div>
  )
}
