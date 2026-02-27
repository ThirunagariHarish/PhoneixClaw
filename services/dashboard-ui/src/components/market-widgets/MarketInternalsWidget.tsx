import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'

interface InternalData {
  name: string
  value: number
  change: number
  zone: string
}

const ZONE_COLORS: Record<string, string> = {
  'Bullish': 'text-green-400 bg-green-500/10',
  'Bearish': 'text-red-400 bg-red-500/10',
  'Risk-On': 'text-green-400 bg-green-500/10',
  'Risk-Off': 'text-red-400 bg-red-500/10',
  'Neutral': 'text-yellow-400 bg-yellow-500/10',
  'N/A': 'text-muted-foreground bg-muted/20',
}

const DESCRIPTIONS: Record<string, string> = {
  TICK: 'NYSE net upticks vs downticks',
  TRIN: 'Arms Index (breadth)',
  ADD: 'Advance-Decline line',
  VIX: 'CBOE Volatility Index',
}

export default function MarketInternalsWidget() {
  const { data, isLoading } = useQuery<InternalData[]>({
    queryKey: ['market', 'internals'],
    queryFn: () => axios.get('/api/v1/market/internals').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  const bullCount = data?.filter(d => d.zone === 'Bullish' || d.zone === 'Risk-On').length ?? 0
  const bearCount = data?.filter(d => d.zone === 'Bearish' || d.zone === 'Risk-Off').length ?? 0
  const overallBias = bullCount > bearCount ? 'Bullish' : bearCount > bullCount ? 'Bearish' : 'Mixed'

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-auto">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">Market Internals</span>
        <span className={`text-[9px] font-medium px-2 py-0.5 rounded-full ${
          overallBias === 'Bullish' ? 'bg-green-500/10 text-green-400'
          : overallBias === 'Bearish' ? 'bg-red-500/10 text-red-400'
          : 'bg-yellow-500/10 text-yellow-400'
        }`}>{overallBias} Bias</span>
      </div>

      <div className="flex-1 space-y-2">
        {data?.map(item => (
          <div key={item.name} className="rounded-lg border p-2.5">
            <div className="flex items-center justify-between mb-1">
              <div>
                <span className="text-sm font-bold">{item.name}</span>
                <p className="text-[9px] text-muted-foreground">{DESCRIPTIONS[item.name] || ''}</p>
              </div>
              <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full ${ZONE_COLORS[item.zone] || ZONE_COLORS['N/A']}`}>
                {item.zone}
              </span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-mono font-bold">{item.value.toFixed(2)}</span>
              <span className={`text-xs font-mono ${item.change > 0 ? 'text-green-400' : item.change < 0 ? 'text-red-400' : 'text-muted-foreground'}`}>
                {item.change > 0 ? '+' : ''}{item.change.toFixed(2)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
