import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
  type DragOverEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
  sortableKeyboardCoordinates,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useDroppable } from '@dnd-kit/core'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2, Plus, Trash2, GripVertical, Calendar } from 'lucide-react'

interface BoardTask {
  id: string
  title: string
  description: string | null
  status: string
  priority: string
  position: number
  created_by: string
  created_by_name: string | null
  assigned_to: string | null
  assigned_to_name: string | null
  labels: string[]
  due_date: string | null
  created_at: string
  updated_at: string
}

const COLUMNS = [
  { id: 'refinement', label: 'Refinement' },
  { id: 'ready', label: 'Ready' },
  { id: 'in_progress', label: 'In Progress' },
  { id: 'completed', label: 'Completed' },
] as const

const PRIORITIES = ['critical', 'high', 'medium', 'low'] as const

const PRIORITY_STYLES: Record<string, string> = {
  critical: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400',
  high: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-400',
  medium: 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-400',
  low: 'border-gray-500/40 bg-gray-500/10 text-gray-700 dark:text-gray-400',
}

const COLUMN_ACCENT: Record<string, string> = {
  refinement: 'border-t-purple-500',
  ready: 'border-t-blue-500',
  in_progress: 'border-t-amber-500',
  completed: 'border-t-emerald-500',
}

const COLUMN_COUNT_BG: Record<string, string> = {
  refinement: 'bg-purple-500/15 text-purple-600',
  ready: 'bg-blue-500/15 text-blue-600',
  in_progress: 'bg-amber-500/15 text-amber-600',
  completed: 'bg-emerald-500/15 text-emerald-600',
}

const LABEL_COLORS = [
  'bg-red-500', 'bg-orange-500', 'bg-amber-500', 'bg-emerald-500',
  'bg-teal-500', 'bg-blue-500', 'bg-indigo-500', 'bg-purple-500', 'bg-pink-500',
]

function labelColor(label: string): string {
  let hash = 0
  for (const ch of label) hash = ((hash << 5) - hash + ch.charCodeAt(0)) | 0
  return LABEL_COLORS[Math.abs(hash) % LABEL_COLORS.length]
}

function userInitials(name: string | null): string {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  return parts.length >= 2
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : name.slice(0, 2).toUpperCase()
}

