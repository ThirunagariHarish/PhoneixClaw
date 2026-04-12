import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { DndContext, DragEndEvent, DragOverlay, closestCenter, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog'
import { AiAssistPopover } from '@/components/AiAssistPopover'
import { Badge } from '@/components/ui/badge'
import {
  Plus, User, GripVertical, ListTodo, ChevronDown, ChevronUp,
  Inbox, Clock, Eye, CheckCircle2, Flag, Trash2, Search, Filter,
  Calendar, AlertTriangle,
} from 'lucide-react'

const COLUMNS = ['BACKLOG', 'IN_PROGRESS', 'UNDER_REVIEW', 'COMPLETED'] as const
type ColumnStatus = (typeof COLUMNS)[number]

const COLUMN_CONFIG: Record<ColumnStatus, { label: string; icon: typeof Inbox; color: string; accent: string; bg: string }> = {
  BACKLOG:      { label: 'Backlog',       icon: Inbox,        color: 'text-zinc-500',    accent: 'bg-zinc-500',    bg: 'bg-zinc-500/10' },
  IN_PROGRESS:  { label: 'In Progress',   icon: Clock,        color: 'text-blue-500',    accent: 'bg-blue-500',    bg: 'bg-blue-500/10' },
  UNDER_REVIEW: { label: 'Under Review',  icon: Eye,          color: 'text-amber-500',   accent: 'bg-amber-500',   bg: 'bg-amber-500/10' },
  COMPLETED:    { label: 'Completed',      icon: CheckCircle2, color: 'text-emerald-500', accent: 'bg-emerald-500', bg: 'bg-emerald-500/10' },
}

type Priority = 'low' | 'medium' | 'high' | 'critical'

const PRIORITY_CONFIG: Record<Priority, { label: string; color: string; dot: string; stripColor: string; badgeBg: string }> = {
  low:      { label: 'Low',      color: 'text-slate-500',  dot: 'bg-slate-400',  stripColor: 'bg-slate-400',  badgeBg: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300' },
  medium:   { label: 'Medium',   color: 'text-blue-500',   dot: 'bg-blue-500',   stripColor: 'bg-blue-500',   badgeBg: 'bg-blue-50 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300' },
  high:     { label: 'High',     color: 'text-orange-500', dot: 'bg-orange-500',  stripColor: 'bg-orange-500', badgeBg: 'bg-orange-50 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300' },
  critical: { label: 'Critical', color: 'text-red-500',    dot: 'bg-red-500',    stripColor: 'bg-red-500',    badgeBg: 'bg-red-50 text-red-700 dark:bg-red-900/50 dark:text-red-300' },
}

const AGENT_ROLES = [
  { value: 'day-trader', label: 'Day Trader' },
  { value: 'technical-analyst', label: 'Technical Analyst' },
  { value: 'risk-analyzer', label: 'Risk Analyzer' },
  { value: 'sentiment-analyst', label: 'Sentiment Analyst' },
  { value: 'portfolio-manager', label: 'Portfolio Manager' },
  { value: 'market-researcher', label: 'Market Researcher' },
  { value: 'options-specialist', label: 'Options Specialist' },
  { value: 'quant-developer', label: 'Quant Developer' },
  { value: 'compliance-officer', label: 'Compliance Officer' },
]

const TASK_SKILLS = [
  { id: 'market_data', label: 'Market Data', description: 'Real-time price feeds and OHLCV data' },
  { id: 'signal_parsing', label: 'Signal Parsing', description: 'Parse trade signals from text sources' },
  { id: 'order_execution', label: 'Order Execution', description: 'Place and manage orders via broker API' },
  { id: 'risk_management', label: 'Risk Mgmt', description: 'Position sizing and loss limits' },
  { id: 'portfolio_tracking', label: 'Portfolio', description: 'Track positions and P&L in real time' },
  { id: 'sentiment_analysis', label: 'Sentiment', description: 'NLP-based market sentiment scoring' },
  { id: 'backtesting', label: 'Backtesting', description: 'Historical strategy performance testing' },
  { id: 'alerting', label: 'Alerting', description: 'Push alerts on key events' },
]

const SKILL_COLORS = [
  'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300',
  'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',
  'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  'bg-lime-100 text-lime-700 dark:bg-lime-900/40 dark:text-lime-300',
  'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
]

function skillColor(skillId: string) {
  const idx = TASK_SKILLS.findIndex((s) => s.id === skillId)
  return SKILL_COLORS[idx >= 0 ? idx % SKILL_COLORS.length : 0]
}

interface Task {
  id: string
  title: string
  description?: string
  status: ColumnStatus
  agent_role: string
  priority: Priority
  skills?: string[]
  due_date?: string | null
  created_at: string
}

interface TaskForm {
  title: string
  description: string
  agent_role: string
  priority: Priority
  skills: string[]
  due_date: string
}

const INITIAL_FORM: TaskForm = {
  title: '',
  description: '',
  agent_role: 'day-trader',
  priority: 'medium',
  skills: [],
  due_date: '',
}

// T2: Due date status helper
function getDueDateStatus(dueDate: string | null | undefined): 'overdue' | 'today' | 'upcoming' | null {
  if (!dueDate) return null
  const now = new Date()
  const due = new Date(dueDate)
  if (isNaN(due.getTime())) return null

  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const todayEnd = new Date(todayStart)
  todayEnd.setDate(todayEnd.getDate() + 1)

  if (due < todayStart) return 'overdue'
  if (due < todayEnd) return 'today'
  return 'upcoming'
}

function DueDateBadge({ dueDate }: { dueDate: string | null | undefined }) {
  const status = getDueDateStatus(dueDate)
  if (!status || !dueDate) return null

  const d = new Date(dueDate)
  const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  const styles = {
    overdue: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
    today: 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
    upcoming: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
  }

  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ${styles[status]}`}>
      {status === 'overdue' && <AlertTriangle className="h-2.5 w-2.5" />}
      {status === 'today' && <Clock className="h-2.5 w-2.5" />}
      {status === 'upcoming' && <Calendar className="h-2.5 w-2.5" />}
      {label}
    </span>
  )
}

function PriorityBadge({ priority }: { priority: Priority }) {
  const cfg = PRIORITY_CONFIG[priority] ?? PRIORITY_CONFIG.medium
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${cfg.badgeBg}`}>
      <Flag className={`h-3 w-3 ${cfg.color}`} />
      {cfg.label}
    </span>
  )
}

