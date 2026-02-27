import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'

interface VolData {
  iv_current: number; iv_rank: number; iv_percentile: number
  iv_high_52w: number; iv_low_52w: number
  hv_10: number; hv_20: number; hv_30: number
  hv_iv_spread: number
}

function GaugeBar({ value, max, color, label }: { value: number; max: number; color: string; label: string }) {
  const pct = Math.min((value / max) * 100, 100)
  return (
    <div>
      <div className="flex justify-between text-[9px] mb-0.5">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-medium">{value.toFixed(1)}%</span>
      </div>
      <div className="w-full bg-muted/30 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function VolatilityDashboardWidget() {
  const { data, isLoading } = useQuery<VolData>({
    queryKey: ['market', 'volatility'],
    queryFn: () => axios.get('/api/v1/market/volatility').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  if (!data || data.iv_current === undefined) return <div className="flex items-center justify-center h-full text-[10px] text-muted-foreground">No data</div>

  const ivLevel = data.iv_rank > 50 ? 'High' : data.iv_rank > 25 ? 'Medium' : 'Low'
  const ivColor = ivLevel === 'High' ? 'text-red-400' : ivLevel === 'Medium' ? 'text-yellow-400' : 'text-green-400'

  return (
    <div className="p-3 h-full flex flex-col gap-3 overflow-auto">
      <div className="text-center">
        <p className="text-[9px] text-muted-foreground uppercase">SPY Implied Volatility</p>
        <p className="text-3xl font-bold font-mono">{data.iv_current.toFixed(1)}<span className="text-sm text-muted-foreground">%</span></p>
        <p className={`text-[10px] font-medium ${ivColor}`}>IV Rank: {ivLevel}</p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="bg-muted/20 rounded p-2 text-center">
          <p className="text-[9px] text-muted-foreground">IV Rank</p>
          <p className="text-sm font-bold">{data.iv_rank.toFixed(0)}%</p>
        </div>
        <div className="bg-muted/20 rounded p-2 text-center">
          <p className="text-[9px] text-muted-foreground">IV Percentile</p>
          <p className="text-sm font-bold">{data.iv_percentile.toFixed(0)}%</p>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-[9px] font-semibold text-muted-foreground uppercase">Historical Volatility</p>
        <GaugeBar value={data.hv_10} max={60} color="bg-blue-500" label="HV 10-day" />
        <GaugeBar value={data.hv_20} max={60} color="bg-blue-400" label="HV 20-day" />
        <GaugeBar value={data.hv_30} max={60} color="bg-blue-300" label="HV 30-day" />
      </div>

      <div className="border-t pt-2">
        <div className="flex justify-between">
          <span className="text-[9px] text-muted-foreground">HV-IV Spread</span>
          <span className={`text-xs font-mono font-bold ${data.hv_iv_spread > 0 ? 'text-red-400' : 'text-green-400'}`}>
            {data.hv_iv_spread > 0 ? '+' : ''}{data.hv_iv_spread.toFixed(1)}%
          </span>
        </div>
        <p className="text-[8px] text-muted-foreground mt-0.5">
          {data.hv_iv_spread > 3 ? 'IV elevated vs HV - options expensive' : data.hv_iv_spread < -3 ? 'IV compressed - options cheap' : 'IV near HV - fair pricing'}
        </p>
      </div>

      <div className="flex justify-between text-[9px] text-muted-foreground border-t pt-1">
        <span>52W Low: {data.iv_low_52w}</span>
        <span>52W High: {data.iv_high_52w}</span>
      </div>
    </div>
  )
}
