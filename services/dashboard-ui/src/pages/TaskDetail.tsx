import { useState, useCallback, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import RichTextEditor from '@/components/RichTextEditor'
import {
  ArrowLeft,
  Trash2,
  Loader2,
  Calendar,
  User,
  Tag,
  Flag,
  KanbanSquare,
  X,
  Plus,
} from 'lucide-react'

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

interface UserBrief {
  id: string
  name: string | null
  email: string
}

const STATUSES = [
  { value: 'refinement', label: 'Refinement', color: 'bg-purple-500' },
  { value: 'ready', label: 'Ready', color: 'bg-blue-500' },
  { value: 'in_progress', label: 'In Progress', color: 'bg-amber-500' },
  { value: 'completed', label: 'Completed', color: 'bg-emerald-500' },
]

const PRIORITIES = [
  { value: 'critical', label: 'Critical', color: 'text-red-600 bg-red-500/10 border-red-500/30' },
  { value: 'high', label: 'High', color: 'text-orange-600 bg-orange-500/10 border-orange-500/30' },
  { value: 'medium', label: 'Medium', color: 'text-blue-600 bg-blue-500/10 border-blue-500/30' },
  { value: 'low', label: 'Low', color: 'text-gray-600 bg-gray-500/10 border-gray-500/30' },
]

const LABEL_COLORS = [
  'bg-red-500', 'bg-orange-500', 'bg-amber-500', 'bg-emerald-500',
  'bg-teal-500', 'bg-blue-500', 'bg-indigo-500', 'bg-purple-500', 'bg-pink-500',
]

function labelColor(label: string): string {
  let hash = 0
  for (const ch of label) hash = ((hash << 5) - hash + ch.charCodeAt(0)) | 0
  return LABEL_COLORS[Math.abs(hash) % LABEL_COLORS.length]
}

function initials(name: string | null, email: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/)
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : name.slice(0, 2).toUpperCase()
  }
  return email.slice(0, 2).toUpperCase()
}

