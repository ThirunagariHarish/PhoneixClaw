/**
 * AgentDashboard unit tests — PipelineStatsPanel component logic.
 *
 * Tests:
 *  - Panel renders with stats when runtime_info.pipeline_stats present
 *  - Panel hidden when pipeline_stats is null/undefined
 *  - Empty state when signals_processed=0 && worker_status=RUNNING
 *  - Offline state when worker_status=STOPPED
 */
import { describe, it, expect } from 'vitest'

interface PipelineStats {
  signals_processed: number
  trades_executed: number
  signals_skipped: number
  last_heartbeat: string | null
  uptime_seconds: number
  circuit_state: 'open' | 'closed' | 'half_open'
}

interface AgentData {
  engine_type?: 'sdk' | 'pipeline'
  worker_status?: string
  runtime_info?: {
    pipeline_stats?: PipelineStats
  }
  error_message?: string
}

// Helper functions extracted from PipelineStatsPanel component
function shouldShowPanel(agent: AgentData): boolean {
  return agent.engine_type === 'pipeline' && !!agent.runtime_info?.pipeline_stats
}

function shouldShowWaitingState(agent: AgentData): boolean {
  const stats = agent.runtime_info?.pipeline_stats
  if (!stats) return false
  return stats.signals_processed === 0 && agent.worker_status === 'RUNNING'
}

function shouldShowOfflineState(agent: AgentData): boolean {
  return agent.worker_status === 'STOPPED'
}

function shouldShowErrorState(agent: AgentData): boolean {
  return agent.worker_status === 'ERROR' && !!agent.error_message
}

function isHeartbeatStale(heartbeat: string | null, workerStatus?: string): boolean {
  if (!heartbeat || workerStatus !== 'RUNNING') return false
  const diff = Date.now() - new Date(heartbeat).getTime()
  return diff > 5 * 60 * 1000
}

describe('PipelineStatsPanel – rendering logic', () => {
  it('panel_shown_when_pipeline_with_stats — returns true when engine=pipeline and stats present', () => {
    const agent: AgentData = {
      engine_type: 'pipeline',
      runtime_info: {
        pipeline_stats: {
          signals_processed: 42,
          trades_executed: 7,
          signals_skipped: 35,
          last_heartbeat: new Date().toISOString(),
          uptime_seconds: 3600,
          circuit_state: 'closed',
        },
      },
    }
    expect(shouldShowPanel(agent)).toBe(true)
  })

  it('panel_hidden_when_sdk_engine — returns false when engine=sdk', () => {
    const agent: AgentData = {
      engine_type: 'sdk',
    }
    expect(shouldShowPanel(agent)).toBe(false)
  })

  it('panel_hidden_when_no_stats — returns false when runtime_info.pipeline_stats missing', () => {
    const agent: AgentData = {
      engine_type: 'pipeline',
      runtime_info: {},
    }
    expect(shouldShowPanel(agent)).toBe(false)
  })

  it('waiting_state_when_zero_signals — shows waiting when signals_processed=0 and RUNNING', () => {
    const agent: AgentData = {
      engine_type: 'pipeline',
      worker_status: 'RUNNING',
      runtime_info: {
        pipeline_stats: {
          signals_processed: 0,
          trades_executed: 0,
          signals_skipped: 0,
          last_heartbeat: null,
          uptime_seconds: 10,
          circuit_state: 'closed',
        },
      },
    }
    expect(shouldShowWaitingState(agent)).toBe(true)
  })

  it('no_waiting_state_when_signals_present — no waiting when signals_processed > 0', () => {
    const agent: AgentData = {
      engine_type: 'pipeline',
      worker_status: 'RUNNING',
      runtime_info: {
        pipeline_stats: {
          signals_processed: 1,
          trades_executed: 0,
          signals_skipped: 0,
          last_heartbeat: new Date().toISOString(),
          uptime_seconds: 10,
          circuit_state: 'closed',
        },
      },
    }
    expect(shouldShowWaitingState(agent)).toBe(false)
  })

  it('offline_state_when_stopped — shows offline when worker_status=STOPPED', () => {
    const agent: AgentData = {
      worker_status: 'STOPPED',
    }
    expect(shouldShowOfflineState(agent)).toBe(true)
  })

  it('error_state_when_worker_error — shows error when worker_status=ERROR and error_message set', () => {
    const agent: AgentData = {
      worker_status: 'ERROR',
      error_message: 'Pipeline worker crashed',
    }
    expect(shouldShowErrorState(agent)).toBe(true)
  })

  it('no_error_state_without_message — no error banner when error_message null', () => {
    const agent: AgentData = {
      worker_status: 'ERROR',
      error_message: undefined,
    }
    expect(shouldShowErrorState(agent)).toBe(false)
  })

  it('heartbeat_stale_when_old — detects stale heartbeat >5 minutes', () => {
    const oldHeartbeat = new Date(Date.now() - 10 * 60 * 1000).toISOString()
    expect(isHeartbeatStale(oldHeartbeat, 'RUNNING')).toBe(true)
  })

  it('heartbeat_fresh_when_recent — no stale warning when heartbeat <5 minutes', () => {
    const recentHeartbeat = new Date(Date.now() - 2 * 60 * 1000).toISOString()
    expect(isHeartbeatStale(recentHeartbeat, 'RUNNING')).toBe(false)
  })

  it('heartbeat_not_stale_when_stopped — no stale warning when worker_status not RUNNING', () => {
    const oldHeartbeat = new Date(Date.now() - 10 * 60 * 1000).toISOString()
    expect(isHeartbeatStale(oldHeartbeat, 'STOPPED')).toBe(false)
  })
})
