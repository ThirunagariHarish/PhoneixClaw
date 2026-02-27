import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useState } from 'react'

interface SectorData {
  sector: string
  etf: string
  '1w': number
  '1m': number
  '3m': number
}

const TIMEFRAMES = ['1w', '1m', '3m'] as const
type TF = typeof TIMEFRAMES[number]

export default function SectorRotationWidget() {
  const [sortBy, setSortBy] = useState<TF>('1w')

  const { data, isLoading } = useQuery<SectorData[]>({
    queryKey: ['market', 'sector-rotation'],
    queryFn: () => axios.get('/api/v1/market/sector-rotation').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  const sorted = data ? [...data].sort((a, b) => (b[sortBy] ?? 0) - (a[sortBy] ?? 0)) : []

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 p-2 pb-1">
        {TIMEFRAMES.map(tf => (
          <button
            key={tf}
            onClick={() => setSortBy(tf)}
            className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
              sortBy === tf ? 'bg-purple-500/20 border-purple-500/40 text-purple-400' : 'border-border hover:bg-muted/50'
            }`}
          >
            {tf.toUpperCase()}
          </button>
        ))}
      </div>
      <ScrollArea className="flex-1">
        <div className="px-2">
          <div className="grid grid-cols-5 gap-1 text-[9px] text-muted-foreground font-medium px-1 pb-1 border-b">
            <span className="col-span-2">Sector</span>
            <span className="text-right">1W</span>
            <span className="text-right">1M</span>
            <span className="text-right">3M</span>
          </div>
          <div className="space-y-0.5 mt-1">
            {sorted.map(s => (
              <div key={s.etf} className="grid grid-cols-5 gap-1 items-center px-1 py-1.5 rounded hover:bg-muted/50">
                <div className="col-span-2">
                  <span className="text-[11px] font-medium">{s.sector}</span>
                  <p className="text-[9px] text-muted-foreground">{s.etf}</p>
                </div>
                {TIMEFRAMES.map(tf => {
                  const val = s[tf] ?? 0
                  return (
                    <span key={tf} className={`text-[11px] font-mono text-right ${val > 0 ? 'text-green-400' : val < 0 ? 'text-red-400' : 'text-muted-foreground'}`}>
                      {val > 0 ? '+' : ''}{val.toFixed(1)}%
                    </span>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
