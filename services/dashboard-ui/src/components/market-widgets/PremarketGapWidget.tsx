import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2, TrendingUp, TrendingDown } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { useState } from 'react'

interface GapEntry {
  ticker: string
  pre_price: number
  prev_close: number
  gap_pct: number
  volume: number
}
interface GapData { gappers_up: GapEntry[]; gappers_down: GapEntry[] }

export default function PremarketGapWidget() {
  const [tab, setTab] = useState<'up' | 'down'>('up')

  const { data, isLoading } = useQuery<GapData>({
    queryKey: ['market', 'premarket-gaps'],
    queryFn: () => axios.get('/api/v1/market/premarket-gaps').then(r => r.data),
    refetchInterval: 120_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  const items = tab === 'up' ? data?.gappers_up : data?.gappers_down

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b">
        <button onClick={() => setTab('up')}
          className={`flex-1 text-[11px] py-1.5 font-medium transition-colors ${tab === 'up' ? 'text-green-500 border-b-2 border-green-500' : 'text-muted-foreground'}`}>
          <TrendingUp className="h-3 w-3 inline mr-1" /> Gap Up
        </button>
        <button onClick={() => setTab('down')}
          className={`flex-1 text-[11px] py-1.5 font-medium transition-colors ${tab === 'down' ? 'text-red-500 border-b-2 border-red-500' : 'text-muted-foreground'}`}>
          <TrendingDown className="h-3 w-3 inline mr-1" /> Gap Down
        </button>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {(!items || items.length === 0) ? (
            <p className="text-[10px] text-muted-foreground text-center py-4">No significant gaps detected</p>
          ) : items.map((g, i) => (
            <div key={g.ticker} className="flex items-center justify-between px-2 py-1.5 rounded hover:bg-muted/50">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground w-4">{i + 1}</span>
                <div>
                  <span className="text-xs font-semibold">{g.ticker}</span>
                  <p className="text-[9px] text-muted-foreground">${g.prev_close} prev</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">${g.pre_price}</span>
                <Badge variant={g.gap_pct >= 0 ? 'default' : 'destructive'} className="text-[9px] px-1.5">
                  {g.gap_pct >= 0 ? '+' : ''}{g.gap_pct.toFixed(2)}%
                </Badge>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
