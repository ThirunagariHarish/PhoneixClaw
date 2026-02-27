import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'

interface StrikeGex { strike: number; gex: number }
interface GexData {
  symbol: string
  spot: number
  total_gex: number
  regime: string
  flip_point: number
  strikes: StrikeGex[]
}

export default function GammaExposureWidget() {
  const { data, isLoading } = useQuery<GexData>({
    queryKey: ['market', 'gex'],
    queryFn: () => axios.get('/api/v1/market/gex?symbol=SPY').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  if (!data || !data.strikes?.length) return <div className="flex items-center justify-center h-full text-[10px] text-muted-foreground">No GEX data available</div>

  const maxAbs = Math.max(...data.strikes.map(s => Math.abs(s.gex)), 1)
  const isLongGamma = data.total_gex > 0

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-auto">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-xs font-bold">{data.symbol}</span>
          <span className="text-[10px] text-muted-foreground ml-2">${data.spot}</span>
        </div>
        <span className={`text-[9px] font-medium px-2 py-0.5 rounded-full ${
          isLongGamma ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
        }`}>
          {data.regime}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="bg-muted/20 rounded p-2 text-center">
          <p className="text-[9px] text-muted-foreground">Total GEX</p>
          <p className={`text-sm font-bold ${isLongGamma ? 'text-green-400' : 'text-red-400'}`}>
            {(data.total_gex / 1e6).toFixed(1)}M
          </p>
        </div>
        <div className="bg-muted/20 rounded p-2 text-center">
          <p className="text-[9px] text-muted-foreground">Flip Point</p>
          <p className="text-sm font-bold text-yellow-400">${data.flip_point}</p>
        </div>
      </div>

      <p className="text-[9px] text-muted-foreground font-medium">GEX by Strike</p>
      <div className="flex-1 overflow-auto space-y-0.5">
        {data.strikes.map(s => {
          const pct = (s.gex / maxAbs) * 100
          const isPos = s.gex >= 0
          return (
            <div key={s.strike} className="flex items-center gap-2">
              <span className="text-[10px] font-mono w-12 text-right">${s.strike}</span>
              <div className="flex-1 h-3 relative bg-muted/20 rounded-sm overflow-hidden">
                {isPos ? (
                  <div className="absolute left-1/2 top-0 h-full bg-green-500/60 rounded-sm" style={{ width: `${Math.abs(pct) / 2}%` }} />
                ) : (
                  <div className="absolute top-0 h-full bg-red-500/60 rounded-sm" style={{ right: '50%', width: `${Math.abs(pct) / 2}%` }} />
                )}
                <div className="absolute left-1/2 top-0 h-full w-px bg-muted-foreground/30" />
              </div>
              <span className={`text-[9px] font-mono w-14 text-right ${isPos ? 'text-green-400' : 'text-red-400'}`}>
                {(s.gex / 1e3).toFixed(0)}K
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
