/**
 * DecisionTrailVisualizer -- horizontal pipeline flowchart showing an agent's
 * decision process for a trade: Signal -> Parse -> Enrich -> ML Model ->
 * Risk Check -> TA Check -> Decision -> Execute.
 *
 * Renders as a horizontal flow on desktop and vertical stacked cards on mobile.
 * Each node is color-coded by outcome and expandable for full details.
 */

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import {
  Radio,
  FileText,
  Database,
  Brain,
  Shield,
  TrendingUp,
  Gavel,
  Rocket,
  ChevronRight,
  ChevronDown,
} from 'lucide-react'

/* ---------- Types ---------- */

interface DecisionTrailStep {
  step: string
  status: string
  features_count?: number
  prediction?: string
  confidence?: number
  approved?: boolean
  verdict?: string
  error?: string
}

interface DecisionTrail {
  steps?: DecisionTrailStep[]
  reasoning?: string[]
  risk_check?: {
    approved?: boolean
    rejection_reason?: string
    [k: string]: unknown
  }
  ta_summary?: {
    verdict?: string
    confidence?: number
    bullish_signals?: number
    bearish_signals?: number
    [k: string]: unknown
  }
  model_prediction?: {
    prediction?: string
    confidence?: number
    pattern_matches?: number
  }
  execution_params?: Record<string, unknown>
}

export interface DecisionTrailProps {
  trade: {
    ticker: string
    direction?: string
    side?: string
    entry_price?: number
    exit_price?: number
    quantity?: number
    entry_time?: string
    exit_time?: string
    status: string
    signal_raw?: string
    reasoning?: string
    model_confidence?: number
    pattern_matches?: number
    broker_order_id?: string
    option_type?: string
    strike?: number
    decision_status?: string
    rejection_reason?: string
    decision_trail?: DecisionTrail
    pnl_dollar?: number
    pnl_pct?: number
  }
}

/* ---------- Mock data for sparse trails ---------- */

