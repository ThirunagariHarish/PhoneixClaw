import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'

interface TradeEntry { ticker: string; side: string; pnl: number; time: string }
interface PnlData {
  date: string; total_pnl: number; trade_count: number
  wins: number; losses: number; win_rate: number
  avg_win: number; avg_loss: number; trades: TradeEntry[]
}

export default function DayTradePnlWidget() {
  const { data, isLoading } = useQuery<PnlData>({
    queryKey: ['market', 'day-pnl'],
    queryFn: () => axios.get('/api/v1/market/day-pnl').then(r => r.data),
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  const pnl = data?.total_pnl ?? 0
  const isProfitable = pnl >= 0

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-hidden">
      <div className="text-center py-1">
        <p className="text-[9px] text-muted-foreground uppercase">Today's P&L</p>
        <p className={`text-2xl font-bold font-mono ${isProfitable ? 'text-green-400' : 'text-red-400'}`}>
          {isProfitable ? '+' : ''}${pnl.toFixed(2)}
        </p>
        <p className="text-[10px] text-muted-foreground">{data?.trade_count ?? 0} trades</p>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="bg-green-500/10 rounded p-1.5 text-center">
          <p className="text-[9px] text-muted-foreground">Wins</p>
          <p className="text-sm font-bold text-green-400">{data?.wins ?? 0}</p>
        </div>
        <div className="bg-red-500/10 rounded p-1.5 text-center">
          <p className="text-[9px] text-muted-foreground">Losses</p>
          <p className="text-sm font-bold text-red-400">{data?.losses ?? 0}</p>
        </div>
        <div className="bg-muted/20 rounded p-1.5 text-center">
          <p className="text-[9px] text-muted-foreground">Win Rate</p>
          <p className="text-sm font-bold">{(data?.win_rate ?? 0).toFixed(0)}%</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="bg-muted/20 rounded p-1.5 text-center">
          <p className="text-[9px] text-muted-foreground">Avg Win</p>
          <p className="text-xs font-mono text-green-400">${(data?.avg_win ?? 0).toFixed(2)}</p>
        </div>
        <div className="bg-muted/20 rounded p-1.5 text-center">
          <p className="text-[9px] text-muted-foreground">Avg Loss</p>
          <p className="text-xs font-mono text-red-400">${(data?.avg_loss ?? 0).toFixed(2)}</p>
        </div>
      </div>

      {(data?.trades?.length ?? 0) > 0 && (
        <>
          <p className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider">Recent Trades</p>
          <ScrollArea className="flex-1">
            <div className="space-y-0.5">
              {data?.trades.map((t, i) => (
                <div key={i} className="flex items-center justify-between px-2 py-1 rounded hover:bg-muted/50">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] text-muted-foreground font-mono">{t.time}</span>
                    <span className="text-xs font-semibold">{t.ticker}</span>
                    <span className={`text-[9px] px-1 rounded ${t.side === 'BUY' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>{t.side}</span>
                  </div>
                  <span className={`text-xs font-mono ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </ScrollArea>
        </>
      )}
    </div>
  )
}
