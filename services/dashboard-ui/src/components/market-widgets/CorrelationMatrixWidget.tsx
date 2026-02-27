import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Loader2 } from 'lucide-react'

interface CorrData { labels: string[]; matrix: number[][] }

function corrColor(val: number): string {
  if (val >= 0.7) return 'bg-green-600/80 text-white'
  if (val >= 0.3) return 'bg-green-500/40'
  if (val >= -0.3) return 'bg-muted/30'
  if (val >= -0.7) return 'bg-red-500/40'
  return 'bg-red-600/80 text-white'
}

export default function CorrelationMatrixWidget() {
  const { data, isLoading } = useQuery<CorrData>({
    queryKey: ['market', 'correlations'],
    queryFn: () => axios.get('/api/v1/market/correlations').then(r => r.data),
    refetchInterval: 600_000,
  })

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  if (!data?.labels?.length) return <div className="flex items-center justify-center h-full text-[10px] text-muted-foreground">No data</div>

  const { labels, matrix } = data

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-auto">
      <p className="text-[9px] text-muted-foreground text-center">30-Day Rolling Correlation</p>
      <div className="overflow-auto flex-1">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-[9px] text-muted-foreground p-1" />
              {labels.map(l => (
                <th key={l} className="text-[9px] text-muted-foreground font-medium p-1 text-center">{l}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((rowLabel, i) => (
              <tr key={rowLabel}>
                <td className="text-[9px] text-muted-foreground font-medium p-1 text-right pr-2">{rowLabel}</td>
                {matrix[i].map((val, j) => (
                  <td key={j} className={`text-[9px] font-mono text-center p-1 rounded-sm ${i === j ? 'bg-purple-500/20 text-purple-400' : corrColor(val)}`}>
                    {i === j ? '1.00' : val.toFixed(2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-center gap-1 text-[8px] text-muted-foreground">
        <div className="flex items-center gap-0.5"><div className="h-2 w-2 rounded-sm bg-red-600/80" /> Strong -</div>
        <div className="flex items-center gap-0.5"><div className="h-2 w-2 rounded-sm bg-muted/30" /> Neutral</div>
        <div className="flex items-center gap-0.5"><div className="h-2 w-2 rounded-sm bg-green-600/80" /> Strong +</div>
      </div>
    </div>
  )
}