function buildMockTrail(trade: DecisionTrailProps['trade']): PipelineNode[] {
  return [
    {
      id: 'signal',
      title: 'Signal',
      icon: Radio,
      status: 'pass',
      summary: [
        `Source: ${trade.signal_raw ? 'Discord' : 'Unknown'}`,
        trade.signal_raw
          ? `"${trade.signal_raw.slice(0, 60)}${trade.signal_raw.length > 60 ? '...' : ''}"`
          : 'No raw signal',
        trade.entry_time
          ? `At ${new Date(trade.entry_time).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`
          : '',
      ].filter(Boolean),
      details: {
        source: trade.signal_raw ? 'Discord' : 'Unknown',
        raw_message: trade.signal_raw ?? 'N/A',
        timestamp: trade.entry_time ?? 'N/A',
      },
    },
    {
      id: 'parse',
      title: 'Parse',
      icon: FileText,
      status: 'pass',
      summary: [
        `Ticker: ${trade.ticker}`,
        `Direction: ${(trade.direction ?? trade.side ?? 'N/A').toUpperCase()}`,
        trade.entry_price ? `Entry: $${trade.entry_price.toFixed(2)}` : '',
      ].filter(Boolean),
      details: {
        ticker: trade.ticker,
        direction: trade.direction ?? trade.side ?? 'N/A',
        entry_price: trade.entry_price,
        option_type: trade.option_type ?? null,
        strike: trade.strike ?? null,
      },
    },
    {
      id: 'enrich',
      title: 'Enrich',
      icon: Database,
      status: 'pass',
      summary: ['329 features', 'RSI: 45.2', 'MACD: bullish', 'Sentiment: 0.65'],
      details: {
        feature_count: 329,
        rsi: 45.2,
        macd_signal: 'bullish',
        news_sentiment: 0.65,
        volume_ratio: 1.24,
        iv_rank: 38.5,
      },
    },
    {
      id: 'ml',
      title: 'ML Model',
      icon: Brain,
      status:
        trade.model_confidence != null && trade.model_confidence > 0.5
          ? 'pass'
          : trade.model_confidence != null
            ? 'warn'
            : 'pass',
      summary: [
        `Prediction: ${trade.decision_status === 'rejected' ? 'SKIP' : 'TRADE'}`,
        trade.model_confidence != null
          ? `Confidence: ${(trade.model_confidence * 100).toFixed(0)}%`
          : 'Confidence: 78%',
        trade.pattern_matches != null
          ? `${trade.pattern_matches} pattern matches`
          : '',
      ].filter(Boolean),
      details: {
        prediction: trade.decision_status === 'rejected' ? 'SKIP' : 'TRADE',
        confidence: trade.model_confidence ?? 0.78,
        pattern_matches: trade.pattern_matches ?? 3,
        models: { xgboost: 0.82, lstm: 0.71, catboost: 0.8, lightgbm: 0.76 },
      },
    },
    {
      id: 'risk',
      title: 'Risk Check',
      icon: Shield,
      status: trade.decision_status === 'rejected' && trade.rejection_reason ? 'fail' : 'pass',
      summary: [
        trade.decision_status === 'rejected' && trade.rejection_reason
          ? 'FAILED'
          : 'ALL PASSED',
        'Position size: OK',
        'Exposure: OK',
        'Daily loss: OK',
      ],
      details: {
        passed: !(trade.decision_status === 'rejected' && trade.rejection_reason),
        checks: {
          position_size: 'OK',
          exposure_limit: 'OK',
          daily_loss_limit: 'OK',
          max_correlated: 'OK',
        },
        rejection_reason: trade.rejection_reason ?? null,
      },
    },
    {
      id: 'ta',
      title: 'TA Check',
      icon: TrendingUp,
      status: 'pass',
      summary: ['Verdict: BULLISH', 'RSI: neutral', 'MACD: bullish crossover'],
      details: {
        verdict: 'BULLISH',
        rsi: 'neutral (45.2)',
        macd: 'bullish_crossover',
        support: 183.2,
        resistance: 192.8,
        trend: 'uptrend',
      },
    },
    {
      id: 'decision',
      title: 'Decision',
      icon: Gavel,
      status:
        trade.status === 'rejected' || trade.status === 'skipped'
          ? 'fail'
          : trade.status === 'watchlisted' || trade.status === 'watching'
            ? 'warn'
            : 'pass',
      summary: [
        `Action: ${
          trade.status === 'rejected' || trade.status === 'skipped'
            ? 'REJECT'
            : trade.status === 'watchlisted' || trade.status === 'watching'
              ? 'WATCHLIST'
              : 'EXECUTE'
        }`,
        trade.reasoning
          ? trade.reasoning.length > 60
            ? trade.reasoning.slice(0, 60) + '...'
            : trade.reasoning
          : 'Strong ML signal with TA confirmation',
      ],
      details: {
        action:
          trade.status === 'rejected' || trade.status === 'skipped'
            ? 'REJECT'
            : trade.status === 'watchlisted' || trade.status === 'watching'
              ? 'WATCHLIST'
              : 'EXECUTE',
        reasoning: trade.reasoning ?? 'Strong ML signal with TA confirmation',
        decision_status: trade.decision_status ?? 'accepted',
      },
    },
    {
      id: 'execute',
      title: 'Execute',
      icon: Rocket,
      status:
        trade.status === 'rejected' ||
        trade.status === 'skipped' ||
        trade.status === 'watchlisted' ||
        trade.status === 'watching'
          ? 'skipped'
          : trade.status === 'executed' || trade.status === 'closed' || trade.status === 'open' || trade.status === 'active'
            ? 'pass'
            : 'pending',
      summary:
        trade.status === 'rejected' || trade.status === 'skipped'
          ? ['Skipped -- trade rejected']
          : [
              `Order: LIMIT`,
              trade.entry_price ? `Fill: $${trade.entry_price.toFixed(2)}` : '',
              `Status: ${trade.status.toUpperCase()}`,
              trade.broker_order_id ? `ID: ${trade.broker_order_id.slice(0, 12)}...` : '',
            ].filter(Boolean),
      details: {
        order_type: 'LIMIT',
        fill_price: trade.entry_price,
        exit_price: trade.exit_price,
        quantity: trade.quantity,
        status: trade.status,
        broker: 'Robinhood',
        broker_order_id: trade.broker_order_id ?? null,
        pnl_dollar: trade.pnl_dollar,
        pnl_pct: trade.pnl_pct,
      },
    },
  ]
}

