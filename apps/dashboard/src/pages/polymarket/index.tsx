/**
 * Polymarket — v1.0 dashboard tab (Phase 12).
 *
 * Tabs: Markets, Strategies, Orders, Positions, Promotion, Briefing, Risk.
 * Top-right kill switch with confirm dialog. Jurisdiction attestation banner
 * shown when missing/expired. Backed by /api/polymarket/* (Phase 10 routes).
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import {
  ShieldAlert,
  Info,
  Activity,
  Pause,
  Play,
  ArrowUpCircle,
  RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { VenueSelectorPills, type VenueId } from './VenueSelectorPills'
import { TopBetsPanel } from './TopBetsPanel'
import { ChatTab } from './ChatTab'
import { LogsTab } from './LogsTab'

// ---------------------------------------------------------------------------
// Types (mirror Phase 10 response shapes — kept loose on purpose)
// ---------------------------------------------------------------------------

interface PMMarket {
  id: string
  venue: string
  venue_market_id: string
  slug: string | null
  question: string
  category: string | null
  outcomes: unknown[]
  total_volume: number | null
  liquidity_usd: number | null
  expiry: string | null
  oracle_type: string | null
  is_active: boolean
  last_scanned_at: string | null
}

interface PMMarketsList {
  markets: PMMarket[]
  total: number
  request_id: string
}

interface PMResolutionScore {
  final_score: number | null
  tradeable: boolean
  rationale: string | null
  oracle_type: string | null
  prior_disputes: number
  scored_at: string | null
}

interface PMStrategy {
  id: string
  strategy_id: string
  archetype: string
  mode: string
  bankroll_usd: number
  max_strategy_notional_usd: number
  max_trade_notional_usd: number
  kelly_cap: number
  min_edge_bps: number | null
  paused: boolean
}

interface PMOrder {
  id: string
  pm_strategy_id: string
  pm_market_id: string
  outcome_token_id: string
  side: string
  qty_shares: number
  limit_price: number
  mode: string
  status: string
  venue_order_id: string | null
  fees_paid_usd: number | null
  slippage_bps: number | null
  f9_score: number | null
  arb_group_id: string | null
  submitted_at: string | null
  filled_at: string | null
  cancelled_at: string | null
}

interface PMPosition {
  id: string
  pm_strategy_id: string
  pm_market_id: string
  outcome_token_id: string
  qty_shares: number
  avg_entry_price: number
  mode: string
  unrealized_pnl_usd: number | null
  realized_pnl_usd: number | null
  opened_at: string | null
  closed_at: string | null
}

interface PMPromotionAuditRow {
  id: string
  action: string
  outcome: string
  previous_mode: string | null
  new_mode: string | null
  gate_evaluations: Record<string, unknown>
  created_at: string | null
}

interface PMJurisdiction {
  valid: boolean
  valid_until?: string | null
}

interface PMKillStatus {
  active: boolean
  reason: string | null
  activated_at: string | null
  scope: string
}

interface PMBriefingSection {
  date: string | null
  movers: unknown[]
  new_high_volume: unknown[]
  resolutions_24h: unknown[]
  f9_risks: unknown[]
  paper_pnl: number
  live_pnl: number
  kill_switch: { active: boolean; reason: string | null }
}

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------

function Pill({
  children,
  tone = 'default',
}: {
  children: React.ReactNode
  tone?: 'default' | 'good' | 'warn' | 'bad' | 'info'
}) {
  const tones: Record<string, string> = {
    default: 'bg-muted text-muted-foreground',
    good: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30',
    warn: 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/30',
    bad: 'bg-red-500/10 text-red-400 border border-red-500/30',
    info: 'bg-blue-500/10 text-blue-400 border border-blue-500/30',
  }
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium', tones[tone])}>
      {children}
    </span>
  )
}

function fmtUsd(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function fmtNum(v: number | null | undefined, digits = 2) {
  if (v === null || v === undefined) return '—'
  return v.toFixed(digits)
}

function fmtTime(v: string | null | undefined) {
  if (!v) return '—'
  try {
    return new Date(v).toLocaleString()
  } catch {
    return v
  }
}

// ---------------------------------------------------------------------------
// F9 (resolution risk) badge — fetched lazily per market id
// ---------------------------------------------------------------------------

function F9Badge({ marketId }: { marketId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['pm-resolution-risk', marketId],
    queryFn: async () => {
      const res = await api.get<PMResolutionScore>(`/api/polymarket/markets/${marketId}/resolution-risk`)
      return res.data
    },
    retry: false,
    staleTime: 60_000,
  })
  if (isLoading) return <Pill tone="default">F9 …</Pill>
  if (isError || !data) return <Pill tone="default">F9 n/a</Pill>
  const score = data.final_score
  if (score === null || score === undefined) return <Pill tone="default">F9 n/a</Pill>
  const tone: 'good' | 'warn' | 'bad' = data.tradeable ? (score >= 0.8 ? 'good' : 'warn') : 'bad'
  return (
    <Pill tone={tone}>
      F9 {score.toFixed(2)}
      {!data.tradeable && ' • blocked'}
    </Pill>
  )
}

// ---------------------------------------------------------------------------
// Jurisdiction banner
// ---------------------------------------------------------------------------

function JurisdictionBanner() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['pm-jurisdiction'],
    queryFn: async () => (await api.get<PMJurisdiction>('/api/polymarket/jurisdiction/current')).data,
  })
  const [open, setOpen] = useState(false)
  const [ack, setAck] = useState(false)
  const [text, setText] = useState('')

  const mut = useMutation({
    mutationFn: async () =>
      api.post('/api/polymarket/jurisdiction/attest', {
        ack_geoblock: true,
        attestation_text_hash: text || 'ATTEST-V1',
      }),
    onSuccess: () => {
      toast.success('Jurisdiction attestation recorded')
      setOpen(false)
      setAck(false)
      setText('')
      qc.invalidateQueries({ queryKey: ['pm-jurisdiction'] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'attestation failed'
      toast.error(msg)
    },
  })

  if (data?.valid) return null

  return (
    <>
      <div className="flex items-start gap-3 rounded-xl border border-blue-500/40 bg-blue-500/10 p-4">
        <Info className="h-5 w-5 shrink-0 text-blue-400" />
        <div className="flex-1">
          <p className="text-sm font-semibold text-blue-200">
            Prediction Markets — informational notice
          </p>
          <p className="mt-1 text-xs text-blue-100/80">
            Prediction Markets are available in the US via Robinhood (primary) and Polymarket
            (secondary). All trades in this tab are paper mode only. Record a jurisdiction
            attestation to confirm you understand the applicable terms.
          </p>
        </div>
        <Button size="sm" onClick={() => setOpen(true)}>
          Attest
        </Button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Jurisdiction attestation</DialogTitle>
            <DialogDescription>
              Confirm you understand Polymarket access restrictions and that you are solely
              responsible for compliance with the laws of your jurisdiction.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={ack}
                onChange={(e) => setAck(e.target.checked)}
                className="mt-1"
              />
              <span>
                I acknowledge the geo-block, accept full responsibility, and confirm I am not
                accessing this from a restricted jurisdiction.
              </span>
            </label>
            <div className="space-y-1">
              <Label htmlFor="attest-text">Attestation phrase (optional)</Label>
              <Input
                id="attest-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="ATTEST-V1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button disabled={!ack || mut.isPending} onClick={() => mut.mutate()}>
              {mut.isPending ? 'Submitting…' : 'Submit attestation'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ---------------------------------------------------------------------------
// Kill switch
// ---------------------------------------------------------------------------

function KillSwitchButton() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['pm-kill-status'],
    queryFn: async () => (await api.get<PMKillStatus>('/api/polymarket/kill-switch/status')).data,
    refetchInterval: 15_000,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [rearmOpen, setRearmOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [confirmText, setConfirmText] = useState('')

  const activate = useMutation({
    mutationFn: async () =>
      api.post('/api/polymarket/kill-switch/activate', { reason: reason || 'manual' }),
    onSuccess: () => {
      toast.success('Polymarket kill switch ACTIVATED')
      setConfirmOpen(false)
      setReason('')
      qc.invalidateQueries({ queryKey: ['pm-kill-status'] })
    },
    onError: () => toast.error('Failed to activate kill switch'),
  })

  const deactivate = useMutation({
    mutationFn: async () =>
      api.post('/api/polymarket/kill-switch/deactivate', { typed_confirmation: confirmText }),
    onSuccess: () => {
      toast.success('Polymarket kill switch rearmed')
      setRearmOpen(false)
      setConfirmText('')
      qc.invalidateQueries({ queryKey: ['pm-kill-status'] })
    },
    onError: () => toast.error('Rearm failed — must type REARM exactly'),
  })

  const active = !!data?.active

  return (
    <>
      {active ? (
        <Button variant="outline" className="border-red-500/50 text-red-400" onClick={() => setRearmOpen(true)}>
          <ShieldAlert className="mr-1 h-4 w-4" />
          Kill Switch ACTIVE — Rearm
        </Button>
      ) : (
        <Button variant="destructive" onClick={() => setConfirmOpen(true)}>
          <ShieldAlert className="mr-1 h-4 w-4" />
          Kill Switch
        </Button>
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Activate Polymarket kill switch?</DialogTitle>
            <DialogDescription>
              All Polymarket strategies will halt within 2 seconds. Open orders are cancelled
              where possible. This event is logged.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="kill-reason">Reason</Label>
            <Input
              id="kill-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="manual halt — investigating"
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => activate.mutate()} disabled={activate.isPending}>
              {activate.isPending ? 'Activating…' : 'Activate'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rearmOpen} onOpenChange={setRearmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rearm Polymarket kill switch?</DialogTitle>
            <DialogDescription>
              Type <code className="font-mono">REARM</code> to confirm. Strategies remain paused
              until manually resumed.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="rearm-text">Confirmation</Label>
            <Input
              id="rearm-text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value.toUpperCase())}
              placeholder="REARM"
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRearmOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => deactivate.mutate()} disabled={confirmText !== 'REARM' || deactivate.isPending}>
              {deactivate.isPending ? 'Rearming…' : 'Rearm'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ---------------------------------------------------------------------------
// Markets tab
// ---------------------------------------------------------------------------

function MarketsTab() {
  const qc = useQueryClient()
  // BUG-2: Markets tab filters are URL-shareable via query params, so a user
  // can copy/paste the URL and reproduce the same filtered view.
  const [searchParams, setSearchParams] = useSearchParams()
  const category = searchParams.get('category') ?? ''
  const minVolume = searchParams.get('min_volume') ?? ''
  const tradeableOnly = searchParams.get('tradeable_only') === '1'
  const [selectedVenue, setSelectedVenue] = useState<VenueId>('all')

  const updateParam = (key: string, value: string | boolean) => {
    const next = new URLSearchParams(searchParams)
    const str = typeof value === 'boolean' ? (value ? '1' : '') : value
    if (str) next.set(key, str)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }
  const setCategory = (v: string) => updateParam('category', v)
  const setMinVolume = (v: string) => updateParam('min_volume', v)
  const setTradeableOnly = (v: boolean) => updateParam('tradeable_only', v)

  const { data, isLoading } = useQuery({
    queryKey: ['pm-markets', category, minVolume, tradeableOnly],
    queryFn: async () => {
      const params: Record<string, string | number | boolean> = { limit: 100 }
      if (category) params.category = category
      if (minVolume) params.min_volume = Number(minVolume)
      if (tradeableOnly) params.tradeable_only = true
      const res = await api.get<PMMarketsList>('/api/polymarket/markets', { params })
      return res.data
    },
    refetchInterval: 30_000,
  })

  const scan = useMutation({
    mutationFn: async () => api.post('/api/polymarket/markets/scan', { venue: 'polymarket' }),
    onSuccess: () => {
      toast.success('Scan triggered')
      qc.invalidateQueries({ queryKey: ['pm-markets'] })
    },
    onError: () => toast.error('Scan failed'),
  })

  return (
    <div className="space-y-4">
      {/* Venue selector + Top Bets Panel */}
      <div className="space-y-3">
        <VenueSelectorPills selected={selectedVenue} onChange={setSelectedVenue} />
        <div className="rounded-xl border border-border bg-card p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Activity className="h-4 w-4 text-purple-400" />
            Top Bets
          </h3>
          <TopBetsPanel venue={selectedVenue} />
        </div>
      </div>

      {/* Existing market list */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
        <div className="space-y-1">
          <Label htmlFor="cat">Category</Label>
          <Input id="cat" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="all" className="w-40" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="vol">Min volume (USD)</Label>
          <Input id="vol" value={minVolume} onChange={(e) => setMinVolume(e.target.value)} placeholder="0" className="w-32" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={tradeableOnly} onChange={(e) => setTradeableOnly(e.target.checked)} />
          Tradeable only (F9)
        </label>
        <div className="ml-auto">
          <Button size="sm" variant="outline" onClick={() => scan.mutate()} disabled={scan.isPending}>
            <RefreshCw className={cn('mr-1 h-4 w-4', scan.isPending && 'animate-spin')} />
            Force scan
          </Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-muted/40 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Question</th>
              <th className="px-3 py-2">Category</th>
              <th className="px-3 py-2 text-right">Volume</th>
              <th className="px-3 py-2 text-right">Liquidity</th>
              <th className="px-3 py-2">Expiry</th>
              <th className="px-3 py-2">F9</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {!isLoading && (data?.markets.length ?? 0) === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                  No markets match the current filters.
                </td>
              </tr>
            )}
            {data?.markets.map((m) => (
              <tr key={m.id} className="hover:bg-muted/30">
                <td className="max-w-[420px] px-3 py-2">
                  <div className="truncate font-medium" title={m.question}>
                    {m.question}
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground">{m.slug ?? m.venue_market_id}</div>
                </td>
                <td className="px-3 py-2 text-xs">{m.category ?? '—'}</td>
                <td className="px-3 py-2 text-right">{fmtUsd(m.total_volume)}</td>
                <td className="px-3 py-2 text-right">{fmtUsd(m.liquidity_usd)}</td>
                <td className="px-3 py-2 text-xs">{fmtTime(m.expiry)}</td>
                <td className="px-3 py-2">
                  <F9Badge marketId={m.id} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && (
        <div className="text-right text-[11px] text-muted-foreground">
          Showing {data.markets.length} of {data.total} markets
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Strategies tab
// ---------------------------------------------------------------------------

function StrategyCard({ s, onChanged }: { s: PMStrategy; onChanged: () => void }) {
  const [promoteOpen, setPromoteOpen] = useState(false)
  const [maxNotional, setMaxNotional] = useState('500')
  const [confirmText, setConfirmText] = useState('')
  const [ackRisk, setAckRisk] = useState(false)

  const pause = useMutation({
    mutationFn: async () => api.post(`/api/polymarket/strategies/${s.id}/pause`),
    onSuccess: () => {
      toast.success('Paused')
      onChanged()
    },
    onError: () => toast.error('Pause failed'),
  })
  const resume = useMutation({
    mutationFn: async () => api.post(`/api/polymarket/strategies/${s.id}/resume`),
    onSuccess: () => {
      toast.success('Resumed')
      onChanged()
    },
    onError: () => toast.error('Resume failed'),
  })
  const promote = useMutation({
    mutationFn: async () =>
      api.post(`/api/polymarket/strategies/${s.id}/promote`, {
        typed_confirmation: confirmText,
        max_notional_first_week: Number(maxNotional),
        ack_resolution_risk: ackRisk,
      }),
    onSuccess: (res) => {
      const success = (res.data as { success?: boolean })?.success
      if (success) {
        toast.success('Strategy promoted to LIVE')
      } else {
        toast.error('Promotion blocked by gates — see audit')
      }
      setPromoteOpen(false)
      setConfirmText('')
      setAckRisk(false)
      onChanged()
    },
    onError: () => toast.error('Promotion request failed'),
  })

  const isLive = s.mode === 'LIVE'

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold">{s.archetype}</div>
          <div className="text-[11px] text-muted-foreground">{s.id.slice(0, 8)}</div>
        </div>
        <div className="flex items-center gap-2">
          <Pill tone={isLive ? 'good' : 'info'}>{isLive ? 'LIVE' : 'PAPER'}</Pill>
          {s.paused && <Pill tone="warn">paused</Pill>}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-muted-foreground">Bankroll</div>
          <div className="font-medium">{fmtUsd(s.bankroll_usd)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Strategy cap</div>
          <div className="font-medium">{fmtUsd(s.max_strategy_notional_usd)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Per-trade cap</div>
          <div className="font-medium">{fmtUsd(s.max_trade_notional_usd)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Kelly cap</div>
          <div className="font-medium">{fmtNum(s.kelly_cap)}</div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {s.paused ? (
          <Button size="sm" variant="outline" onClick={() => resume.mutate()} disabled={resume.isPending}>
            <Play className="mr-1 h-3 w-3" />
            Resume
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => pause.mutate()} disabled={pause.isPending}>
            <Pause className="mr-1 h-3 w-3" />
            Pause
          </Button>
        )}
        {!isLive && (
          <Button size="sm" onClick={() => setPromoteOpen(true)}>
            <ArrowUpCircle className="mr-1 h-3 w-3" />
            Promote
          </Button>
        )}
      </div>

      <Dialog open={promoteOpen} onOpenChange={setPromoteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Promote to LIVE</DialogTitle>
            <DialogDescription>
              Server re-validates every gate (calibration, soak time, jurisdiction, F9). Type
              the strategy archetype to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <Label>Max notional first week (USD)</Label>
              <Input value={maxNotional} onChange={(e) => setMaxNotional(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Type &quot;{s.archetype}&quot; to confirm</Label>
              <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
            </div>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={ackRisk} onChange={(e) => setAckRisk(e.target.checked)} className="mt-1" />
              <span>I understand resolution / oracle risk and accept loss of full notional.</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPromoteOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => promote.mutate()}
              disabled={!ackRisk || confirmText !== s.archetype || promote.isPending}
            >
              {promote.isPending ? 'Submitting…' : 'Promote'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function StrategiesTab() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['pm-strategies'],
    queryFn: async () => (await api.get<PMStrategy[]>('/api/polymarket/strategies')).data,
    refetchInterval: 15_000,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['pm-strategies'] })

  if (isLoading) {
    return <div className="text-sm text-muted-foreground">Loading strategies…</div>
  }
  if (!data || data.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
        No Polymarket strategies registered yet.
      </div>
    )
  }
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {data.map((s) => (
        <StrategyCard key={s.id} s={s} onChanged={refresh} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Orders tab
// ---------------------------------------------------------------------------

function OrdersTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['pm-orders'],
    queryFn: async () => (await api.get<PMOrder[]>('/api/polymarket/orders', { params: { limit: 200 } })).data,
    refetchInterval: 15_000,
  })
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-muted/40 text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Submitted</th>
            <th className="px-3 py-2">Mode</th>
            <th className="px-3 py-2">Side</th>
            <th className="px-3 py-2 text-right">Qty</th>
            <th className="px-3 py-2 text-right">Limit</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2 text-right">Fees</th>
            <th className="px-3 py-2 text-right">Slip bps</th>
            <th className="px-3 py-2 text-right">F9</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {isLoading && (
            <tr>
              <td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">
                Loading…
              </td>
            </tr>
          )}
          {!isLoading && (data?.length ?? 0) === 0 && (
            <tr>
              <td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">
                No orders.
              </td>
            </tr>
          )}
          {data?.map((o) => (
            <tr key={o.id} className="hover:bg-muted/30">
              <td className="px-3 py-2 text-xs">{fmtTime(o.submitted_at)}</td>
              <td className="px-3 py-2">
                <Pill tone={o.mode === 'LIVE' ? 'good' : 'info'}>{o.mode}</Pill>
              </td>
              <td className="px-3 py-2 text-xs">{o.side}</td>
              <td className="px-3 py-2 text-right">{fmtNum(o.qty_shares, 0)}</td>
              <td className="px-3 py-2 text-right">{fmtNum(o.limit_price, 4)}</td>
              <td className="px-3 py-2 text-xs">{o.status}</td>
              <td className="px-3 py-2 text-right">{fmtUsd(o.fees_paid_usd)}</td>
              <td className="px-3 py-2 text-right">{fmtNum(o.slippage_bps, 1)}</td>
              <td className="px-3 py-2 text-right">{fmtNum(o.f9_score)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Positions tab
// ---------------------------------------------------------------------------

function PositionsTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['pm-positions'],
    queryFn: async () => (await api.get<PMPosition[]>('/api/polymarket/positions')).data,
    refetchInterval: 15_000,
  })
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-muted/40 text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Opened</th>
            <th className="px-3 py-2">Mode</th>
            <th className="px-3 py-2 text-right">Qty</th>
            <th className="px-3 py-2 text-right">Avg entry</th>
            <th className="px-3 py-2 text-right">Unrealized</th>
            <th className="px-3 py-2 text-right">Realized</th>
            <th className="px-3 py-2">Closed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {isLoading && (
            <tr>
              <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                Loading…
              </td>
            </tr>
          )}
          {!isLoading && (data?.length ?? 0) === 0 && (
            <tr>
              <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                No positions.
              </td>
            </tr>
          )}
          {data?.map((p) => (
            <tr key={p.id} className="hover:bg-muted/30">
              <td className="px-3 py-2 text-xs">{fmtTime(p.opened_at)}</td>
              <td className="px-3 py-2">
                <Pill tone={p.mode === 'LIVE' ? 'good' : 'info'}>{p.mode}</Pill>
              </td>
              <td className="px-3 py-2 text-right">{fmtNum(p.qty_shares, 0)}</td>
              <td className="px-3 py-2 text-right">{fmtNum(p.avg_entry_price, 4)}</td>
              <td className="px-3 py-2 text-right">{fmtUsd(p.unrealized_pnl_usd)}</td>
              <td className="px-3 py-2 text-right">{fmtUsd(p.realized_pnl_usd)}</td>
              <td className="px-3 py-2 text-xs">{fmtTime(p.closed_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Promotion tab — strategy picker + audit history + last gate evaluation
// ---------------------------------------------------------------------------

function PromotionTab() {
  const { data: strategies = [] } = useQuery({
    queryKey: ['pm-strategies'],
    queryFn: async () => (await api.get<PMStrategy[]>('/api/polymarket/strategies')).data,
  })
  const [selected, setSelected] = useState<string | null>(null)
  const effectiveId = selected ?? strategies[0]?.id ?? null

  const { data: audit = [] } = useQuery({
    queryKey: ['pm-promotion-audit', effectiveId],
    queryFn: async () =>
      effectiveId
        ? (await api.get<PMPromotionAuditRow[]>(`/api/polymarket/strategies/${effectiveId}/promotion_audit`)).data
        : [],
    enabled: !!effectiveId,
    refetchInterval: 15_000,
  })

  const lastGate = useMemo(() => {
    const last = audit[0]
    return last?.gate_evaluations ?? null
  }, [audit])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-3">
        <Label className="text-xs uppercase text-muted-foreground">Strategy</Label>
        <select
          className="rounded-md border border-border bg-background px-2 py-1 text-sm"
          value={effectiveId ?? ''}
          onChange={(e) => setSelected(e.target.value)}
        >
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>
              {s.archetype} — {s.id.slice(0, 8)} ({s.mode})
            </option>
          ))}
          {strategies.length === 0 && <option value="">no strategies</option>}
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-4">
          <h3 className="text-sm font-semibold">Last gate evaluation</h3>
          {lastGate ? (
            <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted/40 p-3 text-[11px] leading-relaxed">
              {JSON.stringify(lastGate, null, 2)}
            </pre>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">No promotion attempts yet.</p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-4">
          <h3 className="text-sm font-semibold">Audit history</h3>
          {audit.length === 0 && (
            <p className="mt-2 text-xs text-muted-foreground">No audit rows.</p>
          )}
          <ul className="mt-2 space-y-2 text-xs">
            {audit.map((a) => (
              <li key={a.id} className="rounded-md border border-border/60 bg-muted/20 p-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{a.action}</span>
                  <Pill tone={a.outcome === 'success' ? 'good' : 'bad'}>{a.outcome}</Pill>
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  {a.previous_mode ?? '—'} → {a.new_mode ?? '—'} · {fmtTime(a.created_at)}
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Briefing tab
// ---------------------------------------------------------------------------

function BriefingTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['pm-briefing-section'],
    queryFn: async () => (await api.get<PMBriefingSection>('/api/polymarket/briefing/section')).data,
    refetchInterval: 60_000,
  })
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading…</div>
  if (!data) return <div className="text-sm text-muted-foreground">No briefing data.</div>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="text-[11px] uppercase text-muted-foreground">Paper P&amp;L</div>
          <div className="mt-1 text-2xl font-bold">{fmtUsd(data.paper_pnl)}</div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="text-[11px] uppercase text-muted-foreground">Live P&amp;L</div>
          <div className="mt-1 text-2xl font-bold">{fmtUsd(data.live_pnl)}</div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="text-[11px] uppercase text-muted-foreground">Movers</div>
          <div className="mt-1 text-2xl font-bold">{data.movers.length}</div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="text-[11px] uppercase text-muted-foreground">F9 risks</div>
          <div className="mt-1 text-2xl font-bold">{data.f9_risks.length}</div>
        </div>
      </div>
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-sm font-semibold">Kill switch</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {data.kill_switch.active ? `ACTIVE — ${data.kill_switch.reason ?? 'no reason'}` : 'idle'}
        </p>
      </div>
      <pre className="overflow-auto rounded-xl border border-border bg-card p-4 text-[11px]">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Risk tab — global PM risk view: kill switch + jurisdiction + paused strats
// ---------------------------------------------------------------------------

function RiskTab() {
  // Shares cache with KillSwitchButton via same queryKey — no second poller.
  const { data: kill } = useQuery({
    queryKey: ['pm-kill-status'],
    queryFn: async () => (await api.get<PMKillStatus>('/api/polymarket/kill-switch/status')).data,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })
  const { data: juris } = useQuery({
    queryKey: ['pm-jurisdiction'],
    queryFn: async () => (await api.get<PMJurisdiction>('/api/polymarket/jurisdiction/current')).data,
  })
  const { data: strategies = [] } = useQuery({
    queryKey: ['pm-strategies'],
    queryFn: async () => (await api.get<PMStrategy[]>('/api/polymarket/strategies')).data,
  })

  const paused = strategies.filter((s) => s.paused)
  const live = strategies.filter((s) => s.mode === 'LIVE')

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-sm font-semibold">Kill switch</h3>
        <div className="mt-2 flex items-center gap-2">
          <Pill tone={kill?.active ? 'bad' : 'good'}>{kill?.active ? 'ACTIVE' : 'idle'}</Pill>
          {kill?.activated_at && <span className="text-[11px] text-muted-foreground">{fmtTime(kill.activated_at)}</span>}
        </div>
        {kill?.reason && <p className="mt-1 text-xs text-muted-foreground">{kill.reason}</p>}
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-sm font-semibold">Jurisdiction</h3>
        <div className="mt-2 flex items-center gap-2">
          <Pill tone={juris?.valid ? 'good' : 'bad'}>{juris?.valid ? 'attested' : 'missing/expired'}</Pill>
          {juris?.valid_until && <span className="text-[11px] text-muted-foreground">until {fmtTime(juris.valid_until)}</span>}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-4 md:col-span-2">
        <h3 className="text-sm font-semibold">Strategy status</h3>
        <div className="mt-2 grid grid-cols-3 gap-3 text-xs">
          <div>
            <div className="text-muted-foreground">Total</div>
            <div className="text-xl font-bold">{strategies.length}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Live</div>
            <div className="text-xl font-bold text-emerald-400">{live.length}</div>
          </div>
          <div>
            <div className="text-muted-foreground">Paused</div>
            <div className="text-xl font-bold text-yellow-400">{paused.length}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PolymarketPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Activity className="h-6 w-6 text-purple-500" />
            Prediction Markets
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Prediction-market scanner, strategies, orders, positions, promotion gate, chat, and logs.
          </p>
        </div>
        <KillSwitchButton />
      </div>

      <JurisdictionBanner />

      <Tabs defaultValue="markets" className="space-y-4">
        <TabsList>
          <TabsTrigger value="markets">Markets</TabsTrigger>
          <TabsTrigger value="strategies">Strategies</TabsTrigger>
          <TabsTrigger value="orders">Orders</TabsTrigger>
          <TabsTrigger value="positions">Positions</TabsTrigger>
          <TabsTrigger value="promotion">Promotion</TabsTrigger>
          <TabsTrigger value="briefing">Briefing</TabsTrigger>
          <TabsTrigger value="risk">Risk</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>
        <TabsContent value="markets">
          <MarketsTab />
        </TabsContent>
        <TabsContent value="strategies">
          <StrategiesTab />
        </TabsContent>
        <TabsContent value="orders">
          <OrdersTab />
        </TabsContent>
        <TabsContent value="positions">
          <PositionsTab />
        </TabsContent>
        <TabsContent value="promotion">
          <PromotionTab />
        </TabsContent>
        <TabsContent value="briefing">
          <BriefingTab />
        </TabsContent>
        <TabsContent value="risk">
          <RiskTab />
        </TabsContent>
        <TabsContent value="chat">
          <ChatTab />
        </TabsContent>
        <TabsContent value="logs">
          <LogsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
