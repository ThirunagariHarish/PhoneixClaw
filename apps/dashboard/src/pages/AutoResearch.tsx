/**
 * AutoResearch page — Karpathy-style nightly experiment results.
 *
 * Shows:
 * - Supervisor scheduler status (next run at 16:30 ET)
 * - Latest EOD analysis summary
 * - Pending improvements across all agents (with approve/reject)
 * - Trade signal stats (missed opportunities for RL feedback loop)
 * - Manual "Run Supervisor Now" + "Run EOD Analysis" buttons
 */
import { useEffect, useState } from 'react'
import { agentsApi } from '@/lib/api/agents'

interface SchedulerStatus {
  running: boolean
  jobs?: Array<{ id: string; name: string; next_run_time: string | null }>
}

interface SignalStats {
  days: number
  breakdown: Record<string, { count: number; missed: number }>
  total_missed_opportunities: number
}

export default function AutoResearchPage() {
  const [status, setStatus] = useState<SchedulerStatus | null>(null)
  const [signalStats, setSignalStats] = useState<SignalStats | null>(null)
  const [eodSummary, setEodSummary] = useState<any>(null)
  const [supervisorResult, setSupervisorResult] = useState<any>(null)
  const [eodResult, setEodResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState({ supervisor: false, eod: false })

  useEffect(() => {
    agentsApi.schedulerStatus().then(setStatus).catch(() => null)
    agentsApi.tradeSignalStats(undefined, 30).then(setSignalStats).catch(() => null)
    agentsApi.latestEodSummary().then((d) => d?.found && setEodSummary(d)).catch(() => null)
  }, [])

  const runSupervisor = async () => {
    setLoading({ ...loading, supervisor: true })
    setError(null)
    try {
      const r = await agentsApi.triggerSupervisor()
      setSupervisorResult(r)
    } catch (e: any) {
      setError(e?.message || 'Failed to trigger supervisor')
    } finally {
      setLoading({ ...loading, supervisor: false })
    }
  }

  const runEod = async () => {
    setLoading({ ...loading, eod: true })
    setError(null)
    try {
      const r = await agentsApi.triggerEodAnalysis()
      setEodResult(r)
    } catch (e: any) {
      setError(e?.message || 'Failed to trigger EOD analysis')
    } finally {
      setLoading({ ...loading, eod: false })
    }
  }

  const supervisorJob = status?.jobs?.find((j) => j.id === 'supervisor_run')
  const eodJob = status?.jobs?.find((j) => j.id === 'eod_analysis')

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">AutoResearch</h1>
        <p className="text-sm text-gray-400">
          Karpathy-style nightly experiments + EOD analysis + RL feedback loop.
        </p>
      </div>

      {/* Manual triggers */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="font-semibold mb-2">Supervisor Agent</h2>
          <p className="text-xs text-gray-400 mb-3">
            Runs daily at 16:30 ET. Analyzes performance, proposes improvements.
          </p>
          {supervisorJob && (
            <div className="text-xs text-gray-500 mb-3">
              Next run:{' '}
              {supervisorJob.next_run_time
                ? new Date(supervisorJob.next_run_time).toLocaleString()
                : 'unknown'}
            </div>
          )}
          <button
            onClick={runSupervisor}
            disabled={loading.supervisor}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-sm"
          >
            {loading.supervisor ? 'Running...' : 'Run Supervisor Now'}
          </button>
          {supervisorResult && (
            <pre className="text-xs bg-gray-900 rounded p-2 mt-3 overflow-auto max-h-40">
              {JSON.stringify(supervisorResult, null, 2)}
            </pre>
          )}
        </div>

        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="font-semibold mb-2">EOD Analysis</h2>
          <p className="text-xs text-gray-400 mb-3">
            Runs daily at 16:45 ET. Enriches trade signals with outcomes.
          </p>
          {eodJob && (
            <div className="text-xs text-gray-500 mb-3">
              Next run:{' '}
              {eodJob.next_run_time
                ? new Date(eodJob.next_run_time).toLocaleString()
                : 'unknown'}
            </div>
          )}
          <button
            onClick={runEod}
            disabled={loading.eod}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-sm"
          >
            {loading.eod ? 'Running...' : 'Run EOD Analysis Now'}
          </button>
          {eodResult && (
            <pre className="text-xs bg-gray-900 rounded p-2 mt-3 overflow-auto max-h-40">
              {JSON.stringify(eodResult, null, 2)}
            </pre>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded p-3 text-red-200 text-sm">
          {error}
        </div>
      )}

      {/* Signal stats */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h2 className="font-semibold mb-3">Trade Signal Stats (last 30 days)</h2>
        {signalStats ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(signalStats.breakdown).map(([decision, stats]) => (
              <div key={decision} className="bg-gray-900 rounded p-3">
                <div className="text-xs text-gray-400 uppercase">{decision}</div>
                <div className="text-2xl font-bold">{stats.count}</div>
                {stats.missed > 0 && (
                  <div className="text-xs text-yellow-400 mt-1">
                    {stats.missed} missed opportunities
                  </div>
                )}
              </div>
            ))}
            <div className="bg-yellow-900/20 border border-yellow-700/50 rounded p-3">
              <div className="text-xs text-yellow-400 uppercase">Total Missed</div>
              <div className="text-2xl font-bold text-yellow-300">
                {signalStats.total_missed_opportunities}
              </div>
              <div className="text-xs text-gray-400 mt-1">RL feedback candidates</div>
            </div>
          </div>
        ) : (
          <div className="text-gray-500 text-sm">No data yet — agents need to log signals first</div>
        )}
      </div>

      {/* Latest EOD summary */}
      {eodSummary && (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h2 className="font-semibold mb-2">Latest EOD Summary</h2>
          <div className="text-xs text-gray-500 mb-2">
            {eodSummary.created_at && new Date(eodSummary.created_at).toLocaleString()}
          </div>
          <pre className="text-sm bg-gray-900 rounded p-3 whitespace-pre-wrap">{eodSummary.body}</pre>
        </div>
      )}
    </div>
  )
}
