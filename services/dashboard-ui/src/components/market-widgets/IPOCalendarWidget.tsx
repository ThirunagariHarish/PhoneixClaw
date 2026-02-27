import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'

interface IPOEntry {
  ticker: string
  price: number
  change_pct: number
  market_cap: number
}

function formatCap(val: number): string {
  if (val >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
  if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`
  return `$${val}`
}

export default function IPOCalendarWidget() {
  const { data, isLoading } = useQuery<IPOEntry[]>({
    queryKey: ['market', 'ipo-calendar'],
    queryFn: () => axios.get('/api/v1/market/ipo-calendar').then(r => r.data),
    refetchInterval: 600_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>

  return (
    <ScrollArea className="h-full">
      <div className="p-2 space-y-1">
        {data?.map((ipo, i) => (
          <div key={ipo.ticker} className="flex items-center justify-between px-2 py-1.5 rounded hover:bg-muted/50">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-muted-foreground w-4">{i + 1}</span>
              <div>
                <span className="text-xs font-semibold">{ipo.ticker}</span>
                <p className="text-[9px] text-muted-foreground">{formatCap(ipo.market_cap)}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">${ipo.price.toFixed(2)}</span>
              <Badge variant={ipo.change_pct >= 0 ? 'default' : 'destructive'} className="text-[9px] px-1.5">
                {ipo.change_pct >= 0 ? '+' : ''}{ipo.change_pct.toFixed(2)}%
              </Badge>
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  )
}
