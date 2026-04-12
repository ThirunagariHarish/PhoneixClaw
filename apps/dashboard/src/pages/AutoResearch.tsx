/**
 * AutoResearch page — Karpathy-style nightly experiment results.
 *
 * Shows:
 * - Supervisor scheduler status (next run at 16:30 ET)
 * - Latest EOD analysis summary
 * - Pending improvements across all agents (with approve/reject)
 * - Trade signal stats (missed opportunities for RL feedback loop)
 * - Manual "Run Supervisor Now" + "Run EOD Analysis" buttons
 * - Results History section (last 5 research runs)
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { agentsApi } from '@/lib/api/agents'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { MetricCard } from '@/components/ui/MetricCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Beaker, Play, Clock, AlertTriangle, History, FileSearch } from 'lucide-react'

interface SchedulerStatus {
  running: boolean
  jobs?: Array<{ id: string; name: string; next_run_time: string | null }>
}

interface SignalStats {
  days: number
  breakdown: Record<string, { count: number; missed: number }>
  total_missed_opportunities: number
}

interface ResearchRun {
  id: string
  created_at: string
  findings_count: number
  improvements_applied: number
  summary?: string
}

export default function AutoResearchPage() {
  const [status, setStatus] = useState<SchedulerStatus | null>(null)
  const [signalStats, setSignalStats] = useState<SignalStats | null>(null)
  const [eodSummary, setEodSummary] = useState<Record<string, unknown> | null>(null)
  const [supervisorResult, setSupervisorResult] = useState<Record<string, unknown> | null>(null)
  const [eodResult, setEodResult] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState({ supervisor: false, eod: false })

  useEffect(() => {
    agentsApi.schedulerStatus().then(setStatus).catch(() => null)
    agentsApi.tradeSignalStats(undefined, 30).then(setSignalStats).catch(() => null)
    agentsApi.latestEodSummary().then((d: Record<string, unknown>) => d?.found && setEodSummary(d)).catch(() => null)
  }, [])

  // Results History — last 5 research runs
  const { data: researchHistory = [] } = useQuery<ResearchRun[]>({
    queryKey: ['research-history'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/autoresearch/history?limit=5')
        return res.data ?? []
      } catch {
        return []
      }
    },
    refetchInterval: 60_000,
  })

  const runSupervisor = async () => {
    setLoading((prev) => ({ ...prev, supervisor: true }))
    setError(null)
    try {
      const r = await agentsApi.triggerSupervisor()
      setSupervisorResult(r)
    } catch (e: any) {
      setError(e?.message || 'Failed to trigger supervisor')
    } finally {
      setLoading((prev) => ({ ...prev, supervisor: false }))
    }
  }

  const runEod = async () => {
    setLoading((prev) => ({ ...prev, eod: true }))
    setError(null)
    try {
      const r = await agentsApi.triggerEodAnalysis()
      setEodResult(r)
    } catch (e: any) {
      setError(e?.message || 'Failed to trigger EOD analysis')
    } finally {
      setLoading((prev) => ({ ...prev, eod: false }))
    }
  }

  const supervisorJob = status?.jobs?.find((j) => j.id === 'supervisor_run')
  const eodJob = status?.jobs?.find((j) => j.id === 'eod_analysis')

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Beaker} title="AutoResearch" description="Karpathy-style nightly experiments + EOD analysis + RL feedback loop." />

      {/* Manual triggers */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <h2 className="text-base font-semibold">Supervisor Agent</h2>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Runs daily at 16:30 ET. Analyzes performance, proposes improvements.
            </p>
            {supervisorJob && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Clock className="h-3 w-3" />
                Next run: {supervisorJob.next_run_time
                  ? new Date(supervisorJob.next_run_time).toLocaleString()
                  : 'unknown'}
              </div>
            )}
            <Button
              onClick={runSupervisor}
              disabled={loading.supervisor}
              size="sm"
            >
              <Play className="h-3.5 w-3.5 mr-1.5" />
              {loading.supervisor ? 'Running...' : 'Run Supervisor Now'}
            </Button>
            {supervisorResult && (
              <pre className="text-xs bg-muted rounded-lg p-2 overflow-auto max-h-40 font-mono">
                {JSON.stringify(supervisorResult, null, 2)}
              </pre>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <h2 className="text-base font-semibold">EOD Analysis</h2>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Runs daily at 16:45 ET. Enriches trade signals with outcomes.
            </p>
            {eodJob && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Clock className="h-3 w-3" />
                Next run: {eodJob.next_run_time
                  ? new Date(eodJob.next_run_time).toLocaleString()
                  : 'unknown'}
              </div>
            )}
            <Button
              onClick={runEod}
              disabled={loading.eod}
              size="sm"
            >
              <Play className="h-3.5 w-3.5 mr-1.5" />
              {loading.eod ? 'Running...' : 'Run EOD Analysis Now'}
            </Button>
            {eodResult && (
              <pre className="text-xs bg-muted rounded-lg p-2 overflow-auto max-h-40 font-mono">
                {JSON.stringify(eodResult, null, 2)}
              </pre>
            )}
          </CardContent>
        </Card>
      </div>

      {error && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="py-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Signal stats */}
      <Card>
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold">Trade Signal Stats (last 30 days)</h2>
        </CardHeader>
        <CardContent>
          {signalStats ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Object.entries(signalStats.breakdown).map(([decision, stats]) => (
                <MetricCard
                  key={decision}
                  title={decision}
                  value={stats.count}
                  subtitle={stats.missed > 0 ? `${stats.missed} missed opportunities` : undefined}
                  trend={stats.missed > 0 ? 'down' : 'neutral'}
                />
              ))}
              <Card className="border-amber-500/30 bg-amber-500/5">
                <CardContent className="p-3">
                  <div className="text-[10px] text-amber-600 dark:text-amber-400 uppercase font-medium">Total Missed</div>
                  <div className="text-2xl font-bold text-amber-600 dark:text-amber-400 mt-1">
                    {signalStats.total_missed_opportunities}
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-1">RL feedback candidates</div>
                </CardContent>
              </Card>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No data yet -- agents need to log signals first</p>
          )}
        </CardContent>
      </Card>

      {/* Results History — last 5 research runs */}
      <Card>
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <History className="h-4 w-4 text-muted-foreground" />
            Results History
          </h2>
        </CardHeader>
        <CardContent>
          {researchHistory.length > 0 ? (
            <div className="space-y-2">
              {researchHistory.map((run) => (
                <div key={run.id} className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <FileSearch className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">
                        {run.created_at ? new Date(run.created_at).toLocaleDateString(undefined, {
                          weekday: 'short', month: 'short', day: 'numeric'
                        }) : 'Unknown date'}
                      </p>
                      {run.summary && (
                        <p className="text-xs text-muted-foreground truncate">{run.summary}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <Badge variant="outline" className="text-xs">
                      {run.findings_count} findings
                    </Badge>
                    <Badge variant="secondary" className="text-xs">
                      {run.improvements_applied} applied
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No research runs yet. Run the supervisor to generate results.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Latest EOD summary */}
      {eodSummary && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">Latest EOD Summary</h2>
              <span className="text-xs text-muted-foreground">
                {(eodSummary.created_at as string) && new Date(eodSummary.created_at as string).toLocaleString()}
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted rounded-lg p-3 whitespace-pre-wrap font-mono">
              {eodSummary.body as string}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
