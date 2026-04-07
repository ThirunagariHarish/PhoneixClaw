/**
 * AgentSkillsTab — "Skills / Tools" tab for the Agent Detail page.
 * Fetches GET /api/v2/agents/:id/manifest and renders:
 *   - Character & Identity section
 *   - Tools section (capability cards)
 *   - Skills section (capability cards)
 *   - MCP Servers section (derived from agent.config)
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Wrench,
  BookOpen,
  Server,
  AlertCircle,
  FlaskConical,
  User,
  Activity,
} from 'lucide-react'

/* ─────────────────────────────────────────────
   TypeScript interfaces — architecture contract
───────────────────────────────────────────── */

type ToolCategory =
  | 'trading'
  | 'analysis'
  | 'data'
  | 'risk'
  | 'reporting'
  | 'execution'
  | 'unknown'

interface ManifestTool {
  name: string
  description?: string
  category?: string
  enabled?: boolean
  parameters?: Record<string, unknown>
}

interface ManifestSkill {
  name: string
  description?: string
  category?: string
}

interface ManifestIdentity {
  name?: string
  channel?: string
  analyst?: string
  character?: string
}

interface ManifestModes {
  [modeName: string]: unknown
}

interface AgentManifestPayload {
  version?: string
  template?: string
  identity?: ManifestIdentity
  tools?: ManifestTool[] | string[]
  skills?: ManifestSkill[] | string[]
  modes?: ManifestModes
  risk?: Record<string, unknown>
  models?: Record<string, unknown>
  knowledge?: Record<string, unknown>
}

interface ManifestResponse {
  agent_id: string
  manifest: AgentManifestPayload
  current_mode: string
  rules_version: number
}

type MCPMode = 'paper' | 'live'

interface MCPServer {
  id: string
  displayName: string
  mode: MCPMode
  status: 'connected'
}

interface ToolMeta {
  description: string
  category: ToolCategory
}

/* ─────────────────────────────────────────────
   Component prop shapes
───────────────────────────────────────────── */

interface AgentSkillsTabProps {
  agentId: string
  agent: {
    type: string
    config: Record<string, unknown>
  }
}

interface CapabilityCardProps {
  name: string
  description: string
  category: ToolCategory
  active: boolean
}

interface MCPServerCardProps {
  server: MCPServer
}

/* ─────────────────────────────────────────────
   Static metadata constants
───────────────────────────────────────────── */

const TOOL_META: Record<string, ToolMeta> = {
  discord_redis_consumer: {
    description: 'Reads Discord signal messages from Redis stream',
    category: 'data',
  },
  inference: {
    description: 'Runs ML model inference for trade confidence scoring',
    category: 'analysis',
  },
  enrich_single: {
    description: 'Enriches a ticker with real-time market data (price, volume, IV)',
    category: 'data',
  },
  risk_check: {
    description: 'Validates trade against risk rules (position size, daily loss limit)',
    category: 'risk',
  },
  robinhood_mcp: {
    description: 'MCP server for Robinhood: place orders, manage watchlist, get quotes',
    category: 'trading',
  },
  technical_analysis: {
    description: 'Chart pattern recognition (RSI, MACD, VWAP, support/resistance)',
    category: 'analysis',
  },
  portfolio_tracker: {
    description: 'Tracks open positions, P&L, and equity curve',
    category: 'trading',
  },
  position_monitor: {
    description: 'Monitors open positions and triggers stop-loss/take-profit',
    category: 'trading',
  },
  pre_market_analyzer: {
    description: 'Pre-market gap scan, futures analysis, sector rotation detection',
    category: 'analysis',
  },
  decision_engine: {
    description: 'Final trade decision: aggregates all signals into a go/no-go',
    category: 'trading',
  },
  report_to_phoenix: {
    description: 'Reports activity back to the Phoenix API',
    category: 'reporting',
  },
  paper_portfolio: {
    description: 'Paper trading portfolio simulation',
    category: 'trading',
  },
  live_pipeline: {
    description: 'End-to-end live trading pipeline orchestrator',
    category: 'trading',
  },
  exit_decision: {
    description: 'Determines when to exit a position',
    category: 'trading',
  },
  strategy_executor: {
    description: 'Executes a named trading strategy',
    category: 'trading',
  },
}

const SKILL_META: Record<string, ToolMeta> = {
  'discord_monitor.md': {
    description: 'How to monitor Discord for trade signals',
    category: 'data',
  },
  'trade_execution.md': {
    description: 'How to execute trades (entry, sizing, confirmation)',
    category: 'trading',
  },
  'risk_management.md': {
    description: 'Risk rules, position sizing, daily loss limits',
    category: 'risk',
  },
  'position_monitoring.md': {
    description: 'How to monitor and manage open positions',
    category: 'trading',
  },
  'daily_report.md': {
    description: 'Daily P&L and activity reporting format',
    category: 'reporting',
  },
  'swing_trade.md': {
    description: 'Swing trading strategy patterns and setup criteria',
    category: 'analysis',
  },
  'pre_market.md': {
    description: 'Pre-market analysis workflow',
    category: 'analysis',
  },
  'robinhood_auth.md': {
    description: 'Robinhood authentication and session management',
    category: 'trading',
  },
}

