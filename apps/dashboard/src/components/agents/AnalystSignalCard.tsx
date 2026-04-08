/**
 * AnalystSignalCard — compact card displaying a single analyst trade signal.
 */
import { TrendingUp, TrendingDown, Minus, AlertCircle, CheckCircle2, Eye } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

export interface AnalystSignal {
  id: string
  agent_id: string
  ticker: string
  direction: string | null
  decision: string
  confidence: number | null
  analyst_persona: string | null
  entry_price: number | null
  stop_loss: number | null
  take_profit: number | null
  risk_reward_ratio: number | null
  pattern_name: string | null
  reasoning: string | null
  tool_signals_used: Record<string, unknown> | null
  created_at: string
}

interface AnalystSignalCardProps {
  signal: AnalystSignal
}

function DecisionBadge({ decision }: { decision: string }) {
  const config: Record<string, { label: string; className: string }> = {
    executed: { label: 'Executed', className: 'bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/30' },
    watchlist: { label: 'Watchlist', className: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30' },
    rejected: { label: 'Rejected', className: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30' },
  }
  const c = config[decision] ?? { label: decision, className: 'bg-muted/50 text-muted-foreground' }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${c.className}`}>
      {decision === 'executed' && <CheckCircle2 className="h-3 w-3" />}
      {decision === 'watchlist' && <Eye className="h-3 w-3" />}
      {decision === 'rejected' && <AlertCircle className="h-3 w-3" />}
      {c.label}
    </span>
  )
}

export function AnalystSignalCard({ signal }: AnalystSignalCardProps) {
  const isBuy = signal.direction === 'buy'
  const isSell = signal.direction === 'sell'

  const directionIcon = isBuy ? (
    <TrendingUp className="h-4 w-4 text-green-500" />
  ) : isSell ? (
    <TrendingDown className="h-4 w-4 text-red-500" />
  ) : (
    <Minus className="h-4 w-4 text-muted-foreground" />
  )

  const directionColor = isBuy
    ? 'text-green-600 dark:text-green-400'
    : isSell
      ? 'text-red-600 dark:text-red-400'
      : 'text-muted-foreground'

  const createdAt = signal.created_at
    ? new Date(signal.created_at).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      })
    : '—'

  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-2 hover:border-primary/30 transition-colors">
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {directionIcon}
          <span className="font-semibold text-sm">{signal.ticker}</span>
          <span className={`text-xs font-medium capitalize ${directionColor}`}>
            {signal.direction ?? '—'}
          </span>
          {signal.pattern_name && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4">
              {signal.pattern_name}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <DecisionBadge decision={signal.decision} />
        </div>
      </div>

      {/* Metrics row */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {signal.confidence !== null && (
          <span>
            Confidence:{' '}
            <span className="font-medium text-foreground">{signal.confidence}%</span>
          </span>
        )}
        {signal.entry_price !== null && (
          <span>
            Entry:{' '}
            <span className="font-medium text-foreground">${signal.entry_price.toFixed(2)}</span>
          </span>
        )}
        {signal.stop_loss !== null && (
          <span>
            SL:{' '}
            <span className="font-medium text-red-500">${signal.stop_loss.toFixed(2)}</span>
          </span>
        )}
        {signal.take_profit !== null && (
          <span>
            TP:{' '}
            <span className="font-medium text-green-500">${signal.take_profit.toFixed(2)}</span>
          </span>
        )}
        {signal.risk_reward_ratio !== null && (
          <span>
            R/R:{' '}
            <span className="font-medium text-foreground">{signal.risk_reward_ratio.toFixed(1)}:1</span>
          </span>
        )}
      </div>

      {/* Persona + timestamp */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {signal.analyst_persona && (
          <span className="capitalize">{signal.analyst_persona.replace(/_/g, ' ')}</span>
        )}
        <span className="ml-auto">{createdAt}</span>
      </div>

      {/* Reasoning */}
      {signal.reasoning && (
        <p className="text-xs text-muted-foreground line-clamp-2 border-t border-border/50 pt-1.5">
          {signal.reasoning}
        </p>
      )}
    </div>
  )
}
