/**
 * ConsolidationPanel — Nightly Consolidation ("Agent Sleep") status panel.
 *
 * Shows the last run stats, allows triggering a manual run, renders the
 * consolidation report, and lists recent runs.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Brain, RefreshCw, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface ConsolidationRun {
  id: string
  agent_id: string
  run_type: string
  status: string
  scheduled_for: string | null
  started_at: string | null
  completed_at: string | null
  trades_analyzed: number
  wiki_entries_written: number
  wiki_entries_updated: number
  wiki_entries_pruned: number
  patterns_found: number
  rules_proposed: number
  consolidation_report: string | null
  error_message: string | null
  created_at: string
}

interface ConsolidationPanelProps {
  agentId: string
}

function StatusChip({ status }: { status: string }) {
  if (status === 'completed') {
    return (
      <Badge className="bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-0 gap-1">
        <CheckCircle className="h-3 w-3" />
        Completed
      </Badge>
    )
  }
  if (status === 'failed') {
    return (
      <Badge className="bg-rose-500/20 text-rose-700 dark:text-rose-400 border-0 gap-1">
        <XCircle className="h-3 w-3" />
        Failed
      </Badge>
    )
  }
  if (status === 'running') {
    return (
      <Badge className="bg-blue-500/20 text-blue-700 dark:text-blue-400 border-0 gap-1">
        <Loader2 className="h-3 w-3 animate-spin" />
        Running
      </Badge>
    )
  }
  return (
    <Badge variant="secondary" className="gap-1">
      <Clock className="h-3 w-3" />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  )
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function ConsolidationPanel({ agentId }: ConsolidationPanelProps) {
  const queryClient = useQueryClient()
  const [showReport, setShowReport] = useState(false)

  const { data: runs = [], isLoading } = useQuery<ConsolidationRun[]>({
    queryKey: ['consolidation-runs', agentId],
    queryFn: async () => {
      try {
        return (await api.get(`/api/v2/agents/${agentId}/consolidation/runs?limit=5`)).data
      } catch {
        return []
      }
    },
    refetchInterval: 15000,
  })

  const triggerMut = useMutation({
    mutationFn: () =>
      api.post(`/api/v2/agents/${agentId}/consolidation/run`, { run_type: 'manual' }),
    onSuccess: () => {
      toast.success('Consolidation started')
      queryClient.invalidateQueries({ queryKey: ['consolidation-runs', agentId] })
    },
    onError: () => toast.error('Failed to trigger consolidation'),
  })

  const latest = runs[0] ?? null

  return (
    <Card className="mt-4">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold">
            <Brain className="h-4 w-4 text-violet-500" />
            Nightly Consolidation
          </CardTitle>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs gap-1"
            onClick={() => triggerMut.mutate()}
            disabled={triggerMut.isPending}
          >
            {triggerMut.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            Run Now
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Latest run summary */}
        {isLoading ? (
          <p className="text-xs text-muted-foreground">Loading…</p>
        ) : latest ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <StatusChip status={latest.status} />
              <span className="text-xs text-muted-foreground">
                Last run: {formatDate(latest.created_at)}
              </span>
            </div>

            {latest.status === 'completed' && (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {[
                  { label: 'Trades analyzed', value: latest.trades_analyzed },
                  { label: 'Patterns found', value: latest.patterns_found },
                  { label: 'Entries written', value: latest.wiki_entries_written },
                  { label: 'Entries updated', value: latest.wiki_entries_updated },
                  { label: 'Entries pruned', value: latest.wiki_entries_pruned },
                  { label: 'Rules proposed', value: latest.rules_proposed },
                ].map(({ label, value }) => (
                  <div key={label} className="rounded-md bg-muted/50 px-2 py-1.5">
                    <p className="text-[10px] text-muted-foreground">{label}</p>
                    <p className="text-sm font-semibold">{value}</p>
                  </div>
                ))}
              </div>
            )}

            {latest.status === 'failed' && latest.error_message && (
              <p className="text-xs text-rose-600 bg-rose-50 dark:bg-rose-950/30 rounded p-2">
                Error: {latest.error_message}
              </p>
            )}

            {latest.consolidation_report && (
              <div>
                <button
                  className="text-xs underline text-muted-foreground hover:text-foreground"
                  onClick={() => setShowReport((v) => !v)}
                >
                  {showReport ? 'Hide report' : 'Show consolidation report'}
                </button>
                {showReport && (
                  <pre className="mt-2 text-xs font-mono bg-muted rounded-md p-3 whitespace-pre-wrap max-h-96 overflow-y-auto">
                    {latest.consolidation_report}
                  </pre>
                )}
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No consolidation runs yet.</p>
        )}

        {/* Recent runs list */}
        {runs.length > 1 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-2">Recent Runs</p>
            <div className="space-y-1">
              {runs.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50 text-xs"
                >
                  <StatusChip status={run.status} />
                  <span className="text-muted-foreground flex-1 min-w-0 truncate">
                    {formatDate(run.created_at)}
                  </span>
                  {run.status === 'completed' && (
                    <span className="text-muted-foreground shrink-0">
                      {run.trades_analyzed} trades
                    </span>
                  )}
                  <Badge variant="outline" className="text-[10px] shrink-0">
                    {run.run_type}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
