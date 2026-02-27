import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'

interface RVOLEntry {
  ticker: string
  volume: number
  avg_volume: number
  rvol: number
  price: number
}

function formatVol(val: number): string {
  if (val >= 1e6) return `${(val / 1e6).toFixed(1)}M`
  if (val >= 1e3) return `${(val / 1e3).toFixed(0)}K`
  return `${val}`
}

export default function RelativeVolumeWidget() {
  const { data, isLoading } = useQuery<RVOLEntry[]>({
    queryKey: ['market', 'rvol'],
    queryFn: () => axios.get('/api/v1/market/rvol').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  return (
    <ScrollArea className="h-full">
      <div className="p-2">
        <div className="grid grid-cols-4 gap-1 text-[9px] text-muted-foreground font-medium px-2 pb-1 border-b">
          <span>Ticker</span>
          <span className="text-right">RVOL</span>
          <span className="text-right">Volume</span>
          <span className="text-right">Avg</span>
        </div>
        <div className="space-y-0.5 mt-1">
          {data?.map(item => {
            const rvolColor = item.rvol >= 3 ? 'text-red-400' : item.rvol >= 2 ? 'text-orange-400' : item.rvol >= 1.5 ? 'text-yellow-400' : 'text-muted-foreground'
            return (
              <div key={item.ticker} className="grid grid-cols-4 gap-1 items-center px-2 py-1 rounded hover:bg-muted/50">
                <div>
                  <span className="text-xs font-semibold">{item.ticker}</span>
                  <p className="text-[9px] text-muted-foreground">${item.price}</p>
                </div>
                <div className="text-right">
                  <span className={`text-xs font-bold ${rvolColor}`}>{item.rvol.toFixed(1)}x</span>
                </div>
                <span className="text-[10px] text-muted-foreground text-right">{formatVol(item.volume)}</span>
                <span className="text-[10px] text-muted-foreground text-right">{formatVol(item.avg_volume)}</span>
              </div>
            )
          })}
        </div>
      </div>
    </ScrollArea>
  )
}