const CATEGORY_COLORS: Record<ToolCategory, string> = {
  trading: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  analysis: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  data: 'bg-green-500/20 text-green-400 border-green-500/30',
  risk: 'bg-red-500/20 text-red-400 border-red-500/30',
  reporting: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  execution: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  unknown: 'bg-muted text-muted-foreground',
}

/* ─────────────────────────────────────────────
   Helper functions
───────────────────────────────────────────── */

/** "robinhood_mcp" → "Robinhood MCP"  |  "trade_execution.md" → "Trade Execution" */
function formatName(name: string): string {
  return name
    .replace(/\.md$/, '')
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function normaliseCategory(raw?: string): ToolCategory {
  const valid: ToolCategory[] = [
    'trading',
    'analysis',
    'data',
    'risk',
    'reporting',
    'execution',
  ]
  if (raw && (valid as string[]).includes(raw)) {
    return raw as ToolCategory
  }
  return 'unknown'
}

/** Normalise manifest tools — handles both string[] and ManifestTool[] from backend */
function normaliseTools(raw?: ManifestTool[] | string[]): ManifestTool[] {
  if (!raw) return []
  return raw.map((item): ManifestTool => {
    if (typeof item === 'string') {
      const meta = TOOL_META[item]
      return {
        name: item,
        description: meta?.description,
        category: meta?.category,
        enabled: true,
      }
    }
    return item
  })
}

/** Normalise manifest skills — handles both string[] and ManifestSkill[] */
function normaliseSkills(raw?: ManifestSkill[] | string[]): ManifestSkill[] {
  if (!raw) return []
  return raw.map((item): ManifestSkill => {
    if (typeof item === 'string') {
      const meta = SKILL_META[item]
      return {
        name: item,
        description: meta?.description,
        category: meta?.category,
      }
    }
    return item
  })
}

function deriveMCPServers(config: Record<string, unknown>): MCPServer[] {
  const servers: MCPServer[] = []
  if (config.robinhood_credentials) {
    servers.push({
      id: 'robinhood',
      displayName: 'Robinhood',
      mode: config.paper_trading ? 'paper' : 'live',
      status: 'connected',
    })
  }
  return servers
}

/* ─────────────────────────────────────────────
   Sub-components
───────────────────────────────────────────── */

function CapabilityCard({ name, description, category, active }: CapabilityCardProps) {
  const colorClass = CATEGORY_COLORS[category]
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border/50 bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* Active / inactive indicator dot */}
          <span
            className={`h-2 w-2 rounded-full flex-shrink-0 ${
              active ? 'bg-green-400' : 'bg-muted-foreground/40'
            }`}
          />
          <span className="text-sm font-semibold leading-tight">{formatName(name)}</span>
        </div>
        <Badge
          variant="outline"
          className={`text-[10px] px-1.5 py-0 border ${colorClass} flex-shrink-0`}
        >
          {category}
        </Badge>
      </div>
      {description && (
        <p className="text-xs text-muted-foreground leading-relaxed">{description}</p>
      )}
    </div>
  )
}

function MCPServerCard({ server }: MCPServerCardProps) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border/50 bg-card p-3">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
          <Server className="h-4 w-4 text-muted-foreground" />
        </div>
        <div>
          <div className="text-sm font-semibold">{server.displayName}</div>
          <div className="text-xs text-muted-foreground">MCP Server</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge
          variant="outline"
          className="text-[10px] border bg-green-500/20 text-green-400 border-green-500/30"
        >
          connected
        </Badge>
        {server.mode === 'paper' ? (
          <Badge
            variant="outline"
            className="text-[10px] border bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
          >
            Paper Mode
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className="text-[10px] border bg-red-500/20 text-red-400 border-red-500/30"
          >
            Live
          </Badge>
        )}
      </div>
    </div>
  )
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="flex flex-col gap-2 rounded-lg border border-border/50 bg-card p-3"
        >
          <div className="flex items-center gap-2">
            <Skeleton className="h-2 w-2 rounded-full" />
            <Skeleton className="h-4 w-28" />
          </div>
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      ))}
    </div>
  )
}

/* ─────────────────────────────────────────────
   Main exported component
───────────────────────────────────────────── */

