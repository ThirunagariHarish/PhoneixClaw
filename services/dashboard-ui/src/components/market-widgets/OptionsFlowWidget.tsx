import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useState } from 'react'

interface UnusualEntry { strike: number; type: string; volume: number; oi: number; ratio: number; exp: string }
interface FlowEntry {
  symbol: string
  call_volume: number; put_volume: number
  call_oi: number; put_oi: number
  pc_ratio: number
  unusual_activity: UnusualEntry[]
}

function formatNum(n: number): string {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}K` : `${n}`
}

export default function OptionsFlowWidget() {
  const [selectedSym, setSelectedSym] = useState(0)

  const { data, isLoading } = useQuery<FlowEntry[]>({
    queryKey: ['market', 'options-flow'],
    queryFn: () => axios.get('/api/v1/market/options-flow').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  if (!data?.length) return <div className="flex items-center justify-center h-full text-[10px] text-muted-foreground">No flow data</div>

  const item = data[selectedSym]
  const totalVol = item.call_volume + item.put_volume
  const callPct = totalVol > 0 ? (item.call_volume / totalVol) * 100 : 50

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-hidden">
      <div className="flex gap-1">
        {data.map((d, i) => (
          <button key={d.symbol} onClick={() => setSelectedSym(i)}
            className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
              selectedSym === i ? 'bg-purple-500/20 border-purple-500/40 text-purple-400' : 'border-border hover:bg-muted/50'
            }`}>{d.symbol}</button>
        ))}
      </div>

      <div className="space-y-1">
        <div className="flex justify-between text-[9px] text-muted-foreground">
          <span>Calls {formatNum(item.call_volume)}</span>
          <span>P/C {item.pc_ratio.toFixed(3)}</span>
          <span>Puts {formatNum(item.put_volume)}</span>
        </div>
        <div className="w-full h-3 rounded-full overflow-hidden flex">
          <div className="bg-green-500/60 h-full transition-all" style={{ width: `${callPct}%` }} />
          <div className="bg-red-500/60 h-full transition-all" style={{ width: `${100 - callPct}%` }} />
        </div>
        <div className="grid grid-cols-2 gap-2 text-center">
          <div className="bg-green-500/10 rounded p-1.5">
            <p className="text-[9px] text-muted-foreground">Call OI</p>
            <p className="text-xs font-semibold text-green-400">{formatNum(item.call_oi)}</p>
          </div>
          <div className="bg-red-500/10 rounded p-1.5">
            <p className="text-[9px] text-muted-foreground">Put OI</p>
            <p className="text-xs font-semibold text-red-400">{formatNum(item.put_oi)}</p>
          </div>
        </div>
      </div>

      {item.unusual_activity.length > 0 && (
        <>
          <p className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider">Unusual Activity</p>
          <ScrollArea className="flex-1">
            <div className="space-y-0.5">
              {item.unusual_activity.map((u, i) => (
                <div key={i} className="flex items-center justify-between px-2 py-1 rounded hover:bg-muted/50">
                  <div className="flex items-center gap-2">
                    <span className={`text-[9px] font-medium px-1 py-0.5 rounded ${
                      u.type === 'CALL' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                    }`}>{u.type}</span>
                    <span className="text-xs font-mono">${u.strike}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-[10px] font-mono">{formatNum(u.volume)} vol</span>
                    <p className="text-[9px] text-yellow-400">{u.ratio}x OI</p>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </>
      )}
    </div>
  )
}