export default function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [labelInputOpen, setLabelInputOpen] = useState(false)
  const [initialLoaded, setInitialLoaded] = useState(false)

  const { data: task, isLoading } = useQuery<BoardTask>({
    queryKey: ['board-task', taskId],
    queryFn: () => axios.get(`/api/v1/board/${taskId}`).then(r => r.data),
    enabled: !!taskId,
  })

  const { data: users } = useQuery<UserBrief[]>({
    queryKey: ['board-users'],
    queryFn: () => axios.get('/api/v1/board/users').then(r => r.data),
  })

  useEffect(() => {
    if (task && !initialLoaded) {
      setTitle(task.title)
      setDescription(task.description || '')
      setInitialLoaded(true)
    }
  }, [task, initialLoaded])

  const updateMut = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      axios.put(`/api/v1/board/${taskId}`, body).then(r => r.data),
    onSuccess: (data: BoardTask) => {
      qc.setQueryData(['board-task', taskId], data)
      qc.invalidateQueries({ queryKey: ['board-tasks'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: () => axios.delete(`/api/v1/board/${taskId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['board-tasks'] })
      navigate('/board')
    },
  })

  const debouncedSave = useCallback(
    (body: Record<string, unknown>) => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      saveTimerRef.current = setTimeout(() => updateMut.mutate(body), 800)
    },
    [updateMut],
  )

  const handleTitleBlur = useCallback(() => {
    if (task && title.trim() && title !== task.title) {
      updateMut.mutate({ title: title.trim() })
    }
  }, [task, title, updateMut])

  const handleDescriptionChange = useCallback(
    (html: string) => {
      setDescription(html)
      debouncedSave({ description: html })
    },
    [debouncedSave],
  )

  const handleStatusChange = useCallback(
    (status: string) => {
      updateMut.mutate({ status })
    },
    [updateMut],
  )

  const handlePriorityChange = useCallback(
    (priority: string) => {
      updateMut.mutate({ priority })
    },
    [updateMut],
  )

  const handleAssigneeChange = useCallback(
    (userId: string) => {
      updateMut.mutate({ assigned_to: userId === 'unassigned' ? '' : userId })
    },
    [updateMut],
  )

  const handleDueDateChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      updateMut.mutate({ due_date: e.target.value || '' })
    },
    [updateMut],
  )

  const addLabel = useCallback(() => {
    if (!newLabel.trim() || !task) return
    const updated = [...(task.labels || []), newLabel.trim()]
    updateMut.mutate({ labels: updated })
    setNewLabel('')
    setLabelInputOpen(false)
  }, [newLabel, task, updateMut])

  const removeLabel = useCallback(
    (label: string) => {
      if (!task) return
      updateMut.mutate({ labels: task.labels.filter(l => l !== label) })
    },
    [task, updateMut],
  )

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!task) {
    return (
      <div className="text-center py-20">
        <p className="text-muted-foreground">Task not found</p>
        <Button variant="link" onClick={() => navigate('/board')}>Back to Board</Button>
      </div>
    )
  }

  const statusMeta = STATUSES.find(s => s.value === task.status)
  const priorityMeta = PRIORITIES.find(p => p.value === task.priority)
  const assignee = users?.find(u => u.id === task.assigned_to)
  const creator = users?.find(u => u.id === task.created_by)

  return (
    <div className="max-w-5xl mx-auto space-y-0">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate('/board')}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <KanbanSquare className="h-4 w-4" />
          <button onClick={() => navigate('/board')} className="hover:text-foreground transition-colors">
            Sprint Board
          </button>
          <span>/</span>
          <span className="text-foreground font-medium truncate max-w-[200px]">{task.title}</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {updateMut.isPending && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          <Button variant="ghost" size="icon" className="text-destructive" onClick={() => setDeleteOpen(true)}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6">
        {/* Main content */}
        <div className="space-y-4">
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            onBlur={handleTitleBlur}
            onKeyDown={e => e.key === 'Enter' && e.currentTarget.blur()}
            className="w-full text-3xl font-bold bg-transparent border-none outline-none placeholder:text-muted-foreground/50"
            placeholder="Task title"
          />
          <RichTextEditor
            content={description}
            onChange={handleDescriptionChange}
            placeholder="Add a description, paste images, write notes..."
            className="min-h-[400px]"
          />
        </div>

        {/* Sidebar */}
        <div className="space-y-5 lg:border-l lg:pl-6">
          {/* Status */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              <KanbanSquare className="h-3.5 w-3.5" /> Status
            </div>
            <Select value={task.status} onValueChange={handleStatusChange}>
              <SelectTrigger>
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${statusMeta?.color}`} />
                  <SelectValue />
                </div>
              </SelectTrigger>
              <SelectContent>
                {STATUSES.map(s => (
                  <SelectItem key={s.value} value={s.value}>
                    <div className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${s.color}`} />
                      {s.label}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Priority */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              <Flag className="h-3.5 w-3.5" /> Priority
            </div>
            <Select value={task.priority} onValueChange={handlePriorityChange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRIORITIES.map(p => (
                  <SelectItem key={p.value} value={p.value}>
                    <Badge variant="outline" className={`${p.color} text-xs`}>{p.label}</Badge>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Assignee */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              <User className="h-3.5 w-3.5" /> Assignee
            </div>
            <Select value={task.assigned_to || 'unassigned'} onValueChange={handleAssigneeChange}>
              <SelectTrigger>
                <div className="flex items-center gap-2">
                  {assignee ? (
                    <>
                      <Avatar className="h-5 w-5">
                        <AvatarFallback className="text-[9px] bg-primary/10 text-primary">
                          {initials(assignee.name, assignee.email)}
                        </AvatarFallback>
                      </Avatar>
                      <span className="truncate">{assignee.name || assignee.email}</span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">Unassigned</span>
                  )}
                </div>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="unassigned">
                  <span className="text-muted-foreground">Unassigned</span>
                </SelectItem>
                {users?.map(u => (
                  <SelectItem key={u.id} value={u.id}>
                    <div className="flex items-center gap-2">
                      <Avatar className="h-5 w-5">
                        <AvatarFallback className="text-[9px] bg-primary/10 text-primary">
                          {initials(u.name, u.email)}
                        </AvatarFallback>
                      </Avatar>
                      {u.name || u.email}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Due Date */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              <Calendar className="h-3.5 w-3.5" /> Due Date
            </div>
            <Input
              type="date"
              value={task.due_date ? task.due_date.slice(0, 10) : ''}
              onChange={handleDueDateChange}
            />
          </div>

          {/* Labels */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              <Tag className="h-3.5 w-3.5" /> Labels
            </div>
            <div className="flex flex-wrap gap-1.5">
              {task.labels?.map(label => (
                <Badge key={label} variant="secondary" className="gap-1 pr-1">
                  <span className={`h-2 w-2 rounded-full ${labelColor(label)}`} />
                  {label}
                  <button onClick={() => removeLabel(label)} className="ml-0.5 hover:text-destructive">
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
              {labelInputOpen ? (
                <div className="flex items-center gap-1">
                  <Input
                    value={newLabel}
                    onChange={e => setNewLabel(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') addLabel()
                      if (e.key === 'Escape') setLabelInputOpen(false)
                    }}
                    placeholder="Label name"
                    className="h-7 text-xs w-24"
                    autoFocus
                  />
                  <Button size="icon" variant="ghost" className="h-6 w-6" onClick={addLabel}>
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-6 text-xs gap-1"
                  onClick={() => setLabelInputOpen(true)}
                >
                  <Plus className="h-3 w-3" /> Add
                </Button>
              )}
            </div>
          </div>

          {/* Metadata */}
          <div className="space-y-2 pt-4 border-t text-xs text-muted-foreground">
            <div className="flex justify-between">
              <span>Created by</span>
              <span className="text-foreground">{task.created_by_name || (creator ? (creator.name || creator.email) : 'Unknown')}</span>
            </div>
            <div className="flex justify-between">
              <span>Created</span>
              <span>{new Date(task.created_at).toLocaleDateString()}</span>
            </div>
            <div className="flex justify-between">
              <span>Updated</span>
              <span>{new Date(task.updated_at).toLocaleDateString()}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Delete Dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Task</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Are you sure you want to delete "<strong>{task.title}</strong>"? This action cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={() => deleteMut.mutate()}
              disabled={deleteMut.isPending}
            >
              {deleteMut.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
