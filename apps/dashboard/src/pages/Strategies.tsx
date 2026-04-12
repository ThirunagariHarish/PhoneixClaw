/**
 * Strategies page — strategy leaderboard + enriched cards + 4-step creation wizard.
 * Step 1: Select strategy from 50-template catalog
 * Step 2: Configure rules, backtest params, skills
 * Step 3: Select OpenClaw instance
 * Step 4: Review and create
 */
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Target, Plus, TrendingUp, TrendingDown, ArrowRight, Search, Check, ChevronLeft, ChevronRight, Rocket, Beaker, ArrowUpDown } from 'lucide-react'
import { AiAssistPopover } from '@/components/AiAssistPopover'
import { AgentLeaderboardTable, type AgentLeaderData } from '@/components/AgentLeaderCard'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

/* ── Types ─────────────────────────────────────────────────────────────── */

interface StrategyTemplate {
  id: string
  name: string
  category: string
  description: string
  default_symbol: string
  default_config: Record<string, unknown>
  skills_required: string[]
  legs: Array<Record<string, unknown>>
  backtest_params: Record<string, unknown>
  ai_suitability: string
  win_rate_estimate: string
  risk_profile: string
}

interface Strategy {
  id: string
  name: string
  template_id: string
  symbol: string
  category: string | null
  description: string | null
  status: string
  config: Record<string, unknown>
  legs: Array<Record<string, unknown>>
  backtest_params: Record<string, unknown>
  skills_required: string[]
  agent_id: string | null
  backtest_pnl: number | null
  backtest_sharpe: number | null
  win_rate: number | null
  max_drawdown: number | null
  total_trades: number | null
  created_at: string
}

interface CategoryMeta {
  name: string
  count: number
}

/* ── Data ──────────────────────────────────────────────────────────────── */

/* ── Helpers ──────────────────────────────────────────────────────────── */

