import { useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface AgentNode {
  id: string
  name: string
  status: string
  type: string
  character: string
  tools: string[]
  channels: string[]
  win_rate: number | null
  total_trades: number | null
}

interface AgentEdge {
  from: string
  to: string
  type: string
  intent: string | null
  count: number
  last_message_at: string | null
}

interface GraphData {
  nodes: AgentNode[]
  edges: AgentEdge[]
}

const STATUS_COLORS: Record<string, string> = {
  live: '#22c55e',
  paper: '#3b82f6',
  backtesting: '#eab308',
  approved: '#a855f7',
  pending: '#6b7280',
  error: '#ef4444',
}

function statusBg(status: string): string {
  return STATUS_COLORS[status] || '#6b7280'
}

function AgentNodeContent({ data }: { data: Record<string, unknown> }) {
  const status = data.status as string
  const color = statusBg(status)
  return (
    <div
      className="rounded-xl border-2 bg-card text-card-foreground shadow-lg px-4 py-3 min-w-[180px] cursor-pointer hover:shadow-xl transition-shadow"
      style={{ borderColor: color }}
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="w-2.5 h-2.5 rounded-full animate-pulse" style={{ backgroundColor: color }} />
        <span className="font-semibold text-sm truncate max-w-[140px]">{data.label as string}</span>
      </div>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Badge variant="outline" className="text-[10px] px-1.5 py-0">{status}</Badge>
        <span className="truncate">{data.character as string}</span>
      </div>
      {(data.win_rate != null || data.total_trades != null) && (
        <div className="flex gap-3 mt-1.5 text-[10px] text-muted-foreground">
          {data.win_rate != null && <span>WR: {(data.win_rate as number).toFixed(1)}%</span>}
          {data.total_trades != null && <span>Trades: {data.total_trades as number}</span>}
        </div>
      )}
      {(data.channels as string[]).length > 0 && (
        <div className="mt-1 text-[10px] text-muted-foreground truncate">
          #{(data.channels as string[]).join(', #')}
        </div>
      )}
    </div>
  )
}

const nodeTypes = { agentNode: AgentNodeContent }

function layoutNodes(agents: AgentNode[]): Node[] {
  const cols = Math.max(3, Math.ceil(Math.sqrt(agents.length)))
  const xSpacing = 280
  const ySpacing = 160
  return agents.map((a, i) => ({
    id: a.id,
    type: 'agentNode',
    position: { x: (i % cols) * xSpacing + 40, y: Math.floor(i / cols) * ySpacing + 40 },
    data: {
      label: a.name,
      status: a.status,
      character: a.character,
      win_rate: a.win_rate,
      total_trades: a.total_trades,
      channels: a.channels,
      tools: a.tools,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  }))
}

function buildEdges(raw: AgentEdge[]): Edge[] {
  return raw.map((e, i) => ({
    id: `e-${i}`,
    source: e.from,
    target: e.to,
    label: e.count > 1 ? `${e.count} msgs` : (e.intent || ''),
    animated: true,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { strokeWidth: Math.min(1 + e.count * 0.5, 4) },
  }))
}

export default function AgentGraphPage() {
  const navigate = useNavigate()
  const { data: graphData } = useQuery<GraphData>({
    queryKey: ['agent-graph'],
    queryFn: async () => (await api.get('/api/v2/agents/graph')).data,
    refetchInterval: 15000,
  })

  const initialNodes = useMemo(() => layoutNodes(graphData?.nodes || []), [graphData?.nodes])
  const initialEdges = useMemo(() => buildEdges(graphData?.edges || []), [graphData?.edges])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  useMemo(() => { setNodes(initialNodes) }, [initialNodes, setNodes])
  useMemo(() => { setEdges(initialEdges) }, [initialEdges, setEdges])

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    navigate(`/agents/${node.id}`)
  }, [navigate])

  const liveCount = graphData?.nodes.filter(n => n.status === 'live').length ?? 0
  const paperCount = graphData?.nodes.filter(n => n.status === 'paper').length ?? 0
  const totalEdges = graphData?.edges.length ?? 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Agent Network</h1>
          <p className="text-sm text-muted-foreground">
            Visual topology of all agents and their communication links
          </p>
        </div>
        <div className="flex gap-2">
          {Object.entries(STATUS_COLORS).map(([s, c]) => (
            <div key={s} className="flex items-center gap-1 text-xs text-muted-foreground">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: c }} />
              {s}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Card><CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground">Live Agents</CardTitle></CardHeader><CardContent className="pt-0"><p className="text-2xl font-bold">{liveCount}</p></CardContent></Card>
        <Card><CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground">Paper Agents</CardTitle></CardHeader><CardContent className="pt-0"><p className="text-2xl font-bold">{paperCount}</p></CardContent></Card>
        <Card><CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground">Active Links (24h)</CardTitle></CardHeader><CardContent className="pt-0"><p className="text-2xl font-bold">{totalEdges}</p></CardContent></Card>
      </div>

      <Card className="overflow-hidden" style={{ height: 'calc(100vh - 280px)' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} />
          <Controls />
          <MiniMap
            nodeStrokeWidth={3}
            nodeColor={(n) => statusBg((n.data as Record<string, unknown>)?.status as string || 'pending')}
          />
        </ReactFlow>
      </Card>
    </div>
  )
}