function SortableTaskCard({
  task,
  onOpen,
  onDelete,
}: {
  task: BoardTask
  onOpen: (t: BoardTask) => void
  onDelete: (t: BoardTask) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id,
    data: { task },
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes}>
      <Card className="group relative cursor-pointer hover:ring-1 hover:ring-primary/20 transition-all" onClick={() => onOpen(task)}>
        <CardContent className="p-3">
          <div className="flex items-start gap-2">
            <button
              {...listeners}
              className="mt-0.5 cursor-grab opacity-0 group-hover:opacity-60 hover:opacity-100 transition-opacity shrink-0 touch-none"
              tabIndex={-1}
              onClick={e => e.stopPropagation()}
            >
              <GripVertical className="h-4 w-4 text-muted-foreground" />
            </button>
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium leading-snug">{task.title}</p>
                <Badge variant="outline" className={`text-[10px] shrink-0 ${PRIORITY_STYLES[task.priority] || ''}`}>
                  {task.priority}
                </Badge>
              </div>

              {/* Labels */}
              {task.labels?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {task.labels.slice(0, 3).map(l => (
                    <span key={l} className={`inline-flex items-center gap-1 text-[10px] text-white px-1.5 py-0.5 rounded ${labelColor(l)}`}>
                      {l}
                    </span>
                  ))}
                  {task.labels.length > 3 && (
                    <span className="text-[10px] text-muted-foreground">+{task.labels.length - 3}</span>
                  )}
                </div>
              )}

              <div className="flex items-center justify-between mt-2">
                <div className="flex items-center gap-2">
                  {task.due_date && (
                    <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                      <Calendar className="h-3 w-3" />
                      {new Date(task.due_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                    </span>
                  )}
                  {!task.due_date && (
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(task.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  {task.assigned_to_name && (
                    <Avatar className="h-5 w-5">
                      <AvatarFallback className="text-[8px] bg-primary/10 text-primary">
                        {userInitials(task.assigned_to_name)}
                      </AvatarFallback>
                    </Avatar>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={e => { e.stopPropagation(); onDelete(task) }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function TaskCardOverlay({ task }: { task: BoardTask }) {
  return (
    <Card className="shadow-xl ring-2 ring-primary/30 w-[280px]">
      <CardContent className="p-3">
        <div className="flex items-start gap-2">
          <GripVertical className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium leading-snug">{task.title}</p>
              <Badge variant="outline" className={`text-[10px] shrink-0 ${PRIORITY_STYLES[task.priority] || ''}`}>
                {task.priority}
              </Badge>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function DroppableColumn({
  columnId,
  label,
  tasks,
  onOpen,
  onDelete,
  onAdd,
}: {
  columnId: string
  label: string
  tasks: BoardTask[]
  onOpen: (t: BoardTask) => void
  onDelete: (t: BoardTask) => void
  onAdd: (status: string) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: columnId })

  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col rounded-xl border border-t-4 ${COLUMN_ACCENT[columnId] || ''} bg-muted/30 min-w-[280px] w-[280px] shrink-0 transition-colors ${isOver ? 'bg-primary/5 ring-1 ring-primary/20' : ''}`}
    >
      <div className="flex items-center justify-between p-3 pb-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">{label}</h3>
          <span className={`text-xs font-medium rounded-full px-2 py-0.5 ${COLUMN_COUNT_BG[columnId] || ''}`}>
            {tasks.length}
          </span>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onAdd(columnId)}>
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-2 min-h-[120px]">
        <SortableContext items={tasks.map(t => t.id)} strategy={verticalListSortingStrategy}>
          {tasks.map(task => (
            <SortableTaskCard key={task.id} task={task} onOpen={onOpen} onDelete={onDelete} />
          ))}
        </SortableContext>
        {tasks.length === 0 && (
          <div className="flex items-center justify-center h-20 text-xs text-muted-foreground">
            Drop tasks here
          </div>
        )}
      </div>
    </div>
  )
}

export default function SprintBoard() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState({ title: '', priority: 'medium', status: 'refinement' })
  const [activeTask, setActiveTask] = useState<BoardTask | null>(null)

  const { data: tasks, isLoading } = useQuery<BoardTask[]>({
    queryKey: ['board-tasks'],
    queryFn: () => axios.get('/api/v1/board').then(r => r.data),
  })

  const grouped = useMemo(() => {
    const map: Record<string, BoardTask[]> = { refinement: [], ready: [], in_progress: [], completed: [] }
    for (const t of tasks ?? []) {
      if (map[t.status]) map[t.status].push(t)
    }
    for (const key of Object.keys(map)) {
      map[key].sort((a, b) => a.position - b.position)
    }
    return map
  }, [tasks])

  const createMut = useMutation({
    mutationFn: (body: object) => axios.post('/api/v1/board', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['board-tasks'] })
      closeDialog()
    },
  })

  const moveMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { status: string; position: number } }) =>
      axios.patch(`/api/v1/board/${id}/move`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['board-tasks'] }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => axios.delete(`/api/v1/board/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['board-tasks'] }),
  })

  function openCreate(status: string) {
    setForm({ title: '', priority: 'medium', status })
    setDialogOpen(true)
  }

  function closeDialog() {
    setDialogOpen(false)
    setForm({ title: '', priority: 'medium', status: 'refinement' })
  }

  function handleSave() {
    if (!form.title.trim()) return
    createMut.mutate({ title: form.title, priority: form.priority, status: form.status })
  }

  function handleOpen(task: BoardTask) {
    navigate(`/board/${task.id}`)
  }

  function handleDelete(task: BoardTask) {
    if (window.confirm(`Delete "${task.title}"?`)) {
      deleteMut.mutate(task.id)
    }
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  function handleDragStart(event: DragStartEvent) {
    const task = (event.active.data.current as { task: BoardTask } | undefined)?.task
    if (task) setActiveTask(task)
  }

  function handleDragOver(event: DragOverEvent) {
    const { active, over } = event
    if (!over || !tasks) return

    const activeId = String(active.id)
    const overId = String(over.id)

    const activeTaskData = tasks.find(t => t.id === activeId)
    if (!activeTaskData) return

    const isOverColumn = COLUMNS.some(c => c.id === overId)
    const overTaskData = tasks.find(t => t.id === overId)

    const targetStatus = isOverColumn ? overId : overTaskData?.status
    if (!targetStatus || targetStatus === activeTaskData.status) return

    qc.setQueryData<BoardTask[]>(['board-tasks'], old => {
      if (!old) return old
      return old.map(t =>
        t.id === activeId
          ? { ...t, status: targetStatus, position: grouped[targetStatus]?.length ?? 0 }
          : t,
      )
    })
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveTask(null)
    const { active, over } = event
    if (!over || !tasks) return

    const activeId = String(active.id)
    const overId = String(over.id)

    const currentTasks = qc.getQueryData<BoardTask[]>(['board-tasks']) ?? tasks
    const activeTaskData = currentTasks.find(t => t.id === activeId)
    if (!activeTaskData) return

    const isOverColumn = COLUMNS.some(c => c.id === overId)
    const targetStatus = isOverColumn ? overId : currentTasks.find(t => t.id === overId)?.status ?? activeTaskData.status

    const columnTasks = currentTasks
      .filter(t => t.status === targetStatus && t.id !== activeId)
      .sort((a, b) => a.position - b.position)

    let newPosition: number
    if (isOverColumn) {
      newPosition = columnTasks.length
    } else {
      const overIndex = columnTasks.findIndex(t => t.id === overId)
      newPosition = overIndex >= 0 ? overIndex : columnTasks.length
    }

    moveMut.mutate({ id: activeId, body: { status: targetStatus, position: newPosition } })
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Manage feature items, improvements, and bugs in a Kanban-style board
        </p>
        <Button onClick={() => openCreate('refinement')} className="gap-1">
          <Plus className="h-4 w-4" /> Add Task
        </Button>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        <div className="flex gap-4 overflow-x-auto pb-4" style={{ minHeight: 'calc(100vh - 220px)' }}>
          {COLUMNS.map(col => (
            <DroppableColumn
              key={col.id}
              columnId={col.id}
              label={col.label}
              tasks={grouped[col.id] || []}
              onOpen={handleOpen}
              onDelete={handleDelete}
              onAdd={openCreate}
            />
          ))}
        </div>
        <DragOverlay>
          {activeTask ? <TaskCardOverlay task={activeTask} /> : null}
        </DragOverlay>
      </DndContext>

      {/* Quick-create dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New Task</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="grid gap-2">
              <Label>Title</Label>
              <Input
                placeholder="Task title"
                value={form.title}
                onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && handleSave()}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>Priority</Label>
                <Select value={form.priority} onValueChange={v => setForm(f => ({ ...f, priority: v }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PRIORITIES.map(p => (
                      <SelectItem key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>Column</Label>
                <Select value={form.status} onValueChange={v => setForm(f => ({ ...f, status: v }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {COLUMNS.map(c => (
                      <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>Cancel</Button>
            <Button onClick={handleSave} disabled={!form.title.trim() || createMut.isPending}>
              {createMut.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
