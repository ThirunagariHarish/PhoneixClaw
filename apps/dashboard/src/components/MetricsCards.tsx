/**
 * P7: Live risk metrics cards — Sharpe, Max DD, Current DD, Win Rate.
 * Reads from /api/v2/agents/{id}/live-metrics.
 */
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { TrendingUp, TrendingDown, Activity, Target } from 'lucide-react'

interface LiveMetrics {
  sharpe_30d: number
  sharpe_all: number
  max_drawdown_pct: number
  current_drawdown_pct: number
  win_rate: number
  total_trades: number
}

interface Props {
  agentId: string
  days?: number
}

export function MetricsCards({ agentId, days = 30 }: Props) {
  const { data, isLoading, isError } = useQuery<LiveMetrics>({
    queryKey: ['live-metrics', agentId, days],
    queryFn: async () =>
      (await api.get(`/api/v2/agents/${agentId}/live-metrics?days=${days}`)).data,
    refetchInterval: 15000,
    retry: 1,
    throwOnError: false,
  })

  if (isError) {
    return (
      <div className="text-xs text-muted-foreground p-2">
        Live metrics unavailable
      </div>
    )
  }

  const cards = [
    {
      label: 'Sharpe (30d)',
      value: isLoading ? '—' : (data?.sharpe_30d ?? 0).toFixed(2),
      Icon: TrendingUp,
      color: (data?.sharpe_30d ?? 0) >= 1 ? 'text-emerald-500' : 'text-amber-500',
    },
    {
      label: 'Max Drawdown',
      value: isLoading ? '—' : `${(data?.max_drawdown_pct ?? 0).toFixed(2)}%`,
      Icon: TrendingDown,
      color: (data?.max_drawdown_pct ?? 0) > 10 ? 'text-rose-500' : 'text-emerald-500',
    },
    {
      label: 'Current DD',
      value: isLoading ? '—' : `${(data?.current_drawdown_pct ?? 0).toFixed(2)}%`,
      Icon: Activity,
      color: (data?.current_drawdown_pct ?? 0) > 5 ? 'text-rose-500' : 'text-muted-foreground',
    },
    {
      label: 'Win Rate',
      value: isLoading ? '—' : `${((data?.win_rate ?? 0) * 100).toFixed(1)}%`,
      Icon: Target,
      color: (data?.win_rate ?? 0) >= 0.55 ? 'text-emerald-500' : 'text-amber-500',
      sub: data ? `${data.total_trades} trades` : '',
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((c) => (
        <Card key={c.label}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs text-muted-foreground">{c.label}</div>
                <div className={`text-2xl font-semibold ${c.color}`}>{c.value}</div>
                {c.sub && <div className="text-xs text-muted-foreground mt-0.5">{c.sub}</div>}
              </div>
              <c.Icon className={`w-8 h-8 ${c.color} opacity-50`} />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