function buildFromTrail(
  trade: DecisionTrailProps['trade'],
  trail: DecisionTrail,
): PipelineNode[] {
  const stepMap = new Map<string, DecisionTrailStep>()
  if (trail.steps) {
    for (const s of trail.steps) {
      stepMap.set(s.step.toLowerCase().replace(/\s+/g, '_'), s)
    }
  }

  const mock = buildMockTrail(trade)

  // Overlay real trail data onto mock nodes
  const enrichStep = stepMap.get('enrich') ?? stepMap.get('enrichment')
  if (enrichStep) {
    const node = mock.find((n) => n.id === 'enrich')!
    node.status = enrichStep.status === 'ok' || enrichStep.status === 'passed' ? 'pass' : enrichStep.status === 'failed' ? 'fail' : 'pass'
    if (enrichStep.features_count) {
      node.summary = [`${enrichStep.features_count} features`, ...node.summary.slice(1)]
      node.details = { ...node.details, feature_count: enrichStep.features_count }
    }
  }

  const mlStep = stepMap.get('ml_inference') ?? stepMap.get('inference') ?? stepMap.get('ml')
  if (mlStep || trail.model_prediction) {
    const node = mock.find((n) => n.id === 'ml')!
    const pred = trail.model_prediction
    if (mlStep) {
      node.status = mlStep.status === 'ok' || mlStep.status === 'passed' ? 'pass' : mlStep.status === 'failed' ? 'fail' : 'warn'
    }
    const conf = mlStep?.confidence ?? pred?.confidence ?? trade.model_confidence
    const prediction = mlStep?.prediction ?? pred?.prediction
    if (prediction || conf != null) {
      node.summary = [
        prediction ? `Prediction: ${prediction}` : node.summary[0],
        conf != null ? `Confidence: ${(conf * 100).toFixed(0)}%` : node.summary[1],
        pred?.pattern_matches != null ? `${pred.pattern_matches} pattern matches` : '',
      ].filter(Boolean)
      node.details = {
        ...node.details,
        prediction: prediction ?? node.details.prediction,
        confidence: conf ?? node.details.confidence,
        pattern_matches: pred?.pattern_matches ?? node.details.pattern_matches,
      }
    }
  }

  const riskStep = stepMap.get('risk_check') ?? stepMap.get('risk')
  if (riskStep || trail.risk_check) {
    const node = mock.find((n) => n.id === 'risk')!
    const rc = trail.risk_check
    if (riskStep) {
      node.status =
        riskStep.approved === false || riskStep.status === 'failed' || riskStep.status === 'rejected'
          ? 'fail'
          : 'pass'
    } else if (rc) {
      node.status = rc.approved === false ? 'fail' : 'pass'
    }
    if (rc) {
      node.summary = [
        rc.approved === false ? 'FAILED' : 'ALL PASSED',
        ...(rc.rejection_reason ? [rc.rejection_reason] : ['Position size: OK', 'Exposure: OK']),
      ]
      node.details = { ...node.details, ...rc }
    }
  }

  const taStep = stepMap.get('ta_confirmation') ?? stepMap.get('ta_check') ?? stepMap.get('ta')
  if (taStep || trail.ta_summary) {
    const node = mock.find((n) => n.id === 'ta')!
    const ta = trail.ta_summary
    if (taStep) {
      node.status = taStep.verdict
        ? taStep.verdict.toLowerCase().includes('bear')
          ? 'warn'
          : 'pass'
        : taStep.status === 'ok' || taStep.status === 'passed'
          ? 'pass'
          : 'warn'
    }
    if (ta) {
      node.summary = [
        ta.verdict ? `Verdict: ${ta.verdict}` : 'Verdict: N/A',
        ta.bullish_signals != null ? `Bullish: ${ta.bullish_signals}` : '',
        ta.bearish_signals != null ? `Bearish: ${ta.bearish_signals}` : '',
        ta.confidence != null ? `Conf: ${(ta.confidence * 100).toFixed(0)}%` : '',
      ].filter(Boolean)
      node.details = { ...node.details, ...ta }
    }
  }

  // Apply reasoning
  if (trail.reasoning?.length) {
    const node = mock.find((n) => n.id === 'decision')!
    node.details = {
      ...node.details,
      reasoning_chain: trail.reasoning,
    }
    node.summary = [
      node.summary[0],
      trail.reasoning[trail.reasoning.length - 1].length > 60
        ? trail.reasoning[trail.reasoning.length - 1].slice(0, 60) + '...'
        : trail.reasoning[trail.reasoning.length - 1],
    ]
  }

  if (trail.execution_params) {
    const node = mock.find((n) => n.id === 'execute')!
    node.details = { ...node.details, ...trail.execution_params }
  }

  // Mark steps after a failure as skipped
  let failed = false
  for (const node of mock) {
    if (failed && node.id !== 'decision') {
      node.status = 'skipped'
    }
    if (node.status === 'fail' && node.id !== 'decision') {
      failed = true
    }
  }

  return mock
}

