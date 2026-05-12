import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface BacktestStepLog {
  id: string
  backtest_id: string
  step: string
  sub_progress_pct: number
  message: string
  ts: string
}

interface UseBacktestProgressOptions {
  agentId: string | null
  backtestId: string | null
  isRunning: boolean
}

/**
 * Polls /api/v2/agents/{agent_id}/backtest-progress-log for substep progress.
 * Fallback: if endpoint 404s, returns empty array (caller should fall back to existing progress data).
 *
 * TODO: Backend endpoint /api/v2/agents/{agent_id}/backtest-progress-log?limit=50 not yet implemented.
 * Once implemented, this hook will provide real-time substep granularity.
 */
export function useBacktestProgress({
  agentId,
  backtestId,
  isRunning,
}: UseBacktestProgressOptions) {
  return useQuery({
    queryKey: ['backtest-progress-log', agentId, backtestId],
    queryFn: async () => {
      if (!agentId) return []

      try {
        const response = await api.get<BacktestStepLog[]>(
          `/api/v2/agents/${agentId}/backtest-progress-log`,
          { params: { limit: 50 } }
        )
        return Array.isArray(response.data) ? response.data : []
      } catch (error: any) {
        // Fallback behavior: if endpoint doesn't exist yet (404), return empty array
        // Caller should gracefully hide the substep UI section
        if (error.response?.status === 404) {
          return []
        }
        throw error
      }
    },
    enabled: !!agentId && !!backtestId && isRunning,
    refetchInterval: isRunning ? 2000 : false, // Poll every 2s while RUNNING
    retry: false, // Don't retry 404s
  })
}
