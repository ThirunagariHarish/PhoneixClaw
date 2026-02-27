import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'

interface VixPoint { term: string; value: number; change: number }
interface VixData { points: VixPoint[]; regime: string }

export default function VixTermStructureWidget() {
  const { data, isLoading } = useQuery<VixData>({
    queryKey: ['market', 'vix-term-structure'],
    queryFn: () => axios.get('/api/v1/market/vix-term-structure').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  const points = data?.points || []
  const maxVal = Math.max(...points.map(p => p.value), 1)
  const isBackwardation = data?.regime?.includes('Backwardation')

  return (
    <div className="p-3 h-full flex flex-col gap-3 overflow-auto">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold">VIX Term Structure</span>
        <span className={`text-[9px] font-medium px-2 py-0.5 rounded-full ${
          isBackwardation ? 'bg-red-500/10 text-red-400' : 'bg-green-500/10 text-green-400'
        }`}>{data?.regime || 'N/A'}</span>
      </div>

      <div className="flex-1 flex items-end gap-1 min-h-[80px]">
        {points.map((p, i) => {
          const heightPct = (p.value / maxVal) * 100
          return (
            <div key={p.term} className="flex-1 flex flex-col items-center gap-1">
              <span className={`text-[10px] font-mono font-bold ${p.change > 0 ? 'text-red-400' : 'text-green-400'}`}>
                {p.value.toFixed(1)}
              </span>
              <div className="w-full relative" style={{ height: `${Math.max(heightPct, 10)}%` }}>
                <div className={`absolute inset-0 rounded-t ${
                  i === 0 ? 'bg-purple-500/60' : 'bg-purple-500/30'
                } transition-all duration-500`} />
              </div>
              <span className="text-[9px] text-muted-foreground font-medium">{p.term}</span>
              <span className={`text-[8px] font-mono ${p.change > 0 ? 'text-red-400' : p.change < 0 ? 'text-green-400' : 'text-muted-foreground'}`}>
                {p.change > 0 ? '+' : ''}{p.change.toFixed(1)}
              </span>
            </div>
          )
        })}
      </div>

      <div className="text-[9px] text-muted-foreground text-center border-t pt-2">
        Contango = calm, front &lt; back | Backwardation = fear, front &gt; back
      </div>
    </div>
  )
}
