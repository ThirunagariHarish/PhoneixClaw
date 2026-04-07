/**
 * Morning Briefing page — view today's pre-market briefing and trigger manually.
 *
 * The scheduler runs the morning routine at 9:00 AM ET on weekdays. This page
 * shows the latest briefing dispatched to agents + a manual "Run Now" button.
 */
import { useEffect, useState } from 'react'
import { agentsApi } from '@/lib/api/agents'

interface SchedulerStatus {
  running: boolean
  jobs?: Array<{ id: string; name: string; next_run_time: string | null }>
  reason?: string
}

interface BriefingResult {
  started_at?: string
  agents_woken?: number
  agents_triggered?: number
  briefing_sent?: boolean
  briefing_preview?: string
  agent_summaries?: Array<{
    agent_id: string
    name: string
    channel: string
    character: string
    task_id?: string
  }>
  errors?: string[]
  message?: string
}

export default function MorningBriefingPage() {
  const [status, setStatus] = useState<SchedulerStatus | null>(null)
  const [briefing, setBriefing] = useState<BriefingResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    agentsApi.schedulerStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  const runManually = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await agentsApi.triggerMorningBriefing()
      setBriefing(result)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to trigger morning briefing')
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

      {/* Latest briefing result */}
      {briefing && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="text-lg font-semibold mb-2">Latest Run</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4 text-sm">
            <div>
              <div className="text-gray-400">Started</div>
              <div>
                {briefing.started_at ? new Date(briefing.started_at).toLocaleTimeString() : '-'}
              </div>
            </div>
            <div>
              <div className="text-gray-400">Agents woken</div>
              <div className="text-xl font-bold">{briefing.agents_woken ?? 0}</div>
            </div>
            <div>
              <div className="text-gray-400">Triggered</div>
              <div className="text-xl font-bold">{briefing.agents_triggered ?? 0}</div>
            </div>
            <div>
              <div className="text-gray-400">Briefing dispatched</div>
              <div>{briefing.briefing_sent ? '✓ Yes' : '✗ No'}</div>
            </div>
          </div>

          {briefing.agent_summaries && briefing.agent_summaries.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-semibold mb-2">Per-agent</h3>
              <div className="space-y-1 text-sm">
                {briefing.agent_summaries.map((a) => (
                  <div key={a.agent_id} className="flex justify-between">
                    <span>
                      <span className="font-medium">{a.name}</span>{' '}
                      <span className="text-gray-400">({a.channel})</span>
                    </span>
                    <span className="text-gray-400 text-xs">{a.character}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {briefing.briefing_preview && (
            <div>
              <h3 className="text-sm font-semibold mb-2">Briefing Text</h3>
              <pre className="text-xs bg-gray-900 rounded p-3 whitespace-pre-wrap">
                {briefing.briefing_preview}
              </pre>
            </div>
          )}

          {briefing.errors && briefing.errors.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-semibold text-red-400 mb-2">Errors</h3>
              <ul className="text-xs text-red-300 list-disc ml-5">
                {briefing.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
