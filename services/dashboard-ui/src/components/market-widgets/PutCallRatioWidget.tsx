import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'

interface PCData {
  symbol: string
  put_volume: number
  call_volume: number
  ratio: number
  sentiment: string
}

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const color = sentiment === 'Bullish' ? 'text-green-400 bg-green-500/10'
    : sentiment === 'Bearish' ? 'text-red-400 bg-red-500/10'
    : 'text-yellow-400 bg-yellow-500/10'
  return <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full ${color}`}>{sentiment}</span>
}

function GaugeBar({ ratio }: { ratio: number }) {
  const pct = Math.min(ratio / 2, 1) * 100
  const color = ratio > 1.0 ? 'bg-red-500' : ratio < 0.7 ? 'bg-green-500' : 'bg-yellow-500'
  return (
    <div className="w-full bg-muted/30 rounded-full h-2 mt-1">
      <div className={`${color} h-2 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export default function PutCallRatioWidget() {
  const { data, isLoading } = useQuery<PCData[]>({
    queryKey: ['market', 'put-call-ratio'],
    queryFn: () => axios.get('/api/v1/market/put-call-ratio').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  return (
    <div className="p-3 h-full flex flex-col gap-3 overflow-auto">
      {data?.map(item => (
        <div key={item.symbol} className="rounded-lg border p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-bold">{item.symbol}</span>
            <SentimentBadge sentiment={item.sentiment} />
          </div>
          <div className="text-2xl font-mono font-bold mb-1">{item.ratio.toFixed(3)}</div>
          <GaugeBar ratio={item.ratio} />
          <div className="flex justify-between mt-2 text-[10px] text-muted-foreground">
            <span>Puts: {(item.put_volume / 1000).toFixed(0)}K</span>
            <span>Calls: {(item.call_volume / 1000).toFixed(0)}K</span>
          </div>
        </div>
      ))}
      <p className="text-[9px] text-muted-foreground text-center mt-auto">
        {'< 0.7 Bullish | 0.7-1.0 Neutral | > 1.0 Bearish'}
      </p>
    </div>
  )
}
