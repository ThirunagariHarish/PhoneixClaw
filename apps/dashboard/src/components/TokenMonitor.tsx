/**
 * TokenMonitor — sidebar widget showing Claude Code token usage and costs.
 */
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { Coins, AlertTriangle } from 'lucide-react'

interface TokenData {
  daily: { total_tokens: number; estimated_cost_usd: number }
  weekly: { total_tokens: number; estimated_cost_usd: number }
  monthly: { total_tokens: number; estimated_cost_usd: number }
  budget: { monthly_limit_usd: number; used_pct: number; remaining_usd: number }
  by_agent: Array<{ agent_id: string | null; tokens_today: number; cost_today_usd: number }>
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

export function TokenMonitor() {
  const { data, isLoading } = useQuery<TokenData>({
    queryKey: ['token-usage'],
    queryFn: async () => (await api.get('/api/v2/token-usage')).data,
    refetchInterval: 60_000,
  })

  if (isLoading || !data) {
    return (
      <div className="rounded-xl border bg-card p-4 animate-pulse">
        <div className="h-4 w-32 bg-muted rounded mb-3" />
        <div className="space-y-2">
          <div className="h-3 w-full bg-muted rounded" />
          <div className="h-3 w-3/4 bg-muted rounded" />
        </div>
      </div>
    )
  }

  const { daily, weekly, monthly, budget } = data
  const isWarning = budget.used_pct >= 80
  const isCritical = budget.used_pct >= 95

  return (
    <div className={`rounded-xl border bg-card p-4 ${isCritical ? 'border-red-500/50' : isWarning ? 'border-amber-500/50' : ''}`}>
      <div className="flex items-center gap-2 mb-3">
        <Coins className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-semibold">Claude Code Usage</span>
        {isCritical && <AlertTriangle className="h-3.5 w-3.5 text-red-500" />}
        {isWarning && !isCritical && <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />}
      </div>

      <div className="space-y-1.5 text-xs">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Today</span>
          <span className="font-mono">{formatTokens(daily.total_tokens)} <span className="text-muted-foreground">${daily.estimated_cost_usd.toFixed(2)}</span></span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Week</span>
          <span className="font-mono">{formatTokens(weekly.total_tokens)} <span className="text-muted-foreground">${weekly.estimated_cost_usd.toFixed(2)}</span></span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Month</span>
          <span className="font-mono">{formatTokens(monthly.total_tokens)} <span className="text-muted-foreground">${monthly.estimated_cost_usd.toFixed(2)}</span></span>
        </div>
      </div>

      {/* Budget bar */}
      <div className="mt-3">
        <div className="h-2 rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${isCritical ? 'bg-red-500' : isWarning ? 'bg-amber-500' : 'bg-primary'}`}
            style={{ width: `${Math.min(budget.used_pct, 100)}%` }}
          />
        </div>
        <div className="flex justify-between mt-1 text-[10px] text-muted-foreground">
          <span>{budget.used_pct.toFixed(0)}% of budget</span>
          <span>${budget.remaining_usd.toFixed(2)} left</span>
        </div>
      </div>

      {/* Top agents */}
      {data.by_agent.length > 0 && (
        <div className="mt-3 pt-3 border-t space-y-1">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">By Agent</p>
          {data.by_agent.slice(0, 3).map((a, i) => (
            <div key={i} className="flex justify-between text-[11px]">
              <span className="truncate text-muted-foreground">{a.agent_id?.slice(0, 8) || 'System'}</span>
              <span className="font-mono">{formatTokens(a.tokens_today)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