const AI_BADGE: Record<string, { color: string; label: string }> = {
  high: { color: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20', label: 'AI High' },
  medium: { color: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20', label: 'AI Medium' },
  low: { color: 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/20', label: 'AI Low' },
}

function strategyToLeader(s: Strategy, idx: number): AgentLeaderData {
  return {
    id: s.agent_id || s.id,
    rank: idx + 1,
    name: s.name,
    pnl: s.backtest_pnl ?? 0,
    winRate: s.win_rate ?? 0,
    sharpe: s.backtest_sharpe ?? 0,
    trades: s.total_trades ?? 0,
    status: s.status.toLowerCase() as AgentLeaderData['status'],
  }
}

/* ── Strategy Card ───────────────────────────────────────────────────── */

/* STR2: Mini equity sparkline for strategy cards */
function StrategySparkline({ pnl }: { pnl: number }) {
  // Generate a synthetic sparkline based on the P&L value
  const points = 20
  const data: number[] = []
  let v = 10000
  const target = 10000 + pnl
  const step = (target - v) / points
  for (let i = 0; i <= points; i++) {
    v += step + (Math.sin(i * 1.3) * Math.abs(step) * 0.4)
    data.push(v)
  }
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const w = 120
  const h = 24
  const polyPoints = data.map((val, i) => `${(i / points) * w},${h - ((val - min) / range) * h}`).join(' ')
  const isPositive = data[data.length - 1] >= data[0]
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-6" preserveAspectRatio="none">
      <polyline
        points={polyPoints}
        fill="none"
        stroke={isPositive ? '#22c55e' : '#ef4444'}
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

function StrategyCard({ strategy, onClick }: { strategy: Strategy; onClick: () => void }) {
  const pnlPositive = (strategy.backtest_pnl ?? 0) >= 0
  const PnlIcon = pnlPositive ? TrendingUp : TrendingDown

  return (
    <Card className="cursor-pointer hover:border-primary/50 hover:shadow-md transition-all group" onClick={onClick}>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Target className="h-4 w-4 text-primary shrink-0" />
              <span className="font-semibold text-sm truncate group-hover:text-primary transition-colors">{strategy.name}</span>
            </div>
            <div className="flex gap-1.5 mt-1.5 flex-wrap">
              {strategy.category && <Badge variant="outline" className="text-xs">{strategy.category}</Badge>}
              <StatusBadge status={strategy.status} />
            </div>
          </div>
          <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0 opacity-0 group-hover:opacity-100 transition-opacity mt-1" />
        </div>
        {/* STR2: Equity Curve Sparkline */}
        <StrategySparkline pnl={strategy.backtest_pnl ?? 0} />
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">P&L</span>
            <span className={cn('font-mono font-semibold flex items-center gap-1', pnlPositive ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
              <PnlIcon className="h-3 w-3" />
              {pnlPositive ? '+' : ''}${Math.abs(strategy.backtest_pnl ?? 0).toLocaleString()}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Win Rate</span>
            <span className="font-mono font-medium">{((strategy.win_rate ?? 0) * 100).toFixed(0)}%</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Sharpe</span>
            <span className="font-mono font-medium">{(strategy.backtest_sharpe ?? 0).toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Max DD</span>
            <span className="font-mono font-medium text-red-600 dark:text-red-400">{((strategy.max_drawdown ?? 0) * 100).toFixed(1)}%</span>
          </div>
          <div className="flex items-center justify-between col-span-2 pt-1 border-t border-border/50">
            <span className="text-muted-foreground">Total Trades</span>
            <span className="font-mono font-medium">{strategy.total_trades ?? 0}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/* ── Template Card (Step 1) ──────────────────────────────────────────── */

function TemplateCard({ tpl, selected, onClick }: { tpl: StrategyTemplate; selected: boolean; onClick: () => void }) {
  const badge = AI_BADGE[tpl.ai_suitability] ?? AI_BADGE.medium
  return (
    <Card
      className={cn(
        'cursor-pointer transition-all hover:shadow-md border-2',
        selected ? 'border-primary shadow-primary/10 bg-primary/5' : 'border-transparent hover:border-primary/30',
      )}
      onClick={onClick}
    >
      <CardContent className="p-3 space-y-2">
        <div className="flex items-start justify-between gap-1">
          <h4 className="text-sm font-semibold leading-tight line-clamp-2">{tpl.name}</h4>
          {selected && <Check className="h-4 w-4 text-primary shrink-0 mt-0.5" />}
        </div>
        <p className="text-xs text-muted-foreground line-clamp-2">{tpl.description}</p>
        <div className="flex flex-wrap gap-1">
          <Badge variant="outline" className={cn('text-[10px] border', badge.color)}>{badge.label}</Badge>
          <Badge variant="outline" className="text-[10px]">{tpl.win_rate_estimate}</Badge>
          <Badge variant="outline" className="text-[10px]">{tpl.default_symbol}</Badge>
        </div>
        <p className="text-[10px] text-muted-foreground italic truncate">{tpl.risk_profile}</p>
      </CardContent>
    </Card>
  )
}

/* ── Wizard Step Components ──────────────────────────────────────────── */

function WizardStep1({ templates, categories, selectedId, onSelect }: {
  templates: StrategyTemplate[]
  categories: CategoryMeta[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('All')

  const filtered = useMemo(() => {
    let list = templates
    if (categoryFilter !== 'All') {
      list = list.filter((t) => t.category === categoryFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter((t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q))
    }
    return list
  }, [templates, categoryFilter, search])

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Search 50 strategies..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <Tabs defaultValue="All" value={categoryFilter} onValueChange={setCategoryFilter}>
        <TabsList className="flex flex-wrap h-auto gap-1 bg-transparent p-0">
          <TabsTrigger value="All" className="text-xs h-7 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground">
            All ({templates.length})
          </TabsTrigger>
          {categories.map((c) => (
            <TabsTrigger key={c.name} value={c.name} className="text-xs h-7 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground">
              {c.name} ({c.count})
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="max-h-[45vh] overflow-y-auto pr-1 -mr-1">
        {filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">No strategies match your search.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {filtered.map((tpl) => (
              <TemplateCard
                key={tpl.id}
                tpl={tpl}
                selected={selectedId === tpl.id}
                onClick={() => onSelect(tpl.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface WizardFormState {
  template_id: string
  name: string
  symbol: string
  config: Record<string, unknown>
  backtest_params: Record<string, unknown>
  skills_required: string[]
  agent_role_description: string
  instance_id: string
  agent_name: string
}

function WizardStep2({ form, onChange, template }: {
  form: WizardFormState
  onChange: (patch: Partial<WizardFormState>) => void
  template: StrategyTemplate | null
}) {
  if (!template) return null

  const configKeys = Object.keys(template.default_config)
  const backtestKeys = Object.keys(template.backtest_params)

  const updateConfig = (key: string, value: unknown) => {
    onChange({ config: { ...form.config, [key]: value } })
  }
  const updateBacktest = (key: string, value: unknown) => {
    onChange({ backtest_params: { ...form.backtest_params, [key]: value } })
  }
  const toggleSkill = (skill: string) => {
    const skills = form.skills_required.includes(skill)
      ? form.skills_required.filter((s) => s !== skill)
      : [...form.skills_required, skill]
    onChange({ skills_required: skills })
  }

  return (
    <div className="space-y-4 max-h-[55vh] overflow-y-auto pr-1 -mr-1">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <Label>Symbol</Label>
          <Input value={form.symbol} onChange={(e) => onChange({ symbol: e.target.value })} placeholder="SPY" />
        </div>
        <div>
          <Label>Strategy Name</Label>
          <Input value={form.name} onChange={(e) => onChange({ name: e.target.value })} placeholder={template.name} />
        </div>
      </div>

      <div>
        <Label className="mb-2 block">Entry / Exit Rules</Label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {configKeys.map((key) => (
            <div key={key}>
              <Label className="text-xs text-muted-foreground capitalize">{key.replace(/_/g, ' ')}</Label>
              <Input
                value={String(form.config[key] ?? template.default_config[key] ?? '')}
                onChange={(e) => updateConfig(key, isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value))}
              />
            </div>
          ))}
        </div>
      </div>

      <div>
        <Label className="mb-2 block">Backtest Parameters</Label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {backtestKeys.map((key) => (
            <div key={key}>
              <Label className="text-xs text-muted-foreground capitalize">{key.replace(/_/g, ' ')}</Label>
              <Input
                value={String(form.backtest_params[key] ?? template.backtest_params[key] ?? '')}
                onChange={(e) => updateBacktest(key, e.target.value)}
              />
            </div>
          ))}
        </div>
      </div>

      <div>
        <Label className="mb-2 block">Skills Required</Label>
        <div className="flex flex-wrap gap-2">
          {(template.skills_required || []).map((skill) => (
            <Badge
              key={skill}
              variant={form.skills_required.includes(skill) ? 'default' : 'outline'}
              className="cursor-pointer select-none"
              onClick={() => toggleSkill(skill)}
            >
              {form.skills_required.includes(skill) && <Check className="h-3 w-3 mr-1" />}
              {skill.replace(/_/g, ' ')}
            </Badge>
          ))}
        </div>
      </div>

      <AiAssistPopover
        label="Agent Role Description"
        value={form.agent_role_description}
        onChange={(v) => onChange({ agent_role_description: v })}
        placeholder="Describe what this strategy agent should do..."
        multiline
        context="trading strategy agent role"
      />
    </div>
  )
}

function WizardStep3({ form, onChange, instances }: {
  form: WizardFormState
  onChange: (patch: Partial<WizardFormState>) => void
  instances: Array<{ id: string; name: string }>
}) {
  return (
    <div className="space-y-4">
      <div>
        <Label>Agent Name</Label>
        <Input
          value={form.agent_name}
          onChange={(e) => onChange({ agent_name: e.target.value })}
          placeholder={`${form.name || 'Strategy'} Agent`}
        />
        <p className="text-xs text-muted-foreground mt-1">The name of the OpenClaw agent that will execute this strategy.</p>
      </div>
      <div>
        <Label>OpenClaw Instance</Label>
        <p className="text-sm text-muted-foreground mb-2">Select the instance this strategy agent will run on.</p>
        <Select value={form.instance_id} onValueChange={(v) => onChange({ instance_id: v })}>
          <SelectTrigger><SelectValue placeholder="Select instance..." /></SelectTrigger>
          <SelectContent>
            {instances.map((inst) => (
              <SelectItem key={inst.id} value={inst.id}>{inst.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {instances.length === 0 && (
          <p className="text-sm text-amber-500 mt-2">No instances available. Create one in the Settings tab first.</p>
        )}
      </div>
    </div>
  )
}

function WizardStep4({ form, template, instanceName }: {
  form: WizardFormState
  template: StrategyTemplate | null
  instanceName: string
}) {
  if (!template) return null
  return (
    <div className="space-y-3 max-h-[55vh] overflow-y-auto pr-1 -mr-1">
      <div className="rounded-lg border p-3 space-y-2">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-primary" />
          <span className="font-semibold">{form.name || template.name}</span>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <span className="text-muted-foreground">Template</span>
          <span>{template.name}</span>
          <span className="text-muted-foreground">Category</span>
          <span>{template.category}</span>
          <span className="text-muted-foreground">Symbol</span>
          <span className="font-mono">{form.symbol}</span>
          <span className="text-muted-foreground">Win Rate Est.</span>
          <span>{template.win_rate_estimate}</span>
          <span className="text-muted-foreground">Risk Profile</span>
          <span>{template.risk_profile}</span>
          <span className="text-muted-foreground">Agent Name</span>
          <span>{form.agent_name || `${form.name || template.name} Agent`}</span>
          <span className="text-muted-foreground">Instance</span>
          <span>{instanceName || 'Not selected'}</span>
        </div>
      </div>

      <div className="rounded-lg border p-3">
        <p className="text-xs font-medium mb-1">Skills</p>
        <div className="flex flex-wrap gap-1">
          {form.skills_required.map((s) => (
            <Badge key={s} variant="secondary" className="text-[10px]">{s.replace(/_/g, ' ')}</Badge>
          ))}
        </div>
      </div>

      {form.agent_role_description && (
        <div className="rounded-lg border p-3">
          <p className="text-xs font-medium mb-1">Agent Description</p>
          <p className="text-xs text-muted-foreground">{form.agent_role_description}</p>
        </div>
      )}

      <div className="rounded-lg border p-3">
        <p className="text-xs font-medium mb-1">Configuration</p>
        <pre className="text-[10px] text-muted-foreground overflow-x-auto max-h-32">{JSON.stringify(form.config, null, 2)}</pre>
      </div>

      <div className="rounded-lg bg-primary/5 border border-primary/20 p-3 flex items-start gap-2">
        <Rocket className="h-4 w-4 text-primary mt-0.5 shrink-0" />
        <p className="text-xs text-muted-foreground">
          Clicking <strong>Create & Start Backtesting</strong> will create the strategy, provision an OpenClaw agent,
          and immediately begin backtesting. You can track progress on the agent dashboard.
        </p>
      </div>
    </div>
  )
}

/* ── Main Page ───────────────────────────────────────────────────────── */

const WIZARD_STEPS = ['Select Strategy', 'Configure', 'Instance', 'Review']

const EMPTY_FORM: WizardFormState = {
  template_id: '',
  name: '',
  symbol: '',
  config: {},
  backtest_params: {},
  skills_required: [],
  agent_role_description: '',
  instance_id: '',
  agent_name: '',
}

export default function StrategiesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [wizardStep, setWizardStep] = useState(0)
  const [form, setForm] = useState<WizardFormState>({ ...EMPTY_FORM })
  // STR1: Sort option
  const [sortBy, setSortBy] = useState<string>('pnl')

  const updateForm = (patch: Partial<WizardFormState>) => setForm((prev) => ({ ...prev, ...patch }))

  /* ── Data queries ──────────────────────────────────────────────────── */

  const { data: strategies = [] } = useQuery<Strategy[]>({
    queryKey: ['strategies'],
    queryFn: async () => {
      try {
        const result = await api.get('/api/v2/strategies')
        return result.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: templateData } = useQuery<{ templates: StrategyTemplate[]; categories: CategoryMeta[] }>({
    queryKey: ['strategy-templates'],
    queryFn: async () => {
      try {
        const result = await api.get('/api/v2/strategies/templates')
        if (result.data?.templates?.length) return result.data
        return null
      } catch {
        return null
      }
    },
  })

  const templates = templateData?.templates ?? []
  const categories = templateData?.categories ?? []

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data,
  })

  /* ── Create mutation ───────────────────────────────────────────────── */

  const createMutation = useMutation({
    mutationFn: async (payload: WizardFormState) => {
      const res = await api.post('/api/v2/strategies', {
        template_id: payload.template_id,
        name: payload.name,
        symbol: payload.symbol,
        config: payload.config,
        legs: [],
        backtest_params: payload.backtest_params,
        skills_required: payload.skills_required,
        instance_id: payload.instance_id,
        agent_name: payload.agent_name,
        agent_role_description: payload.agent_role_description,
      })
      return res.data
    },
    onSuccess: (data: Strategy) => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setCreateOpen(false)
      resetWizard()
      toast.success(`Strategy "${data.name}" created — backtesting started`)
      if (data.agent_id) {
        navigate(`/agents/${data.agent_id}`)
      }
    },
    onError: () => {
      toast.error('Failed to create strategy. Check API connection.')
    },
  })

  const resetWizard = () => {
    setWizardStep(0)
    setForm({ ...EMPTY_FORM })
  }

  /* ── Template selection handler ────────────────────────────────────── */

  const selectedTemplate = templates.find((t) => t.id === form.template_id) ?? null

  const handleTemplateSelect = (id: string) => {
    const tpl = templates.find((t) => t.id === id)
    if (!tpl) return
    setForm({
      ...EMPTY_FORM,
      template_id: id,
      name: tpl.name,
      symbol: tpl.default_symbol,
      config: { ...tpl.default_config },
      backtest_params: { ...tpl.backtest_params },
      skills_required: [...tpl.skills_required],
      agent_role_description: tpl.description,
      instance_id: form.instance_id,
      agent_name: `${tpl.name} Agent`,
    })
  }

  const canAdvance = (step: number): boolean => {
    switch (step) {
      case 0: return form.template_id.length > 0
      case 1: return form.symbol.trim().length > 0
      case 2: return form.instance_id.length > 0
      case 3: return true
      default: return false
    }
  }

  /* ── STR1: Sorted strategies ───────────────────────────────────────── */

  const sortedStrategies = useMemo(() => {
    const list = [...strategies]
    switch (sortBy) {
      case 'pnl': return list.sort((a, b) => (b.backtest_pnl ?? 0) - (a.backtest_pnl ?? 0))
      case 'sharpe': return list.sort((a, b) => (b.backtest_sharpe ?? 0) - (a.backtest_sharpe ?? 0))
      case 'win_rate': return list.sort((a, b) => (b.win_rate ?? 0) - (a.win_rate ?? 0))
      case 'max_dd': return list.sort((a, b) => (a.max_drawdown ?? 1) - (b.max_drawdown ?? 1)) // lower DD is better
      default: return list
    }
  }, [strategies, sortBy])

  const leaderData = sortedStrategies.map((s, i) => strategyToLeader(s, i))

  const instanceName = instances.find((i) => i.id === form.instance_id)?.name ?? ''

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Target} title="Strategies" description="Strategy agents, backtest results, and leaderboard">
        <Dialog open={createOpen} onOpenChange={(o) => { setCreateOpen(o); if (!o) resetWizard() }}>
          <DialogTrigger asChild>
            <Button><Plus className="h-4 w-4 mr-2" /> Create Strategy</Button>
          </DialogTrigger>
          <DialogContent className="w-[calc(100vw-2rem)] sm:w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Target className="h-5 w-5 text-primary" />
                Create Strategy
              </DialogTitle>
              {/* Step indicator */}
              <div className="flex items-center gap-1 pt-2">
                {WIZARD_STEPS.map((label, idx) => (
                  <div key={label} className="flex items-center gap-1">
                    <div className={cn(
                      'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all',
                      idx === wizardStep
                        ? 'bg-primary text-primary-foreground'
                        : idx < wizardStep
                          ? 'bg-primary/10 text-primary'
                          : 'bg-muted text-muted-foreground',
                    )}>
                      {idx < wizardStep ? <Check className="h-3 w-3" /> : <span>{idx + 1}</span>}
                      <span className="hidden sm:inline">{label}</span>
                    </div>
                    {idx < WIZARD_STEPS.length - 1 && (
                      <div className={cn('w-4 h-px', idx < wizardStep ? 'bg-primary' : 'bg-border')} />
                    )}
                  </div>
                ))}
              </div>
            </DialogHeader>

            <div className="flex-1 overflow-hidden py-2">
              {wizardStep === 0 && (
                <WizardStep1
                  templates={templates}
                  categories={categories}
                  selectedId={form.template_id}
                  onSelect={handleTemplateSelect}
                />
              )}
              {wizardStep === 1 && (
                <WizardStep2 form={form} onChange={updateForm} template={selectedTemplate} />
              )}
              {wizardStep === 2 && (
                <WizardStep3 form={form} onChange={updateForm} instances={instances} />
              )}
              {wizardStep === 3 && (
                <WizardStep4 form={form} template={selectedTemplate} instanceName={instanceName} />
              )}
            </div>

            <div className="flex items-center justify-between pt-3 border-t">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setWizardStep((s) => Math.max(0, s - 1))}
                disabled={wizardStep === 0}
              >
                <ChevronLeft className="h-4 w-4 mr-1" /> Back
              </Button>
              <span className="text-xs text-muted-foreground">
                Step {wizardStep + 1} of {WIZARD_STEPS.length}
              </span>
              {wizardStep < WIZARD_STEPS.length - 1 ? (
                <Button
                  size="sm"
                  onClick={() => setWizardStep((s) => s + 1)}
                  disabled={!canAdvance(wizardStep)}
                >
                  Next <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              ) : (
                <Button
                  size="sm"
                  onClick={() => createMutation.mutate(form)}
                  disabled={createMutation.isPending || !form.instance_id}
                >
                  {createMutation.isPending ? 'Creating...' : (
                    <>
                      <Rocket className="h-4 w-4 mr-1" /> Create & Start Backtesting
                    </>
                  )}
                </Button>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </PageHeader>

      {strategies.length === 0 ? (
        <Card className="text-center py-12">
          <CardContent>
            <Target className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
            <p className="text-lg text-muted-foreground">No strategies yet</p>
            <p className="text-sm text-muted-foreground mb-4">Create your first strategy to run backtests and deploy agents.</p>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4 mr-2" /> Create Strategy
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {/* STR1: Sort Options */}
          <div className="flex items-center gap-3">
            <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Sort by:</span>
            <Select value={sortBy} onValueChange={setSortBy}>
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="pnl">P&L</SelectItem>
                <SelectItem value="sharpe">Sharpe Ratio</SelectItem>
                <SelectItem value="win_rate">Win Rate</SelectItem>
                <SelectItem value="max_dd">Max Drawdown</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
            <div className="lg:col-span-4 xl:col-span-3">
              <AgentLeaderboardTable agents={leaderData} />
            </div>
            <div className="lg:col-span-8 xl:col-span-9">
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                {sortedStrategies.map((s) => (
                  <StrategyCard
                    key={s.id}
                    strategy={s}
                    onClick={() => navigate(`/agents/${s.agent_id || s.id}`)}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* STR3: Parameter Optimization Placeholder */}
          <Card className="border-dashed border-2">
            <CardContent className="py-8 text-center space-y-3">
              <Beaker className="h-10 w-10 mx-auto text-muted-foreground/40" />
              <h3 className="text-lg font-semibold text-muted-foreground">Parameter Optimization — Coming Soon</h3>
              <p className="text-sm text-muted-foreground max-w-lg mx-auto">
                Automated parameter tuning using grid search, Bayesian optimization, and genetic algorithms.
                Optimize entry/exit thresholds, position sizing, and risk parameters across your strategy catalog
                to maximize Sharpe ratio and minimize drawdown.
              </p>
              <Badge variant="outline" className="text-xs">Planned for v2.0</Badge>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
