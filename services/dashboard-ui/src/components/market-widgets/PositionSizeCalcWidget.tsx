import { useState, useMemo } from 'react'

export default function PositionSizeCalcWidget() {
  const [accountSize, setAccountSize] = useState('25000')
  const [riskPct, setRiskPct] = useState('1')
  const [entry, setEntry] = useState('')
  const [stop, setStop] = useState('')

  const result = useMemo(() => {
    const acct = parseFloat(accountSize) || 0
    const risk = parseFloat(riskPct) || 0
    const entryPrice = parseFloat(entry) || 0
    const stopPrice = parseFloat(stop) || 0

    if (!acct || !risk || !entryPrice || !stopPrice || entryPrice === stopPrice) {
      return null
    }

    const dollarRisk = acct * (risk / 100)
    const stopDistance = Math.abs(entryPrice - stopPrice)
    const shares = Math.floor(dollarRisk / stopDistance)
    const positionValue = shares * entryPrice
    const pctOfAccount = (positionValue / acct) * 100

    return { dollarRisk, stopDistance, shares, positionValue, pctOfAccount }
  }, [accountSize, riskPct, entry, stop])

  return (
    <div className="p-3 h-full flex flex-col gap-2 overflow-auto">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] text-muted-foreground uppercase">Account Size</label>
          <div className="relative">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">$</span>
            <input type="number" value={accountSize} onChange={e => setAccountSize(e.target.value)}
              className="w-full text-xs bg-muted/30 border border-border rounded px-2 py-1.5 pl-5 outline-none focus:border-purple-500/40" />
          </div>
        </div>
        <div>
          <label className="text-[9px] text-muted-foreground uppercase">Risk %</label>
          <div className="relative">
            <input type="number" value={riskPct} onChange={e => setRiskPct(e.target.value)} step="0.25"
              className="w-full text-xs bg-muted/30 border border-border rounded px-2 py-1.5 outline-none focus:border-purple-500/40" />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">%</span>
          </div>
        </div>
        <div>
          <label className="text-[9px] text-muted-foreground uppercase">Entry Price</label>
          <div className="relative">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">$</span>
            <input type="number" value={entry} onChange={e => setEntry(e.target.value)} placeholder="0.00" step="0.01"
              className="w-full text-xs bg-muted/30 border border-border rounded px-2 py-1.5 pl-5 outline-none focus:border-purple-500/40" />
          </div>
        </div>
        <div>
          <label className="text-[9px] text-muted-foreground uppercase">Stop Loss</label>
          <div className="relative">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">$</span>
            <input type="number" value={stop} onChange={e => setStop(e.target.value)} placeholder="0.00" step="0.01"
              className="w-full text-xs bg-muted/30 border border-border rounded px-2 py-1.5 pl-5 outline-none focus:border-purple-500/40" />
          </div>
        </div>
      </div>

      {result ? (
        <div className="mt-1 space-y-2">
          <div className="bg-purple-500/10 border border-purple-500/20 rounded-lg p-3 text-center">
            <p className="text-[9px] text-muted-foreground uppercase">Position Size</p>
            <p className="text-2xl font-bold text-purple-400">{result.shares} shares</p>
            <p className="text-[10px] text-muted-foreground">${result.positionValue.toLocaleString()} ({result.pctOfAccount.toFixed(1)}% of account)</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-muted/20 rounded p-2 text-center">
              <p className="text-[9px] text-muted-foreground">Dollar Risk</p>
              <p className="text-sm font-semibold text-red-400">${result.dollarRisk.toFixed(2)}</p>
            </div>
            <div className="bg-muted/20 rounded p-2 text-center">
              <p className="text-[9px] text-muted-foreground">Stop Distance</p>
              <p className="text-sm font-semibold">${result.stopDistance.toFixed(2)}</p>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[10px] text-muted-foreground text-center">Enter entry and stop loss prices to calculate position size</p>
        </div>
      )}
    </div>
  )
}
