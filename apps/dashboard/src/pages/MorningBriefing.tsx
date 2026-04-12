/**
 * Morning Briefing page — view today's pre-market briefing and trigger manually.
 *
 * The scheduler runs the morning routine at 9:00 AM ET on weekdays. This page
 * shows the latest briefing dispatched to agents + a manual "Run Now" button.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { agentsApi } from '@/lib/api/agents'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Sun, Play, CheckCircle2, Clock, AlertCircle } from 'lucide-react'

interface SchedulerStatus {
  running: boolean
  jobs?: Array<{ id: string; name: string; next_run_time: string | null }>
  reason?: string
}

interface SpawnResult {
  status?: string
  task_key?: string
  detail?: string
  error?: string
}

interface BriefingHistoryRow {
  id: number
  kind: string
  title: string
  body: string
  data: Record<string, unknown>
  agents_woken: number
  dispatched_to: string[]
  created_at: string | null
}

export default function MorningBriefingPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<SchedulerStatus | null>(null)
  const [spawn, setSpawn] = useState<SpawnResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    agentsApi.schedulerStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  // Poll the briefing_history table for the latest morning briefing
  const { data: historyData } = useQuery<{ briefings: BriefingHistoryRow[] }>({
    queryKey: ['briefing-history', 'morning'],
    queryFn: async () =>
      (await api.get('/api/v2/briefings?kind=morning&limit=1')).data,
    refetchInterval: 5000,
  })
  const latestHistory = historyData?.briefings?.[0]

  const runManually = async () => {
    setLoading(true)
    setError(null)
    setSpawn(null)
    try {
      const result = await agentsApi.triggerMorningBriefing()
      setSpawn(result)
      if (result?.status === 'error' || result?.error) {
        setError(`Backend error: ${result?.error || 'unknown'}`)
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to spawn morning briefing agent')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader icon={Sun} title="Morning Briefing" description="Pre-market routine -- wakes all agents, triggers research, sends WhatsApp briefing." />
        <Button onClick={runManually} disabled={loading}>
          <Play className="h-4 w-4 mr-2" />
          {loading ? 'Running...' : 'Run Now'}
        </Button>
      </div>

      {/* Scheduler status — proper table */}
      <Card>
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold">Scheduled Jobs</h2>
        </CardHeader>
        <CardContent>
          {status?.running ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Badge variant="default" className="bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border-emerald-500/30">
                  <CheckCircle2 className="h-3 w-3 mr-1" /> Running
                </Badge>
              </div>
              {status.jobs && status.jobs.length > 0 && (
                <div className="rounded-lg border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Job Name</TableHead>
                        <TableHead>Schedule</TableHead>
                        <TableHead>Next Run</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {status.jobs.map((j) => (
                        <TableRow key={j.id}>
                          <TableCell className="font-medium text-sm">{j.name}</TableCell>
                          <TableCell className="text-xs text-muted-foreground font-mono">{j.id}</TableCell>
                          <TableCell className="text-xs font-mono">
                            {j.next_run_time
                              ? new Date(j.next_run_time).toLocaleString()
                              : 'No next run'}
                          </TableCell>
                          <TableCell>
                            {j.next_run_time ? (
                              <Badge variant="outline" className="text-[10px]">
                                <Clock className="h-3 w-3 mr-1" /> Scheduled
                              </Badge>
                            ) : (
                              <Badge variant="secondary" className="text-[10px]">Idle</Badge>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Badge variant="destructive">
                <AlertCircle className="h-3 w-3 mr-1" /> Not Running
              </Badge>
              {status?.reason && (
                <span className="text-xs text-muted-foreground">({status.reason})</span>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="py-3">
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Latest briefing from history */}
      {latestHistory && (
        <Card
          className="cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => navigate('/briefings')}
        >
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">Latest Morning Briefing</h2>
              <span className="text-xs text-muted-foreground">
                {latestHistory.created_at
                  ? new Date(latestHistory.created_at).toLocaleString()
                  : ''}
              </span>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Agents woken</div>
                <div className="text-xl font-bold">{latestHistory.agents_woken ?? 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Dispatched</div>
                <div className="flex gap-1 flex-wrap mt-1">
                  {(latestHistory.dispatched_to ?? []).map((ch) => (
                    <Badge key={ch} variant="secondary" className="text-xs">{ch}</Badge>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Title</div>
                <div className="text-sm font-medium">{latestHistory.title}</div>
              </div>
            </div>
            <pre className="text-xs bg-muted rounded-lg p-3 whitespace-pre-wrap max-h-48 overflow-y-auto font-mono">
              {latestHistory.body}
            </pre>
            <p className="text-xs text-muted-foreground">
              Click to view full briefing history
            </p>
          </CardContent>
        </Card>
      )}

      {/* Spawn confirmation card */}
      {spawn && spawn.status === 'spawned' && (
        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="py-4 space-y-2">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              <span className="font-semibold text-sm text-primary">Morning briefing agent spawned</span>
            </div>
            <p className="text-sm text-muted-foreground">{spawn.detail || 'Running...'}</p>
            <p className="text-xs text-muted-foreground font-mono">task_key: {spawn.task_key}</p>
            <p className="text-xs text-muted-foreground">
              The briefing body will appear above once the agent completes (auto-refresh every 5s).
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
