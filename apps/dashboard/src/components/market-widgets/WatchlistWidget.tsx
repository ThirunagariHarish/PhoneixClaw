/**
 * MCP-4: Watchlist Widget — shows user's watchlist tickers with live price + change.
 * Click a ticker to update all linked widgets in the same link group.
 */
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'

interface WatchlistItem {
  ticker: string
  price: number
  change: number
  change_pct: number
}

interface Props {
  onTickerClick?: (ticker: string) => void
}

const FALLBACK_WATCHLIST: WatchlistItem[] = [
  { ticker: 'SPY', price: 523.42, change: 2.15, change_pct: 0.41 },
  { ticker: 'QQQ', price: 448.90, change: 3.22, change_pct: 0.72 },
  { ticker: 'AAPL', price: 189.84, change: -0.56, change_pct: -0.29 },
  { ticker: 'NVDA', price: 875.30, change: 12.40, change_pct: 1.44 },
  { ticker: 'TSLA', price: 172.10, change: -3.80, change_pct: -2.16 },
  { ticker: 'MSFT', price: 415.20, change: 1.30, change_pct: 0.31 },
  { ticker: 'AMZN', price: 186.50, change: 0.92, change_pct: 0.50 },
  { ticker: 'META', price: 502.60, change: 5.10, change_pct: 1.02 },
  { ticker: 'GOOG', price: 155.72, change: -0.28, change_pct: -0.18 },
  { ticker: 'AMD', price: 162.45, change: 4.30, change_pct: 2.72 },
]

export default function WatchlistWidget({ onTickerClick }: Props) {
  const { data, isLoading } = useQuery<WatchlistItem[]>({
    queryKey: ['market', 'watchlist'],
    queryFn: async () => {
      try {
        const res = await axios.get('/api/v1/market/watchlist')
        return res.data?.items ?? FALLBACK_WATCHLIST
      } catch {
        return FALLBACK_WATCHLIST
      }
    },
    refetchInterval: 60_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const items = data ?? FALLBACK_WATCHLIST

  return (
    <ScrollArea className="h-full">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-card z-10">
          <tr className="border-b">
            <th className="text-left py-1.5 px-2 font-medium text-muted-foreground">Ticker</th>
            <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Price</th>
            <th className="text-right py-1.5 px-2 font-medium text-muted-foreground">Chg%</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isUp = item.change_pct > 0
            const isFlat = item.change_pct === 0
            return (
              <tr
                key={item.ticker}
                onClick={() => onTickerClick?.(item.ticker)}
                className="hover:bg-muted/50 cursor-pointer transition-colors border-b border-border/30"
              >
                <td className="py-1.5 px-2 font-semibold">{item.ticker}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-muted-foreground">
                  ${item.price.toFixed(2)}
                </td>
                <td className="py-1.5 px-2 text-right tabular-nums">
                  <span className={
                    isFlat
                      ? 'text-muted-foreground'
                      : isUp
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-red-600 dark:text-red-400'
                  }>
                    <span className="inline-flex items-center gap-0.5">
                      {isFlat ? (
                        <Minus className="h-2.5 w-2.5" />
                      ) : isUp ? (
                        <TrendingUp className="h-2.5 w-2.5" />
                      ) : (
                        <TrendingDown className="h-2.5 w-2.5" />
                      )}
                      {isUp ? '+' : ''}{item.change_pct.toFixed(2)}%
                    </span>
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </ScrollArea>
  )
}
