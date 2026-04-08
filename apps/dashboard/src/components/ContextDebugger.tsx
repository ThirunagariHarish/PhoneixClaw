/**
 * ContextDebugger — collapsible panel showing Smart Context build stats for an agent.
 *
 * Placed on the Chat tab in AgentDashboard.  Only meaningful when
 * ENABLE_SMART_CONTEXT=true; otherwise shows a disabled notice.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ChevronDown, ChevronUp, Search } from 'lucide-react'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ContextSessionData {
  id: string
  session_type: string
  signal_symbol: string | null
  token_budget: number
  tokens_used: number
  wiki_entries_injected: number
  trades_injected: number
  manifest_sections_injected: string[]
  quality_score: number | null
  built_at: string
}

interface ContextDebuggerProps {
  agentId: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function QualityBadge({ score }: { score: number | null }) {
  if (score === null) return <Badge variant="outline">N/A</Badge>
  if (score >= 0.65) return <Badge className="bg-emerald-500 text-white">{score.toFixed(2)} 🟢</Badge>
  if (score >= 0.4) return <Badge className="bg-yellow-400 text-black">{score.toFixed(2)} 🟡</Badge>
  return <Badge className="bg-red-500 text-white">{score.toFixed(2)} 🔴</Badge>
}

function TierBar({
  label,
  tokens,
  total,
}: {
  label: string
  tokens: number
  total: number
}) {
  const pct = total > 0 ? Math.min(100, (tokens / total) * 100) : 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 truncate text-muted-foreground">{label}</span>
      <div className="flex-1 h-2 rounded bg-muted overflow-hidden">
        <div
          className="h-full rounded bg-primary/70"
          style={{ width: `${pct.toFixed(1)}%` }}
        />
      </div>
      <span className="w-14 text-right tabular-nums text-muted-foreground">
        {tokens.toLocaleString()}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ContextDebugger({ agentId }: ContextDebuggerProps) {
  const [isOpen, setIsOpen] = useState(false)

  const { data, isError, isFetching } = useQuery<ContextSessionData>({
    queryKey: ['context-latest', agentId],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}/context/latest`)).data,
    retry: false, // 404 is expected when ENABLE_SMART_CONTEXT=false
    refetchInterval: isOpen ? 15_000 : false,
  })

  return (
    <div className="mb-3">
      <Button
        variant="ghost"
        size="sm"
        className="w-full flex items-center justify-between text-xs text-muted-foreground hover:text-foreground h-7 px-2"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="flex items-center gap-1.5">
          <Search className="h-3 w-3" />
          Context Debugger
        </span>
        {isOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </Button>

      {isOpen && (
        <Card className="mt-1 border-dashed">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold flex items-center gap-2">
              <Search className="h-3.5 w-3.5 text-primary" />
              Smart Context Debugger
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3 text-xs">
            {isFetching && !data && (
              <p className="text-muted-foreground">Loading…</p>
            )}

            {isError && (
              <div className="space-y-1">
                <p className="text-muted-foreground">
                  Smart Context disabled or no sessions recorded yet.
                </p>
                <p className="text-[10px] text-muted-foreground/70">
                  Set <code className="font-mono bg-muted px-1 rounded">ENABLE_SMART_CONTEXT=true</code> to enable.
                </p>
              </div>
            )}

            {data && (
              <>
                {/* Header row */}
                <div className="flex flex-wrap gap-3 text-muted-foreground">
                  <span>
                    Last build:{' '}
                    <span className="text-foreground">
                      {new Date(data.built_at).toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </span>
                  <span>
                    Budget:{' '}
                    <span className="text-foreground">{data.token_budget.toLocaleString()}</span>{' '}
                    tokens
                  </span>
                  <span>
                    Used:{' '}
                    <span className="text-foreground">{data.tokens_used.toLocaleString()}</span>
                  </span>
                </div>

                {/* Quality score */}
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">Quality score:</span>
                  <QualityBadge score={data.quality_score} />
                </div>

                {/* Token allocation bars */}
                <div className="space-y-1.5">
                  <p className="font-medium text-muted-foreground">Token allocation:</p>
                  {/* Rough tier split — we show injected counts as proxies */}
                  <TierBar
                    label="Signal"
                    tokens={Math.min(500, data.tokens_used)}
                    total={data.token_budget}
                  />
                  <TierBar
                    label={`Wiki (${data.wiki_entries_injected} entries)`}
                    tokens={data.wiki_entries_injected * 150}
                    total={data.token_budget}
                  />
                  <TierBar
                    label={`Trades (${data.trades_injected})`}
                    tokens={data.trades_injected * 30}
                    total={data.token_budget}
                  />
                  {data.manifest_sections_injected.length > 0 && (
                    <TierBar
                      label={`Manifest (${data.manifest_sections_injected.join(', ')})`}
                      tokens={data.manifest_sections_injected.length * 200}
                      total={data.token_budget}
                    />
                  )}
                </div>

                {/* Wiki entry chips */}
                {data.wiki_entries_injected > 0 && (
                  <div className="space-y-1">
                    <p className="font-medium text-muted-foreground">
                      Wiki entries injected ({data.wiki_entries_injected}):
                    </p>
                    <p className="text-[10px] text-muted-foreground/70 italic">
                      {data.wiki_entries_injected} knowledge entry
                      {data.wiki_entries_injected !== 1 ? 'ies' : 'y'} injected
                      {data.signal_symbol ? ` for ${data.signal_symbol}` : ''}.
                    </p>
                  </div>
                )}

                {/* Status footer */}
                <div className="flex items-center gap-2 pt-1 border-t">
                  <span className="text-muted-foreground">Smart Context:</span>
                  <Badge
                    className={cn(
                      'text-[10px] px-1.5 py-0',
                      'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
                    )}
                  >
                    ENABLED
                  </Badge>
                  <span className="text-[10px] text-muted-foreground/60 ml-auto">
                    env: ENABLE_SMART_CONTEXT=true
                  </span>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
