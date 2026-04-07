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

  // Poll the briefing_history table for the latest morning briefing — this is
  // the single source of truth for what the agent produced (manual or cron).
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

  const morningJob = status?.jobs?.find((j) => j.id === 'morning_briefing')

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Morning Briefing</h1>
          <p className="text-sm text-gray-400">
            Pre-market routine — wakes all agents, triggers research, sends WhatsApp briefing.
          </p>
        </div>
        <button
          onClick={runManually}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-white font-medium"
        >
          {loading ? 'Running...' : 'Run Now'}
        </button>
      </div>

      {/* Scheduler status */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h2 className="text-lg font-semibold mb-2">Scheduler</h2>
        {status?.running ? (
          <div className="text-sm space-y-1">
            <div className="text-green-400">● Running</div>
            {morningJob && (
              <div className="text-gray-300">
                Next morning briefing:{' '}
                <span className="font-mono">
                  {morningJob.next_run_time
                    ? new Date(morningJob.next_run_time).toLocaleString()
                    : 'unknown'}
                </span>
              </div>
            )}
            {status.jobs && (
              <div className="mt-2 text-xs text-gray-400">
                All scheduled jobs:
                <ul className="ml-4 mt-1">
                  {status.jobs.map((j) => (
                    <li key={j.id}>
                      {j.name} →{' '}
                      {j.next_run_time
                        ? new Date(j.next_run_time).toLocaleString()
                        : 'no next run'}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="text-red-400 text-sm">
            ● Not running {status?.reason ? `(${status.reason})` : ''}
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded p-3 text-red-200 text-sm">
          {error}
        </div>
      )}

      {/* Latest briefing from history (always shown, auto-refreshes) */}
      {latestHistory && (
        <div
          className="bg-gray-800 rounded-lg p-4 border border-gray-700 cursor-pointer hover:border-blue-500 transition-colors"
          onClick={() => navigate('/briefings')}
        >
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold">Latest Morning Briefing</h2>
            <span className="text-xs text-gray-400">
              {latestHistory.created_at
                ? new Date(latestHistory.created_at).toLocaleString()
                : ''}
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-3 text-sm">
            <div>
              <div className="text-gray-400">Agents woken</div>
              <div className="text-xl font-bold">{latestHistory.agents_woken ?? 0}</div>
            </div>
            <div>
              <div className="text-gray-400">Dispatched</div>
              <div className="flex gap-1 flex-wrap mt-1">
                {(latestHistory.dispatched_to ?? []).map((ch) => (
                  <span key={ch} className="text-xs px-2 py-0.5 rounded bg-gray-700">
                    {ch}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-gray-400">Title</div>
              <div className="text-sm">{latestHistory.title}</div>
            </div>
          </div>
          <pre className="text-xs bg-gray-900 rounded p-3 whitespace-pre-wrap max-h-48 overflow-y-auto">
            {latestHistory.body}
          </pre>
          <div className="text-xs text-gray-500 mt-2">
            Click to view full briefing history →
          </div>
        </div>
      )}

      {/* Spawn confirmation card (brief toast-like info while agent runs) */}
      {spawn && spawn.status === 'spawned' && (
        <div className="bg-blue-900/20 border border-blue-700/40 rounded-lg p-4 text-sm">
          <div className="font-semibold text-blue-300 mb-1">
            ✓ Morning briefing agent spawned
          </div>
          <div className="text-blue-200/80">{spawn.detail || 'Running…'}</div>
          <div className="text-xs text-gray-400 mt-2 font-mono">
            task_key: {spawn.task_key}
          </div>
          <div className="text-xs text-gray-400 mt-1">
            The briefing body will appear above once the agent completes (auto-refresh every 5s).
          </div>
        </div>
      )}
    </div>
  )
}