// T2: Card border highlight for overdue/today
function dueDateBorderClass(dueDate: string | null | undefined): string {
  const status = getDueDateStatus(dueDate)
  if (status === 'overdue') return 'ring-2 ring-red-500/40'
  if (status === 'today') return 'ring-2 ring-amber-500/40'
  return ''
}

function SortableTaskCard({ task, onDelete, onEdit }: { task: Task; onDelete: (id: string) => void; onEdit: (task: Task) => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id,
    data: { task },
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  const skills = task.skills ?? []
  const priCfg = PRIORITY_CONFIG[task.priority] ?? PRIORITY_CONFIG.medium

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`group relative flex rounded-lg border bg-card overflow-hidden transition-all duration-200 hover:shadow-md hover:shadow-black/5 dark:hover:shadow-black/20 hover:-translate-y-0.5 hover:border-primary/30 cursor-pointer ${dueDateBorderClass(task.due_date)}`}
      onClick={() => onEdit(task)}
    >
      {/* Priority color strip */}
      <div className={`w-1 shrink-0 ${priCfg.stripColor}`} />

      <div className="flex-1 p-3 min-w-0">
        {/* Header row */}
        <div className="flex items-start gap-2 mb-1.5">
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-sm leading-snug">{task.title}</p>
          </div>
          <PriorityBadge priority={task.priority} />
        </div>

        {/* Description */}
        {task.description && (
          <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2 mb-2">{task.description}</p>
        )}

        {/* Agent role pill + due date */}
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          <div className="inline-flex items-center gap-1 rounded-full bg-muted/70 px-2 py-0.5">
            <User className="h-3 w-3 text-muted-foreground" />
            <span className="text-[11px] font-medium capitalize">{(task.agent_role ?? '').replace(/-/g, ' ')}</span>
          </div>
          <DueDateBadge dueDate={task.due_date} />
        </div>

        {/* Skills pills */}
        {skills.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {skills.map((s) => (
              <span key={s} className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium ${skillColor(s)}`}>
                {TASK_SKILLS.find((sk) => sk.id === s)?.label ?? s}
              </span>
            ))}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-1.5 border-t border-border/50">
          <span className="text-[10px] text-muted-foreground">
            {task.created_at ? (() => { const d = new Date(task.created_at); return isNaN(d.getTime()) ? 'N/A' : d.toLocaleDateString() })() : 'N/A'}
          </span>
          <div className="flex items-center gap-1">
            <button
              className="p-0.5 rounded text-destructive/60 hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => { e.stopPropagation(); onDelete(task.id) }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
            <button
              {...attributes}
              {...listeners}
              className="p-0.5 cursor-grab text-muted-foreground/50 hover:text-muted-foreground sm:opacity-0 sm:group-hover:opacity-100 transition-opacity touch-none"
              aria-label="Drag to reorder"
              onClick={(e) => e.stopPropagation()}
            >
              <GripVertical className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function TaskOverlayCard({ task }: { task: Task }) {
  const priCfg = PRIORITY_CONFIG[task.priority] ?? PRIORITY_CONFIG.medium
  return (
    <div className="flex rounded-lg border bg-card shadow-xl ring-2 ring-primary/30 overflow-hidden">
      <div className={`w-1 shrink-0 ${priCfg.stripColor}`} />
      <div className="p-3 min-w-0">
        <div className="flex items-start justify-between gap-2 mb-1">
          <span className="font-semibold text-sm">{task.title}</span>
          <PriorityBadge priority={task.priority} />
        </div>
        <div className="flex items-center gap-1.5">
          <div className="inline-flex items-center gap-1 rounded-full bg-muted/70 px-2 py-0.5">
            <User className="h-3 w-3 text-muted-foreground" />
            <span className="text-[11px] font-medium capitalize">{(task.agent_role ?? '').replace(/-/g, ' ')}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function KanbanColumn({
  status,
  tasks,
  onDelete,
  onEdit,
}: {
  status: ColumnStatus
  tasks: Task[]
  onDelete: (id: string) => void
  onEdit: (task: Task) => void
}) {
  const cfg = COLUMN_CONFIG[status]
  const Icon = cfg.icon
  const taskIds = tasks.map((t) => t.id)

  return (
    <div className="flex flex-col min-h-[320px]">
      {/* Column header */}
      <div className="flex items-center gap-2.5 mb-3 px-1">
        <div className={`flex h-7 w-7 items-center justify-center rounded-lg ${cfg.bg}`}>
          <Icon className={`h-4 w-4 ${cfg.color}`} />
        </div>
        <span className="font-semibold text-sm">{cfg.label}</span>
        <span className={`flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[11px] font-bold text-white ${cfg.accent}`}>
          {tasks.length}
        </span>
      </div>

      {/* Column body */}
      <div className={`flex-1 rounded-xl border border-border/60 bg-muted/20 p-2 transition-colors`}>
        <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
          <div className="space-y-2 min-h-[60px]">
            {tasks.length === 0 && (
              <div className="flex flex-col items-center justify-center py-10 border-2 border-dashed border-border/50 rounded-lg">
                <Icon className="h-6 w-6 text-muted-foreground/30 mb-2" />
                <p className="text-xs text-muted-foreground/50 font-medium">No {cfg.label.toLowerCase()} tasks</p>
                <p className="text-[10px] text-muted-foreground/30 mt-0.5">Drag tasks here</p>
              </div>
            )}
            {tasks.map((task) => (
              <SortableTaskCard key={task.id} task={task} onDelete={onDelete} onEdit={onEdit} />
            ))}
          </div>
        </SortableContext>
      </div>
    </div>
  )
}

function PrioritySummaryBar({ tasks }: { tasks: Task[] }) {
  const counts = (Object.keys(PRIORITY_CONFIG) as Priority[]).map((p) => ({
    priority: p,
    count: tasks.filter((t) => t.priority === p).length,
    ...PRIORITY_CONFIG[p],
  }))

  return (
    <div className="flex items-center gap-4 rounded-lg border bg-card px-4 py-2.5">
      <span className="text-xs font-medium text-muted-foreground">Priority:</span>
      {counts.map((c) => (
        <div key={c.priority} className="flex items-center gap-1.5">
          <span className={`h-2.5 w-2.5 rounded-full ${c.dot}`} />
          <span className="text-xs font-medium">{c.label}</span>
          <span className="text-xs text-muted-foreground font-mono">{c.count}</span>
        </div>
      ))}
      <div className="flex-1" />
      <span className="text-xs text-muted-foreground">
        {tasks.length} total task{tasks.length !== 1 ? 's' : ''}
      </span>
    </div>
  )
}

// T3: Search and Filter Bar
function SearchFilterBar({
  searchText,
  onSearchChange,
  priorityFilter,
  onPriorityChange,
  roleFilter,
  onRoleChange,
}: {
  searchText: string
  onSearchChange: (v: string) => void
  priorityFilter: string
  onPriorityChange: (v: string) => void
  roleFilter: string
  onRoleChange: (v: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-2.5">
      <div className="flex items-center gap-2 flex-1 min-w-[200px]">
        <Search className="h-4 w-4 text-muted-foreground shrink-0" />
        <Input
          value={searchText}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search tasks..."
          className="h-8 border-0 bg-transparent shadow-none focus-visible:ring-0 px-0"
        />
      </div>
      <div className="flex items-center gap-2">
        <Filter className="h-4 w-4 text-muted-foreground" />
        <Select value={priorityFilter} onValueChange={onPriorityChange}>
          <SelectTrigger className="h-8 w-[130px] text-xs">
            <SelectValue placeholder="All priorities" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All priorities</SelectItem>
            {(Object.keys(PRIORITY_CONFIG) as Priority[]).map((p) => (
              <SelectItem key={p} value={p}>
                <span className="flex items-center gap-2">
                  <span className={`inline-block h-2 w-2 rounded-full ${PRIORITY_CONFIG[p].dot}`} />
                  {PRIORITY_CONFIG[p].label}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={roleFilter} onValueChange={onRoleChange}>
          <SelectTrigger className="h-8 w-[160px] text-xs">
            <SelectValue placeholder="All roles" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All roles</SelectItem>
            {AGENT_ROLES.map((r) => (
              <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

// T1: Task Detail/Edit Dialog
function TaskEditDialog({
  task,
  open,
  onOpenChange,
}: {
  task: Task | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<TaskForm>(INITIAL_FORM)
  const [skillsExpanded, setSkillsExpanded] = useState(false)

  // Sync form when task changes
  const currentTaskId = task?.id
  useState(() => {
    if (task) {
      setForm({
        title: task.title,
        description: task.description ?? '',
        agent_role: task.agent_role ?? 'day-trader',
        priority: task.priority ?? 'medium',
        skills: task.skills ?? [],
        due_date: task.due_date ? task.due_date.split('T')[0] : '',
      })
    }
  })

  // Reset form when a different task is opened
  const [prevTaskId, setPrevTaskId] = useState<string | null>(null)
  if (currentTaskId !== prevTaskId) {
    setPrevTaskId(currentTaskId ?? null)
    if (task) {
      setForm({
        title: task.title,
        description: task.description ?? '',
        agent_role: task.agent_role ?? 'day-trader',
        priority: task.priority ?? 'medium',
        skills: task.skills ?? [],
        due_date: task.due_date ? task.due_date.split('T')[0] : '',
      })
      setSkillsExpanded(false)
    }
  }

  const updateMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      await api.patch(`/api/v2/tasks/${task!.id}`, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      onOpenChange(false)
    },
  })

  function toggleSkill(skillId: string) {
    setForm((prev) => ({
      ...prev,
      skills: prev.skills.includes(skillId)
        ? prev.skills.filter((s) => s !== skillId)
        : [...prev.skills, skillId],
    }))
  }

  function handleSave() {
    if (!form.title.trim() || !task) return
    updateMutation.mutate({
      title: form.title.trim(),
      description: form.description.trim(),
      agent_role: form.agent_role,
      priority: form.priority,
      skills: form.skills,
      due_date: form.due_date || null,
    })
  }

  if (!task) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg w-[calc(100vw-2rem)] sm:w-full max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Edit Task</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 flex-1 overflow-y-auto pr-1">
          <div className="space-y-1.5">
            <Label>Title</Label>
            <Input
              value={form.title}
              onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
              placeholder="Task title"
            />
          </div>

          <div className="space-y-1.5">
            <Label>Description</Label>
            <textarea
              className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={form.description}
              onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="Describe what the agent should do..."
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Agent Role</Label>
              <Select
                value={form.agent_role}
                onValueChange={(v) => setForm((prev) => ({ ...prev, agent_role: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select role" />
                </SelectTrigger>
                <SelectContent>
                  {AGENT_ROLES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label>Priority</Label>
              <Select
                value={form.priority}
                onValueChange={(v) => setForm((prev) => ({ ...prev, priority: v as Priority }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select priority" />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(PRIORITY_CONFIG) as Priority[]).map((p) => (
                    <SelectItem key={p} value={p}>
                      <span className="flex items-center gap-2">
                        <span className={`inline-block h-2 w-2 rounded-full ${PRIORITY_CONFIG[p].dot}`} />
                        {PRIORITY_CONFIG[p].label}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* T2: Due date field */}
          <div className="space-y-1.5">
            <Label>Due Date</Label>
            <Input
              type="date"
              value={form.due_date}
              onChange={(e) => setForm((prev) => ({ ...prev, due_date: e.target.value }))}
            />
          </div>

          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setSkillsExpanded(!skillsExpanded)}
              className="flex items-center gap-2 text-sm font-medium w-full"
            >
              <Label className="cursor-pointer">Skills</Label>
              {form.skills.length > 0 && (
                <Badge variant="secondary" className="text-[10px]">{form.skills.length}</Badge>
              )}
              <div className="flex-1" />
              {skillsExpanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
            </button>
            {skillsExpanded && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {TASK_SKILLS.map((skill) => {
                  const checked = form.skills.includes(skill.id)
                  return (
                    <label
                      key={skill.id}
                      className={`flex items-start gap-3 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                        checked ? 'border-primary bg-primary/5' : 'border-border hover:border-muted-foreground/50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSkill(skill.id)}
                        className="mt-0.5 h-4 w-4 rounded border-border accent-primary"
                      />
                      <div>
                        <p className="text-xs font-medium">{skill.label}</p>
                        <p className="text-[10px] text-muted-foreground leading-tight">{skill.description}</p>
                      </div>
                    </label>
                  )
                })}
              </div>
            )}
            {!skillsExpanded && form.skills.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {form.skills.map((s) => (
                  <Badge key={s} variant="secondary" className="text-[10px]">
                    {TASK_SKILLS.find((sk) => sk.id === s)?.label ?? s}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="pt-4 border-t">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={handleSave}
            disabled={!form.title.trim() || updateMutation.isPending}
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function TasksPage() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [newTask, setNewTask] = useState<TaskForm>(INITIAL_FORM)
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const [skillsExpanded, setSkillsExpanded] = useState(false)

  // T1: Edit dialog state
  const [editTask, setEditTask] = useState<Task | null>(null)
  const [editOpen, setEditOpen] = useState(false)

  // T3: Search and filter state
  const [searchText, setSearchText] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('all')
  const [roleFilter, setRoleFilter] = useState('all')

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const { data: tasks = [] } = useQuery<Task[]>({
    queryKey: ['tasks'],
    queryFn: async () => {
      const res = await api.get('/api/v2/tasks')
      return Array.isArray(res.data) ? res.data : []
    },
  })

  // T3: Filter tasks
  const filteredTasks = useMemo(() => {
    let result = tasks
    if (searchText.trim()) {
      const q = searchText.toLowerCase()
      result = result.filter(
        (t) =>
          t.title.toLowerCase().includes(q) ||
          (t.description ?? '').toLowerCase().includes(q)
      )
    }
    if (priorityFilter !== 'all') {
      result = result.filter((t) => t.priority === priorityFilter)
    }
    if (roleFilter !== 'all') {
      result = result.filter((t) => t.agent_role === roleFilter)
    }
    return result
  }, [tasks, searchText, priorityFilter, roleFilter])

  const moveMutation = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: string }) => {
      await api.patch(`/api/v2/tasks/${id}/move`, { status })
    },
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: ['tasks'] })
      const previous = queryClient.getQueryData<Task[]>(['tasks'])
      queryClient.setQueryData<Task[]>(['tasks'], (old) =>
        old?.map((t) => (t.id === id ? { ...t, status: status as ColumnStatus } : t)),
      )
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['tasks'], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  const createMutation = useMutation({
    mutationFn: async (payload: { title: string; description: string; agent_role: string; status: string; priority: string; skills: string[]; due_date?: string | null }) => {
      const res = await api.post('/api/v2/tasks', payload)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      setNewTask(INITIAL_FORM)
      setSkillsExpanded(false)
      setCreateOpen(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/api/v2/tasks/${id}`)
    },
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['tasks'] })
      const previous = queryClient.getQueryData<Task[]>(['tasks'])
      queryClient.setQueryData<Task[]>(['tasks'], (old) => old?.filter((t) => t.id !== id))
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['tasks'], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  const tasksByColumn = (status: ColumnStatus) => filteredTasks.filter((t) => t.status === status)

  function findColumnForTask(taskId: string): ColumnStatus | undefined {
    const task = tasks.find((t) => t.id === taskId)
    return task?.status as ColumnStatus | undefined
  }

  function handleDragStart(event: DragEndEvent) {
    const task = tasks.find((t) => t.id === event.active.id)
    setActiveTask(task ?? null)
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveTask(null)
    const { active, over } = event
    if (!over) return

    const activeId = String(active.id)
    const overId = String(over.id)

    const sourceColumn = findColumnForTask(activeId)

    let targetColumn: ColumnStatus | undefined
    if (COLUMNS.includes(overId as ColumnStatus)) {
      targetColumn = overId as ColumnStatus
    } else {
      targetColumn = findColumnForTask(overId)
    }

    if (!sourceColumn || !targetColumn || sourceColumn === targetColumn) return

    moveMutation.mutate({ id: activeId, status: targetColumn })
  }

  function toggleSkill(skillId: string) {
    setNewTask((prev) => ({
      ...prev,
      skills: prev.skills.includes(skillId)
        ? prev.skills.filter((s) => s !== skillId)
        : [...prev.skills, skillId],
    }))
  }

  function handleCreate() {
    if (!newTask.title.trim()) return
    createMutation.mutate({
      title: newTask.title.trim(),
      description: newTask.description.trim(),
      agent_role: newTask.agent_role,
      status: 'BACKLOG',
      priority: newTask.priority,
      skills: newTask.skills,
      due_date: newTask.due_date || null,
    })
  }

  function handleEditTask(task: Task) {
    setEditTask(task)
    setEditOpen(true)
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <PageHeader
            icon={ListTodo}
            title="Tasks"
            description="Assign and track tasks across your trading agents"
          />
        </div>
        <Dialog open={createOpen} onOpenChange={(v) => { setCreateOpen(v); if (!v) { setNewTask(INITIAL_FORM); setSkillsExpanded(false) } }}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" /> Create Task
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg w-[calc(100vw-2rem)] sm:w-full max-h-[85vh] flex flex-col">
            <DialogHeader>
              <DialogTitle>Create Task</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 flex-1 overflow-y-auto pr-1">
              <div className="space-y-1.5">
                <Label>Title</Label>
                <Input
                  value={newTask.title}
                  onChange={(e) => setNewTask((prev) => ({ ...prev, title: e.target.value }))}
                  placeholder="e.g. Analyze SPY options flow for unusual activity"
                />
              </div>

              <AiAssistPopover
                label="Description"
                value={newTask.description}
                onChange={(v) => setNewTask((prev) => ({ ...prev, description: v }))}
                placeholder="Describe what the agent should do..."
                multiline
                context={`task for agent role: ${newTask.agent_role}`}
              />

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Agent Role</Label>
                  <Select
                    value={newTask.agent_role}
                    onValueChange={(v) => setNewTask((prev) => ({ ...prev, agent_role: v }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select role" />
                    </SelectTrigger>
                    <SelectContent>
                      {AGENT_ROLES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label>Priority</Label>
                  <Select
                    value={newTask.priority}
                    onValueChange={(v) => setNewTask((prev) => ({ ...prev, priority: v as Priority }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select priority" />
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.keys(PRIORITY_CONFIG) as Priority[]).map((p) => (
                        <SelectItem key={p} value={p}>
                          <span className="flex items-center gap-2">
                            <span className={`inline-block h-2 w-2 rounded-full ${PRIORITY_CONFIG[p].dot}`} />
                            {PRIORITY_CONFIG[p].label}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* T2: Due date in create dialog */}
              <div className="space-y-1.5">
                <Label>Due Date</Label>
                <Input
                  type="date"
                  value={newTask.due_date}
                  onChange={(e) => setNewTask((prev) => ({ ...prev, due_date: e.target.value }))}
                />
              </div>

              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setSkillsExpanded(!skillsExpanded)}
                  className="flex items-center gap-2 text-sm font-medium w-full"
                >
                  <Label className="cursor-pointer">Skills</Label>
                  {newTask.skills.length > 0 && (
                    <Badge variant="secondary" className="text-[10px]">{newTask.skills.length}</Badge>
                  )}
                  <div className="flex-1" />
                  {skillsExpanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
                </button>
                {skillsExpanded && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {TASK_SKILLS.map((skill) => {
                      const checked = newTask.skills.includes(skill.id)
                      return (
                        <label
                          key={skill.id}
                          className={`flex items-start gap-3 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                            checked ? 'border-primary bg-primary/5' : 'border-border hover:border-muted-foreground/50'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleSkill(skill.id)}
                            className="mt-0.5 h-4 w-4 rounded border-border accent-primary"
                          />
                          <div>
                            <p className="text-xs font-medium">{skill.label}</p>
                            <p className="text-[10px] text-muted-foreground leading-tight">{skill.description}</p>
                          </div>
                        </label>
                      )
                    })}
                  </div>
                )}
                {!skillsExpanded && newTask.skills.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {newTask.skills.map((s) => (
                      <Badge key={s} variant="secondary" className="text-[10px]">
                        {TASK_SKILLS.find((sk) => sk.id === s)?.label ?? s}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              <div className="border-t pt-4">
                <Button
                  className="w-full"
                  onClick={handleCreate}
                  disabled={!newTask.title.trim() || createMutation.isPending}
                >
                  {createMutation.isPending ? 'Creating...' : 'Create Task'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <PrioritySummaryBar tasks={tasks} />

      {/* T3: Search and filter bar */}
      <SearchFilterBar
        searchText={searchText}
        onSearchChange={setSearchText}
        priorityFilter={priorityFilter}
        onPriorityChange={setPriorityFilter}
        roleFilter={roleFilter}
        onRoleChange={setRoleFilter}
      />

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {COLUMNS.map((col) => (
            <KanbanColumn
              key={col}
              status={col}
              tasks={tasksByColumn(col)}
              onDelete={(id) => deleteMutation.mutate(id)}
              onEdit={handleEditTask}
            />
          ))}
        </div>
        <DragOverlay dropAnimation={{ duration: 200, easing: 'ease' }}>
          {activeTask ? <TaskOverlayCard task={activeTask} /> : null}
        </DragOverlay>
      </DndContext>

      {/* T1: Task Edit Dialog */}
      <TaskEditDialog
        task={editTask}
        open={editOpen}
        onOpenChange={(open) => {
          setEditOpen(open)
          if (!open) setEditTask(null)
        }}
      />
    </div>
  )
}