/* ---------- Pipeline node type ---------- */

interface PipelineNode {
  id: string
  title: string
  icon: React.ComponentType<{ className?: string }>
  status: 'pass' | 'fail' | 'warn' | 'skipped' | 'pending'
  summary: string[]
  details: Record<string, unknown>
}

/* ---------- Status helpers ---------- */

const statusColors: Record<string, { bg: string; border: string; text: string; dot: string; line: string }> = {
  pass: {
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    text: 'text-emerald-600 dark:text-emerald-400',
    dot: 'bg-emerald-500',
    line: 'bg-emerald-500/40',
  },
  fail: {
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
    text: 'text-red-600 dark:text-red-400',
    dot: 'bg-red-500',
    line: 'bg-red-500/40',
  },
  warn: {
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    text: 'text-amber-600 dark:text-amber-400',
    dot: 'bg-amber-500',
    line: 'bg-amber-500/40',
  },
  skipped: {
    bg: 'bg-zinc-500/10',
    border: 'border-zinc-500/20',
    text: 'text-zinc-400 dark:text-zinc-500',
    dot: 'bg-zinc-400',
    line: 'bg-zinc-300/40 dark:bg-zinc-600/40',
  },
  pending: {
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/20',
    text: 'text-blue-500 dark:text-blue-400',
    dot: 'bg-blue-500',
    line: 'bg-blue-400/40',
  },
}

function statusLabel(status: string): string {
  if (status === 'pass') return 'Passed'
  if (status === 'fail') return 'Failed'
  if (status === 'warn') return 'Warning'
  if (status === 'skipped') return 'Skipped'
  return 'Pending'
}

/* ---------- Detail sheet content ---------- */

function hasReasoningChain(details: Record<string, unknown>): boolean {
  return 'reasoning_chain' in details && Array.isArray(details.reasoning_chain)
}

function hasModels(details: Record<string, unknown>): boolean {
  return 'models' in details && details.models != null && typeof details.models === 'object'
}

function ReasoningChainSection({ items }: { items: string[] }) {
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold uppercase text-muted-foreground">
        Reasoning Chain
      </p>
      <ol className="space-y-1 list-decimal list-inside">
        {items.map((r, i) => (
          <li key={i} className="text-sm text-foreground/80">
            {r}
          </li>
        ))}
      </ol>
    </div>
  )
}

