/**
 * TopBetsPanel — Phase 15.7
 * Fetches and renders ranked top-bet cards from /api/polymarket/top-bets.
 * Includes per-card probability bars, AI reasoning expander, and a Place-Bet modal.
 */
import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import { ChevronDown, ChevronUp, TrendingUp } from 'lucide-react'
import type { VenueId } from './VenueSelectorPills'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PMTopBet {
  id: string
  question: string
  venue: string
  yes_probability: number
  no_probability: number
  confidence_score: number
  reference_class: string | null
  side: 'YES' | 'NO'
  edge_bps: number | null
  bull_argument: string | null
  bear_argument: string | null
  category: string | null
  status: string
}

// ---------------------------------------------------------------------------
// TopBetCard
// ---------------------------------------------------------------------------

function TopBetCard({ bet }: { bet: PMTopBet }) {
  const [expanded, setExpanded] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [side, setSide] = useState<'YES' | 'NO'>(bet.side ?? 'YES')
  const [amount, setAmount] = useState('10')

  const execute = useMutation({
    mutationFn: async () =>
      api.post(`/api/polymarket/top-bets/${bet.id}/accept`, {
        side,
        amount_usd: Number(amount),
      }),
    onSuccess: () => {
      toast.success('Paper bet placed successfully!')
      setModalOpen(false)
    },
    onError: () => toast.error('Failed to place bet'),
  })

  const yesPct = Math.round(bet.yes_probability * 100)
  const noPct = Math.round(bet.no_probability * 100)
  const confPct = Math.round(bet.confidence_score * 100)

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium leading-snug">{bet.question}</p>
          <div className="mt-1 flex flex-wrap gap-1">
            <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground uppercase">
              {bet.venue}
            </span>
            {bet.reference_class && (
              <span className="inline-flex items-center rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30 px-2 py-0.5 text-[10px] font-medium">
                {bet.reference_class}
              </span>
            )}
            {bet.category && bet.category !== bet.reference_class && (
              <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                {bet.category}
              </span>
            )}
          </div>
        </div>
        <span
          className={cn(
            'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold shrink-0',
            confPct >= 80
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
              : confPct >= 60
              ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/30'
              : 'bg-muted text-muted-foreground',
          )}
        >
          {confPct}% conf
        </span>
      </div>

      {/* Probability bars */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-xs">
          <span className="w-6 font-semibold text-emerald-400">YES</span>
          <div className="flex-1 h-2 rounded-full bg-muted/60 overflow-hidden">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${yesPct}%` }}
            />
          </div>
          <span className="w-8 text-right tabular-nums text-muted-foreground">{yesPct}%</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="w-6 font-semibold text-red-400">NO</span>
          <div className="flex-1 h-2 rounded-full bg-muted/60 overflow-hidden">
            <div
              className="h-full rounded-full bg-red-500 transition-all duration-300"
              style={{ width: `${noPct}%` }}
            />
          </div>
          <span className="w-8 text-right tabular-nums text-muted-foreground">{noPct}%</span>
        </div>
      </div>

      {/* Edge */}
      {bet.edge_bps !== null && (
        <p className="text-[11px] text-muted-foreground">
          Edge: <span className="font-medium text-foreground">{bet.edge_bps} bps</span>
        </p>
      )}

      {/* Actions row */}
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => setModalOpen(true)} className="flex-1">
          <TrendingUp className="mr-1 h-3.5 w-3.5" />
          Place Bet
        </Button>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted/40 transition-colors"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          AI Reasoning
        </button>
      </div>

      {/* Expandable reasoning */}
      {expanded && (
        <div className="space-y-2 rounded-lg bg-muted/30 p-3 text-xs">
          {bet.bull_argument && (
            <div>
              <p className="font-semibold text-emerald-400 mb-0.5">🐂 Bull case</p>
              <p className="text-muted-foreground leading-relaxed">{bet.bull_argument}</p>
            </div>
          )}
          {bet.bear_argument && (
            <div>
              <p className="font-semibold text-red-400 mb-0.5">🐻 Bear case</p>
              <p className="text-muted-foreground leading-relaxed">{bet.bear_argument}</p>
            </div>
          )}
          {!bet.bull_argument && !bet.bear_argument && (
            <p className="text-muted-foreground">No AI reasoning available yet.</p>
          )}
        </div>
      )}

      {/* Place Bet modal */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Place Paper Bet</DialogTitle>
            <DialogDescription>
              Paper-mode simulation only — no real money is committed.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm font-medium leading-snug">{bet.question}</p>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setSide('YES')}
                className={cn(
                  'rounded-lg border p-3 text-sm font-semibold transition-colors',
                  side === 'YES'
                    ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400'
                    : 'border-border text-muted-foreground hover:border-muted-foreground',
                )}
              >
                YES ({yesPct}%)
              </button>
              <button
                type="button"
                onClick={() => setSide('NO')}
                className={cn(
                  'rounded-lg border p-3 text-sm font-semibold transition-colors',
                  side === 'NO'
                    ? 'border-red-500 bg-red-500/10 text-red-400'
                    : 'border-border text-muted-foreground hover:border-muted-foreground',
                )}
              >
                NO ({noPct}%)
              </button>
            </div>
            <div className="space-y-1">
              <Label htmlFor="bet-amount">Amount (USD)</Label>
              <Input
                id="bet-amount"
                type="number"
                min="1"
                step="1"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
            <div className="rounded-md bg-blue-500/10 border border-blue-500/20 p-2 text-[11px] text-blue-300">
              📄 <strong>Paper mode only</strong> — this simulates a trade without real funds.
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => execute.mutate()}
              disabled={execute.isPending || !amount || Number(amount) <= 0}
            >
              {execute.isPending ? 'Placing…' : `Place ${side} bet`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TopBetsPanel (exported)
// ---------------------------------------------------------------------------

interface TopBetsPanelProps {
  venue?: VenueId
}

export function TopBetsPanel({ venue = 'all' }: TopBetsPanelProps) {
  const params: Record<string, string> = {}
  if (venue !== 'all') params.venue = venue

  const { data, isLoading } = useQuery({
    queryKey: ['pm-top-bets', venue],
    queryFn: async () =>
      (await api.get<PMTopBet[]>('/api/polymarket/top-bets', { params })).data,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="rounded-xl border border-border bg-card p-4 animate-pulse space-y-3"
          >
            <div className="h-4 bg-muted rounded w-3/4" />
            <div className="h-3 bg-muted rounded w-1/2" />
            <div className="h-2 bg-muted rounded" />
            <div className="h-2 bg-muted rounded w-4/5" />
            <div className="h-8 bg-muted rounded" />
          </div>
        ))}
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/50 p-8 text-center">
        <p className="text-sm text-muted-foreground">
          No top bets available right now. The agent may be scanning.
        </p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {data.map((bet) => (
        <TopBetCard key={bet.id} bet={bet} />
      ))}
    </div>
  )
}
