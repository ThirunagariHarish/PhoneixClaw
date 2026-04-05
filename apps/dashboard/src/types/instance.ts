/**
 * Instance and network types.
 */

export interface ClaudeCodeInstance {
  id: string
  name: string
  host: string
  ssh_port: number
  ssh_username: string
  role: string
  status: string
  node_type: 'vps' | 'local'
  capabilities: Record<string, unknown>
  claude_version: string | null
  agent_count: number
  last_heartbeat_at?: string | null
  created_at: string
}

export interface NetworkNode {
  id: string
  type: 'instance' | 'agent' | 'service'
  label: string
  status: string
  parentId?: string
  data: Record<string, unknown>
}

export interface NetworkEdge {
  id: string
  source: string
  target: string
  label?: string
  animated?: boolean
}

export interface NetworkGraph {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
}
