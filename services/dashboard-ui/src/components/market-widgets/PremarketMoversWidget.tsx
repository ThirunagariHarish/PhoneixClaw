import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'

interface MoverEntry {
  ticker: string
  pre_price: number
  prev_close: number
  change_pct: number
  volume: number
}

function formatVol(n: number): string {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}K` : `${n}`
}

export default function PremarketMoversWidget() {
  const { data, isLoading } = useQuery<MoverEntry[]>({
    queryKey: ['market', 'premarket-movers'],
    queryFn: () => axios.get('/api/v1/market/premarket-movers').then(r => r.data),
    refetchInterval: 120_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  return (
    <ScrollArea className="h-full">
      <div className="p-2 space-y-1">
        <div className="grid grid-cols-5 text-[9px] text-muted-foreground font-medium px-2 pb-1 border-b">
          <span className="col-span-2">Ticker</span>
          <span className="text-right">Pre</span>
          <span className="text-right">Chg</span>
          <span className="text-right">Vol</span>
        </div>
        {data?.map((m, i) => (
          <div key={m.ticker} className="grid grid-cols-5 items-center px-2 py-1 rounded hover:bg-muted/50">
            <div className="col-span-2 flex items-center gap-2">
              <span className="text-[10px] text-muted-foreground w-4">{i + 1}</span>
              <span className="text-xs font-semibold">{m.ticker}</span>
            </div>
            <span className="text-xs text-muted-foreground text-right">${m.pre_price}</span>
            <div className="text-right">
              <Badge variant={m.change_pct >= 0 ? 'default' : 'destructive'} className="text-[9px] px-1">
                {m.change_pct >= 0 ? '+' : ''}{m.change_pct.toFixed(1)}%
              </Badge>
            </div>
            <span className="text-[10px] text-muted-foreground text-right">{formatVol(m.volume)}</span>
          </div>
        ))}
      </div>
    </ScrollArea>
  )
}