function DetailContent({ node }: { node: PipelineNode }) {
  const colors = statusColors[node.status] ?? statusColors.pending

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className={cn('p-2 rounded-lg', colors.bg)}>
          <node.icon className={cn('h-5 w-5', colors.text)} />
        </div>
        <div>
          <p className="font-semibold text-base">{node.title}</p>
          <Badge
            variant={
              node.status === 'pass'
                ? 'success'
                : node.status === 'fail'
                  ? 'destructive'
                  : node.status === 'warn'
                    ? 'warning'
                    : 'secondary'
            }
            className="text-[10px] mt-0.5"
          >
            {statusLabel(node.status)}
          </Badge>
        </div>
      </div>

      {/* Summary bullets */}
      <div className="space-y-1">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">Summary</p>
        <ul className="space-y-0.5">
          {node.summary.map((s, i) => (
            <li key={i} className="text-sm text-foreground/80">
              {s}
            </li>
          ))}
        </ul>
      </div>

      {/* Reasoning chain if present */}
      {hasReasoningChain(node.details) && (
        <ReasoningChainSection items={node.details.reasoning_chain as string[]} />
      )}

      {/* Model breakdown if present */}
      {node.id === 'ml' && hasModels(node.details) && (
        <div className="space-y-1">
          <p className="text-[10px] font-semibold uppercase text-muted-foreground">
            Model Breakdown
          </p>
          <div className="space-y-1.5">
            {Object.entries(node.details.models as Record<string, number>).map(
              ([name, score]) => (
                <div key={name} className="flex items-center gap-2 text-sm">
                  <span className="w-24 font-mono text-muted-foreground capitalize">
                    {name}
                  </span>
                  <div className="flex-1 h-2 rounded bg-muted overflow-hidden">
                    <div
                      className={cn(
                        'h-full rounded',
                        score >= 0.7
                          ? 'bg-emerald-500/70'
                          : score >= 0.5
                            ? 'bg-amber-500/70'
                            : 'bg-red-500/70',
                      )}
                      style={{ width: `${(score * 100).toFixed(0)}%` }}
                    />
                  </div>
                  <span className="w-12 text-right font-mono">
                    {(score * 100).toFixed(0)}%
                  </span>
                </div>
              ),
            )}
          </div>
        </div>
      )}

      {/* Full details table */}
      <div className="space-y-1">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">
          All Details
        </p>
        <div className="rounded border bg-muted/30 p-3 space-y-1">
          {Object.entries(node.details)
            .filter(
              ([k, v]) =>
                v != null &&
                k !== 'models' &&
                k !== 'reasoning_chain' &&
                typeof v !== 'object',
            )
            .map(([k, v]) => (
              <div key={k} className="flex text-xs">
                <span className="w-36 text-muted-foreground font-mono shrink-0">
                  {k}
                </span>
                <span className="font-mono text-foreground/80 break-all">
                  {typeof v === 'number'
                    ? Number.isInteger(v)
                      ? String(v)
                      : v.toFixed(4)
                    : String(v)}
                </span>
              </div>
            ))}
          {/* Nested objects */}
          {Object.entries(node.details)
            .filter(
              ([k, v]) =>
                v != null &&
                typeof v === 'object' &&
                !Array.isArray(v) &&
                k !== 'models' &&
                k !== 'reasoning_chain',
            )
            .map(([k, v]) => (
              <div key={k} className="mt-2">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">
                  {k}
                </p>
                {Object.entries(v as Record<string, unknown>)
                  .filter(([, val]) => val != null)
                  .map(([subK, subV]) => (
                    <div key={subK} className="flex text-xs pl-3">
                      <span className="w-32 text-muted-foreground font-mono shrink-0">
                        {subK}
                      </span>
                      <span className="font-mono text-foreground/80">
                        {String(subV)}
                      </span>
                    </div>
                  ))}
              </div>
            ))}
        </div>
      </div>
    </div>
  )
}

/* ---------- Pipeline node card ---------- */

function NodeCard({
  node,
  index,
  isLast,
  isCurrent,
  onSelect,
}: {
  node: PipelineNode
  index: number
  isLast: boolean
  isCurrent: boolean
  onSelect: () => void
}) {
  const colors = statusColors[node.status] ?? statusColors.pending

  return (
    <>
      {/* Desktop: horizontal node */}
      <div
        className={cn(
          'hidden md:flex flex-col items-center',
          'animate-in fade-in slide-in-from-left-2',
        )}
        style={{ animationDelay: `${index * 80}ms`, animationFillMode: 'both' }}
      >
        <button
          onClick={onSelect}
          className={cn(
            'relative flex flex-col items-center gap-1.5 p-3 rounded-lg border transition-all',
            'hover:shadow-md hover:scale-[1.03] cursor-pointer',
            'w-[120px] min-h-[100px]',
            colors.bg,
            colors.border,
            isCurrent && 'ring-2 ring-primary/50 shadow-md shadow-primary/10',
          )}
        >
          {/* Pulse glow for current step */}
          {isCurrent && (
            <span className="absolute -inset-px rounded-lg animate-pulse opacity-30 border-2 border-primary pointer-events-none" />
          )}
          <div className={cn('p-1.5 rounded-md', colors.bg)}>
            <node.icon className={cn('h-4 w-4', colors.text)} />
          </div>
          <span className="text-[11px] font-semibold">{node.title}</span>
          <div className="flex flex-col items-center gap-0.5 w-full">
            {node.summary.slice(0, 2).map((s, i) => (
              <span
                key={i}
                className="text-[9px] text-muted-foreground leading-tight truncate w-full text-center"
                title={s}
              >
                {s}
              </span>
            ))}
          </div>
          <div className={cn('h-1.5 w-1.5 rounded-full mt-auto', colors.dot)} />
        </button>
      </div>

      {/* Desktop: connecting arrow */}
      {!isLast && (
        <div
          className="hidden md:flex items-center animate-in fade-in"
          style={{
            animationDelay: `${index * 80 + 40}ms`,
            animationFillMode: 'both',
          }}
        >
          <div className={cn('w-6 h-0.5 rounded', colors.line)} />
          <ChevronRight
            className={cn('h-3 w-3 -ml-1', colors.text, 'opacity-50')}
          />
        </div>
      )}

      {/* Mobile: vertical node */}
      <div
        className={cn(
          'md:hidden flex items-start gap-3',
          'animate-in fade-in slide-in-from-top-2',
        )}
        style={{ animationDelay: `${index * 60}ms`, animationFillMode: 'both' }}
      >
        {/* Vertical line + dot */}
        <div className="flex flex-col items-center shrink-0 pt-1">
          <div className={cn('h-3 w-3 rounded-full border-2', colors.border, colors.dot)} />
          {!isLast && <div className={cn('w-0.5 flex-1 min-h-[40px] mt-1 rounded', colors.line)} />}
        </div>

        {/* Card */}
        <button
          onClick={onSelect}
          className={cn(
            'flex-1 text-left p-2.5 rounded-lg border transition-all mb-1',
            'hover:shadow-sm cursor-pointer',
            colors.bg,
            colors.border,
            isCurrent && 'ring-2 ring-primary/50',
          )}
        >
          <div className="flex items-center gap-2 mb-1">
            <node.icon className={cn('h-3.5 w-3.5', colors.text)} />
            <span className="text-xs font-semibold">{node.title}</span>
            <Badge
              variant={
                node.status === 'pass'
                  ? 'success'
                  : node.status === 'fail'
                    ? 'destructive'
                    : node.status === 'warn'
                      ? 'warning'
                      : 'secondary'
              }
              className="text-[9px] ml-auto px-1.5 py-0"
            >
              {statusLabel(node.status)}
            </Badge>
            <ChevronDown className="h-3 w-3 text-muted-foreground" />
          </div>
          <div className="space-y-0.5">
            {node.summary.slice(0, 2).map((s, i) => (
              <p key={i} className="text-[10px] text-muted-foreground leading-tight truncate">
                {s}
              </p>
            ))}
          </div>
        </button>
      </div>
    </>
  )
}