export function AgentSkillsTab({ agentId, agent }: AgentSkillsTabProps) {
  const queryClient = useQueryClient()
  const isBacktesting = agent.type === 'backtesting'

  const {
    data,
    isLoading,
    isError,
  } = useQuery<ManifestResponse>({
    queryKey: ['manifest', agentId],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}/manifest`)).data as ManifestResponse,
    staleTime: 30_000,
    enabled: !isBacktesting,
  })

  /* ── Backtesting placeholder (no fetch) ── */
  if (isBacktesting) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
          <FlaskConical className="h-10 w-10 text-muted-foreground/50" />
          <p className="text-sm font-medium text-muted-foreground">
            Tools are configured when the agent is promoted to live
          </p>
          <p className="text-xs text-muted-foreground/60">
            Backtesting agents do not have a live capability set.
          </p>
        </CardContent>
      </Card>
    )
  }

  /* ── Error state ── */
  if (isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
          <AlertCircle className="h-10 w-10 text-red-400/60" />
          <p className="text-sm font-medium">Failed to load agent capabilities</p>
          <p className="text-xs text-muted-foreground">
            The manifest endpoint returned an error.
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              queryClient.invalidateQueries({ queryKey: ['manifest', agentId] })
            }
          >
            Retry
          </Button>
        </CardContent>
      </Card>
    )
  }

  /* ── Loading state — show skeletons ── */
  if (isLoading) {
    return (
      <div className="space-y-6">
        {/* Identity skeleton */}
        <Card>
          <CardHeader className="pb-3">
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="flex flex-col gap-1">
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="h-4 w-24" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        {/* Tools skeleton */}
        <div className="space-y-3">
          <Skeleton className="h-5 w-20" />
          <SkeletonGrid />
        </div>
        {/* Skills skeleton */}
        <div className="space-y-3">
          <Skeleton className="h-5 w-20" />
          <SkeletonGrid />
        </div>
        {/* MCP Servers skeleton */}
        <div className="space-y-3">
          <Skeleton className="h-5 w-28" />
          {[1, 2].map((i) => (
            <div
              key={i}
              className="flex items-center justify-between rounded-lg border border-border/50 bg-card p-3"
            >
              <div className="flex items-center gap-3">
                <Skeleton className="h-8 w-8 rounded-md" />
                <div className="flex flex-col gap-1">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-3 w-16" />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Skeleton className="h-4 w-16 rounded-full" />
                <Skeleton className="h-4 w-12 rounded-full" />
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const manifest = data?.manifest ?? {}
  const currentMode = data?.current_mode ?? ''
  const identity = manifest.identity ?? {}
  const tools = normaliseTools(manifest.tools as ManifestTool[] | string[] | undefined)
  const skills = normaliseSkills(manifest.skills as ManifestSkill[] | string[] | undefined)
  const mcpServers = deriveMCPServers(agent.config)

  return (
    <div className="space-y-6">
      {/* ── Character & Identity ── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <User className="h-4 w-4" />
            Character &amp; Identity
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Character
              </span>
              <span className="text-sm">{identity.character ?? '—'}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Analyst
              </span>
              <span className="text-sm">{identity.analyst ?? '—'}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Channel
              </span>
              <span className="text-sm">
                {identity.channel ? `#${identity.channel}` : '—'}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Active Mode
              </span>
              {currentMode ? (
                <Badge
                  variant="outline"
                  className="w-fit text-xs bg-blue-500/20 text-blue-400 border-blue-500/30"
                >
                  <Activity className="mr-1 h-3 w-3" />
                  {currentMode}
                </Badge>
              ) : (
                <span className="text-sm text-muted-foreground">—</span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Tools ── */}
      <div className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Wrench className="h-4 w-4 text-muted-foreground" />
          Tools
          <span className="text-xs font-normal text-muted-foreground">
            ({tools.length})
          </span>
        </h3>
        {tools.length === 0 ? (
          <p className="text-sm text-muted-foreground">No tools configured</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {tools.map((tool) => {
              const meta = TOOL_META[tool.name]
              const category = normaliseCategory(tool.category ?? meta?.category)
              const description =
                tool.description ?? meta?.description ?? 'No description available'
              const active = tool.enabled !== false
              return (
                <CapabilityCard
                  key={tool.name}
                  name={tool.name}
                  description={description}
                  category={category}
                  active={active}
                />
              )
            })}
          </div>
        )}
      </div>

      {/* ── Skills ── */}
      <div className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <BookOpen className="h-4 w-4 text-muted-foreground" />
          Skills
          <span className="text-xs font-normal text-muted-foreground">
            ({skills.length})
          </span>
        </h3>
        {skills.length === 0 ? (
          <p className="text-sm text-muted-foreground">No skills configured</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {skills.map((skill) => {
              const meta = SKILL_META[skill.name]
              const category = normaliseCategory(skill.category ?? meta?.category)
              const description =
                skill.description ?? meta?.description ?? 'No description available'
              return (
                <CapabilityCard
                  key={skill.name}
                  name={skill.name}
                  description={description}
                  category={category}
                  active={true}
                />
              )
            })}
          </div>
        )}
      </div>

      {/* ── MCP Servers ── */}
      <div className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Server className="h-4 w-4 text-muted-foreground" />
          MCP Servers
          <span className="text-xs font-normal text-muted-foreground">
            ({mcpServers.length})
          </span>
        </h3>
        {mcpServers.length === 0 ? (
          <p className="text-sm text-muted-foreground">No MCP servers connected</p>
        ) : (
          <div className="flex flex-col gap-2">
            {mcpServers.map((server) => (
              <MCPServerCard key={server.id} server={server} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
