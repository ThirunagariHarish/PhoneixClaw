/**
 * Domain-specific API modules for agents.
 */
import api from '@/lib/api'
import type { Agent, AgentBacktest } from '@/types/agent'

export const agentsApi = {
  list: () => api.get<Agent[]>('/api/v2/agents').then((r) => r.data),
  get: (id: string) => api.get<Agent>(`/api/v2/agents/${id}`).then((r) => r.data),
  create: (data: Partial<Agent>) => api.post<Agent>('/api/v2/agents', data).then((r) => r.data),
  update: (id: string, data: Partial<Agent>) => api.put<Agent>(`/api/v2/agents/${id}`, data).then((r) => r.data),
  remove: (id: string) => api.delete(`/api/v2/agents/${id}`),
  pause: (id: string) => api.post(`/api/v2/agents/${id}/pause`),
  resume: (id: string) => api.post(`/api/v2/agents/${id}/resume`),
  stats: (id: string) => api.get(`/api/v2/agents/${id}/stats`).then((r) => r.data),
  backtests: (id: string) => api.get<AgentBacktest[]>(`/api/v2/backtests?agent_id=${id}`).then((r) => r.data),

  // ── Phase A2: previously-unwired endpoints ──
  paperPortfolio: (id: string) =>
    api.get(`/api/v2/agents/${id}/paper-portfolio`).then((r) => r.data),

  activityFeed: (id: string, limit = 100) =>
    api.get(`/api/v2/agents/${id}/activity-feed?limit=${limit}`).then((r) => r.data),

  positionAgents: (id: string) =>
    api.get(`/api/v2/agents/${id}/position-agents`).then((r) => r.data),

  pendingImprovements: (id: string) =>
    api.get(`/api/v2/agents/${id}/pending-improvements`).then((r) => r.data),

  approveImprovement: (agentId: string, changeId: string) =>
    api.post(`/api/v2/agents/${agentId}/pending-improvements/${changeId}/approve`).then((r) => r.data),

  rejectImprovement: (agentId: string, changeId: string) =>
    api.post(`/api/v2/agents/${agentId}/pending-improvements/${changeId}/reject`).then((r) => r.data),

  instruct: (id: string, instruction: string) =>
    api.post(`/api/v2/agents/${id}/instruct`, { instruction }).then((r) => r.data),

  runtimeInfo: (id: string) =>
    api.get(`/api/v2/agents/${id}/runtime-info`).then((r) => r.data),

  graph: () => api.get(`/api/v2/agents/graph`).then((r) => r.data),

  // ── Scheduler / system ──
  triggerMorningBriefing: () =>
    api.post(`/api/v2/agents/morning-briefing`).then((r) => r.data),

  triggerSupervisor: () =>
    api.post(`/api/v2/agents/supervisor/run`).then((r) => r.data),

  triggerEodAnalysis: () =>
    api.post(`/api/v2/agents/eod-analysis`).then((r) => r.data),

  latestEodSummary: () =>
    api.get(`/api/v2/agents/eod-analysis/latest`).then((r) => r.data),

  schedulerStatus: () =>
    api.get(`/api/v2/scheduler/status`).then((r) => r.data),

  // ── Trade signals (RL feedback) ──
  tradeSignals: (params: {
    agent_id?: string
    decision?: string
    missed_only?: boolean
    days?: number
    limit?: number
  }) => api.get('/api/v2/trade-signals', { params }).then((r) => r.data),

  tradeSignalStats: (agent_id?: string, days = 30) =>
    api.get('/api/v2/trade-signals/stats', { params: { agent_id, days } }).then((r) => r.data),
}