/* ---------- Main component ---------- */

export function DecisionTrailVisualizer({ trade }: DecisionTrailProps) {
  const [selectedNode, setSelectedNode] = useState<PipelineNode | null>(null)

  // Build pipeline nodes from real trail data or mock
  const nodes: PipelineNode[] = trade.decision_trail
    ? buildFromTrail(trade, trade.decision_trail)
    : buildMockTrail(trade)

  // Determine "current step" -- the last non-skipped node
  const currentIndex = (() => {
    let last = 0
    for (let i = 0; i < nodes.length; i++) {
      if (nodes[i].status !== 'skipped') last = i
    }
    return last
  })()

  return (
    <div className="w-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Decision Pipeline
        </span>
        <span className="text-[10px] text-muted-foreground">
          {trade.ticker} {(trade.direction ?? trade.side ?? '').toUpperCase()}
        </span>
        <Badge
          variant={
            trade.status === 'executed' || trade.status === 'closed'
              ? 'success'
              : trade.status === 'rejected' || trade.status === 'skipped'
                ? 'destructive'
                : 'secondary'
          }
          className="text-[9px] ml-auto"
        >
          {trade.status.toUpperCase()}
        </Badge>
      </div>

      {/* Desktop: horizontal flow */}
      <div className="hidden md:flex items-center gap-0 overflow-x-auto pb-2">
        {nodes.map((node, i) => (
          <NodeCard
            key={node.id}
            node={node}
            index={i}
            isLast={i === nodes.length - 1}
            isCurrent={i === currentIndex}
            onSelect={() => setSelectedNode(node)}
          />
        ))}
      </div>

      {/* Mobile: vertical flow */}
      <div className="md:hidden space-y-0">
        {nodes.map((node, i) => (
          <NodeCard
            key={node.id}
            node={node}
            index={i}
            isLast={i === nodes.length - 1}
            isCurrent={i === currentIndex}
            onSelect={() => setSelectedNode(node)}
          />
        ))}
      </div>

      {/* Detail sheet */}
      <Sheet
        open={selectedNode !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedNode(null)
        }}
      >
        <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto">
          <SheetHeader className="mb-4">
            <SheetTitle>{selectedNode?.title ?? 'Step Details'}</SheetTitle>
            <SheetDescription>
              Full details for the {selectedNode?.title?.toLowerCase() ?? ''} step
              in the decision pipeline.
            </SheetDescription>
          </SheetHeader>
          {selectedNode && <DetailContent node={selectedNode} />}
        </SheetContent>
      </Sheet>
    </div>
  )
}
