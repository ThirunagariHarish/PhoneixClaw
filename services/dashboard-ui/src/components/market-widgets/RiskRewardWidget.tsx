import { useState, useMemo } from 'react'

export default function RiskRewardWidget() {
  const [entry, setEntry] = useState('')
  const [stop, setStop] = useState('')
  const [target, setTarget] = useState('')
  const [direction, setDirection] = useState<'long' | 'short'>('long')

  const result = useMemo(() => {
    const e = parseFloat(entry) || 0
    const s = parseFloat(stop) || 0
    const t = parseFloat(target) || 0
    if (!e || !s || !t) return null

    const risk = direction === 'long' ? e - s : s - e
    const reward = direction === 'long' ? t - e : e - t
    if (risk <= 0 || reward <= 0) return null

    const ratio = reward / risk
    const riskPct = (risk / e) * 100
    const rewardPct = (reward / e) * 100
    const breakeven = (1 / (1 + ratio)) * 100

    return { risk, reward, ratio, riskPct, rewardPct, breakeven }
  }, [entry, stop, target, direction])

  const barWidth = result ? Math.min((result.ratio / 5) * 100, 100) : 0
  const barColor = result
    ? result.ratio >= 3 ? 'bg-green-500' : result.ratio >= 2 ? 'bg-emerald-500' : result.ratio >= 1 ? 'bg-yellow-500' : 'bg-red-500'
    : 'bg-muted'

  return (
    <div className="p-3 h-full flex flex-col gap-2 overflow-auto">
      <div className="flex gap-1 mb-1">
        {(['long', 'short'] as const).map(d => (
          <button key={d} onClick={() => setDirection(d)}
            className={`flex-1 text-[10px] py-1 rounded-full border transition-colors ${
              direction === d
                ? d === 'long' ? 'bg-green-500/20 border-green-500/40 text-green-400' : 'bg-red-500/20 border-red-500/40 text-red-400'
                : 'border-border hover:bg-muted/50'
            }`}>
            {d.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="text-[9px] text-muted-foreground uppercase">Entry</label>
          <input type="number" value={entry} onChange={e => setEntry(e.target.value)} placeholder="0.00" step="0.01"
            className="w-full text-xs bg-muted/30 border border-border rounded px-2 py-1.5 outline-none focus:border-purple-500/40" />
        </div>
        <div>
          <label className="text-[9px] text-muted-foreground uppercase">Stop</label>
          <input type="number" value={stop} onChange={e => setStop(e.target.value)} placeholder="0.00" step="0.01"
            className="w-full text-xs bg-muted/30 border border-border rounded px-2 py-1.5 outline-none focus:border-red-500/40" />
        </div>
        <div>
          <label className="text-[9px] text-muted-foreground uppercase">Target</label>
          <input type="number" value={target} onChange={e => setTarget(e.target.value)} placeholder="0.00" step="0.01"
            className="w-full text-xs bg-muted/30 border border-border rounded px-2 py-1.5 outline-none focus:border-green-500/40" />
        </div>
      </div>

      {result ? (
        <div className="mt-1 space-y-2">
          <div className="bg-muted/20 rounded-lg p-3 text-center">
            <p className="text-[9px] text-muted-foreground uppercase">Risk : Reward</p>
            <p className="text-3xl font-bold">1 : <span className={result.ratio >= 2 ? 'text-green-400' : result.ratio >= 1 ? 'text-yellow-400' : 'text-red-400'}>{result.ratio.toFixed(2)}</span></p>
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-[9px] text-muted-foreground">
              <span>R:R Gauge</span>
              <span>{result.ratio.toFixed(1)}R</span>
            </div>
            <div className="w-full bg-muted/30 rounded-full h-2.5">
              <div className={`${barColor} h-2.5 rounded-full transition-all duration-500`} style={{ width: `${barWidth}%` }} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-red-500/10 rounded p-1.5">
              <p className="text-[9px] text-muted-foreground">Risk</p>
              <p className="text-[11px] font-semibold text-red-400">${result.risk.toFixed(2)}</p>
              <p className="text-[9px] text-red-400/70">{result.riskPct.toFixed(1)}%</p>
            </div>
            <div className="bg-green-500/10 rounded p-1.5">
              <p className="text-[9px] text-muted-foreground">Reward</p>
              <p className="text-[11px] font-semibold text-green-400">${result.reward.toFixed(2)}</p>
              <p className="text-[9px] text-green-400/70">{result.rewardPct.toFixed(1)}%</p>
            </div>
            <div className="bg-muted/20 rounded p-1.5">
              <p className="text-[9px] text-muted-foreground">Breakeven</p>
              <p className="text-[11px] font-semibold">{result.breakeven.toFixed(1)}%</p>
              <p className="text-[9px] text-muted-foreground">win rate</p>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[10px] text-muted-foreground text-center">Enter entry, stop, and target to visualize risk/reward</p>
        </div>
      )}
    </div>
  )
}
