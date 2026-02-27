import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2, TrendingUp, TrendingDown } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useState } from 'react'

interface FTWEntry {
  ticker: string
  price: number
  high_52w: number
  low_52w: number
  pct_from_high: number
  pct_from_low: number
}

interface FTWData {
  near_highs: FTWEntry[]
  near_lows: FTWEntry[]
}

function RangeBar({ price, high, low }: { price: number; high: number; low: number }) {
  const range = high - low
  const pct = range > 0 ? ((price - low) / range) * 100 : 50
  return (
    <div className="relative w-full h-1.5 bg-muted/30 rounded-full">
      <div className="absolute top-0 left-0 h-1.5 bg-gradient-to-r from-red-500 via-yellow-500 to-green-500 rounded-full opacity-30 w-full" />
      <div
        className="absolute top-[-1px] h-2 w-2 rounded-full bg-white border-2 border-purple-500"
        style={{ left: `calc(${Math.min(Math.max(pct, 0), 100)}% - 4px)` }}
      />
    </div>
  )
}

export default function FiftyTwoWeekWidget() {
  const [tab, setTab] = useState<'highs' | 'lows'>('highs')

  const { data, isLoading } = useQuery<FTWData>({
    queryKey: ['market', '52week'],
    queryFn: () => axios.get('/api/v1/market/52week').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  const items = tab === 'highs' ? data?.near_highs : data?.near_lows

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b">
        <button
          onClick={() => setTab('highs')}
          className={`flex-1 text-[11px] py-1.5 font-medium transition-colors ${tab === 'highs' ? 'text-green-500 border-b-2 border-green-500' : 'text-muted-foreground'}`}
        >
          <TrendingUp className="h-3 w-3 inline mr-1" /> Near Highs
        </button>
        <button
          onClick={() => setTab('lows')}
          className={`flex-1 text-[11px] py-1.5 font-medium transition-colors ${tab === 'lows' ? 'text-red-500 border-b-2 border-red-500' : 'text-muted-foreground'}`}
        >
          <TrendingDown className="h-3 w-3 inline mr-1" /> Near Lows
        </button>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-2">
          {(!items || items.length === 0) ? (
            <p className="text-[10px] text-muted-foreground text-center py-4">No stocks near 52-week {tab}</p>
          ) : items.map(s => (
            <div key={s.ticker} className="px-2 py-1.5 rounded hover:bg-muted/50">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-semibold">{s.ticker}</span>
                <span className="text-xs text-muted-foreground">${s.price.toFixed(2)}</span>
              </div>
              <RangeBar price={s.price} high={s.high_52w} low={s.low_52w} />
              <div className="flex justify-between mt-1 text-[9px] text-muted-foreground">
                <span>Low: ${s.low_52w.toFixed(2)}</span>
                <span>High: ${s.high_52w.toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
