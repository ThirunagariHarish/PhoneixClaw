import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'

interface Levels {
  current?: number
  prev_high?: number; prev_low?: number; prev_close?: number
  pivot?: number; r1?: number; r2?: number; s1?: number; s2?: number
  week_high?: number; week_low?: number; month_high?: number; month_low?: number
  vwap_approx?: number
}

function LevelRow({ label, value, current, color }: { label: string; value?: number; current?: number; color: string }) {
  if (!value) return null
  const diff = current ? ((current - value) / value * 100).toFixed(2) : '0'
  return (
    <div className="flex items-center justify-between px-2 py-1 rounded hover:bg-muted/50">
      <div className="flex items-center gap-2">
        <div className={`h-2 w-2 rounded-full ${color}`} />
        <span className="text-[11px] font-medium">{label}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs font-mono">${value.toFixed(2)}</span>
        <span className={`text-[9px] font-mono ${parseFloat(diff) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {parseFloat(diff) >= 0 ? '+' : ''}{diff}%
        </span>
      </div>
    </div>
  )
}

export default function SpxKeyLevelsWidget() {
  const { data, isLoading } = useQuery<Levels>({
    queryKey: ['market', 'spx-levels'],
    queryFn: () => axios.get('/api/v1/market/spx-levels').then(r => r.data),
    refetchInterval: 300_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  return (
    <div className="p-2 h-full flex flex-col gap-1 overflow-auto">
      {data?.current && (
        <div className="text-center py-1 border-b mb-1">
          <p className="text-[9px] text-muted-foreground">SPY Current</p>
          <p className="text-lg font-bold font-mono">${data.current.toFixed(2)}</p>
        </div>
      )}

      <p className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider px-2">Resistance</p>
      <LevelRow label="R2" value={data?.r2} current={data?.current} color="bg-red-500" />
      <LevelRow label="R1" value={data?.r1} current={data?.current} color="bg-red-400" />
      <LevelRow label="Month High" value={data?.month_high} current={data?.current} color="bg-orange-400" />
      <LevelRow label="Week High" value={data?.week_high} current={data?.current} color="bg-orange-400" />
      <LevelRow label="Prev High" value={data?.prev_high} current={data?.current} color="bg-yellow-400" />

      <p className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider px-2 mt-1">Key Levels</p>
      <LevelRow label="VWAP" value={data?.vwap_approx} current={data?.current} color="bg-purple-500" />
      <LevelRow label="Pivot" value={data?.pivot} current={data?.current} color="bg-blue-400" />
      <LevelRow label="Prev Close" value={data?.prev_close} current={data?.current} color="bg-blue-300" />

      <p className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider px-2 mt-1">Support</p>
      <LevelRow label="Prev Low" value={data?.prev_low} current={data?.current} color="bg-yellow-400" />
      <LevelRow label="Week Low" value={data?.week_low} current={data?.current} color="bg-orange-400" />
      <LevelRow label="Month Low" value={data?.month_low} current={data?.current} color="bg-orange-400" />
      <LevelRow label="S1" value={data?.s1} current={data?.current} color="bg-green-400" />
      <LevelRow label="S2" value={data?.s2} current={data?.current} color="bg-green-500" />
    </div>
  )
}
