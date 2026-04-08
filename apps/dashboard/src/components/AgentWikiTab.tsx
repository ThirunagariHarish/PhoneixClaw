/**
 * AgentWikiTab — Knowledge Wiki for a single agent.
 * Shows the agent's accumulated knowledge entries, lets users browse,
 * search, add, edit, and delete entries.
 *
 * Layout (3-pane):
 *   [Category sidebar] | [Entry list] | [Entry detail]
 *
 * Features:
 *   - Category sidebar with counts
 *   - Entry list with confidence badge + bar, created_by badge, relative time
 *   - Edit / Delete / New Entry dialogs
 *   - Phoenix Brain toggle (cross-agent shared entries)
 *   - Export as Markdown or JSON
 *   - Debounced search (300ms)
 */
import { useState, useCallback, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Brain, Edit2, Trash2, Plus, Download,
  Share2, ChevronRight, Search, Clock, Tag, TrendingUp,
  Bot, User,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

/* ─────────────────────────────────────────────
   Types
───────────────────────────────────────────── */

interface WikiEntry {
  id: string
  agent_id: string
  category: string
  subcategory?: string
  title: string
  content: string
  tags: string[]
  symbols: string[]
  confidence_score: number
  trade_ref_ids: string[]
  created_by: 'agent' | 'user'
  is_active: boolean
  is_shared: boolean
  version: number
  created_at: string
  updated_at: string
}

interface WikiListResponse {
  entries: WikiEntry[]
  total: number
  page: number
  per_page: number
}

interface BrainWikiResponse {
  entries: WikiEntry[]
  total: number
}

interface WikiVersion {
  version: number
  title: string
  content: string
  change_reason?: string
  updated_at: string
  updated_by?: string
}

interface AgentWikiTabProps {
  agentId: string
  /** Optional agent metadata — reserved for future contextual rendering */
  agent?: unknown
}

/* ─────────────────────────────────────────────
   Constants
───────────────────────────────────────────── */

const ALL_CATEGORIES = [
  'MARKET_PATTERNS',
  'SYMBOL_PROFILES',
  'STRATEGY_LEARNINGS',
  'MISTAKES',
  'WINNING_CONDITIONS',
  'SECTOR_NOTES',
  'MACRO_CONTEXT',
  'TRADE_OBSERVATION',
] as const

type WikiCategory = (typeof ALL_CATEGORIES)[number]

interface CategoryMeta {
  icon: string
  color: string
  label: string
}

const CATEGORY_META: Record<WikiCategory, CategoryMeta> = {
  MARKET_PATTERNS:    { icon: '📈', color: 'text-blue-400',   label: 'Market Patterns' },
  SYMBOL_PROFILES:    { icon: '🏷️', color: 'text-purple-400', label: 'Symbol Profiles' },
  STRATEGY_LEARNINGS: { icon: '🎯', color: 'text-green-400',  label: 'Strategy' },
  MISTAKES:           { icon: '❌', color: 'text-red-400',    label: 'Mistakes' },
  WINNING_CONDITIONS: { icon: '🏆', color: 'text-yellow-400', label: 'Winning Conditions' },
  SECTOR_NOTES:       { icon: '🏭', color: 'text-orange-400', label: 'Sector Notes' },
  MACRO_CONTEXT:      { icon: '🌐', color: 'text-cyan-400',   label: 'Macro Context' },
  TRADE_OBSERVATION:  { icon: '🔭', color: 'text-gray-400',   label: 'Trade Observations' },
}

/** Fallback for entries with unknown category values */
const getCategoryMeta = (cat: string): CategoryMeta =>
  (CATEGORY_META as Record<string, CategoryMeta>)[cat] ?? {
    icon: '📝',
    color: 'text-muted-foreground',
    label: cat,
  }

/* ─────────────────────────────────────────────
   Helpers
───────────────────────────────────────────── */

const confidenceColor = (score: number): string =>
  score >= 0.7
    ? 'bg-green-500/20 text-green-400 border-green-500/30'
    : score >= 0.4
      ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
      : 'bg-red-500/20 text-red-400 border-red-500/30'

const confidenceBarColor = (score: number): string =>
  score >= 0.7 ? 'bg-green-500' : score >= 0.4 ? 'bg-yellow-500' : 'bg-red-500'

function ConfidenceBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  return (
    <Badge variant="outline" className={cn('text-[10px] font-semibold border', confidenceColor(score))}>
      {pct}% conf
    </Badge>
  )
}

function ConfidenceBar({ score }: { score: number }) {
  return (
    <div className="w-full bg-muted rounded h-1 overflow-hidden">
      <div
        className={cn('h-1 rounded transition-all', confidenceBarColor(score))}
        style={{ width: `${Math.round(score * 100)}%` }}
      />
    </div>
  )
}

function formatRelativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = Math.floor((now - then) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`
  return new Date(dateStr).toLocaleDateString()
}

/* ─────────────────────────────────────────────
   Skeleton loaders
───────────────────────────────────────────── */

function EntrySkeleton() {
  return (
    <div className="space-y-3 p-3">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="rounded-lg border p-3 space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
          <div className="flex gap-1">
            <Skeleton className="h-5 w-12 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  )
}

/* ─────────────────────────────────────────────
   Add / Edit modal
───────────────────────────────────────────── */

interface WikiFormData {
  category: string
  title: string
  content: string
  tags: string
  symbols: string
  confidence_score: number
  is_shared: boolean
  change_reason: string
}

const DEFAULT_FORM: WikiFormData = {
  category: 'TRADE_OBSERVATION',
  title: '',
  content: '',
  tags: '',
  symbols: '',
  confidence_score: 0.5,
  is_shared: false,
  change_reason: '',
}

interface WikiEntryModalProps {
  open: boolean
  onClose: () => void
  agentId: string
  existing?: WikiEntry | null
}

function WikiEntryModal({ open, onClose, agentId, existing }: WikiEntryModalProps) {
  const queryClient = useQueryClient()
  const isEdit = !!existing

  const [form, setForm] = useState<WikiFormData>(() =>
    existing
      ? {
          category: existing.category,
          title: existing.title,
          content: existing.content,
          tags: existing.tags.join(', '),
          symbols: existing.symbols.join(', '),
          confidence_score: existing.confidence_score,
          is_shared: existing.is_shared,
          change_reason: '',
        }
      : DEFAULT_FORM,
  )

  const createMut = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post(`/api/v2/agents/${agentId}/wiki`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wiki', agentId] })
      toast.success('Wiki entry created')
      onClose()
    },
    onError: () => toast.error('Failed to create wiki entry'),
  })

  const updateMut = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.patch(`/api/v2/agents/${agentId}/wiki/${existing?.id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wiki', agentId] })
      queryClient.invalidateQueries({ queryKey: ['wiki-entry', agentId, existing?.id] })
      toast.success('Wiki entry updated')
      onClose()
    },
    onError: () => toast.error('Failed to update wiki entry'),
  })

  const handleSubmit = () => {
    if (!form.title.trim() || !form.content.trim()) {
      toast.error('Title and content are required')
      return
    }
    const payload: Record<string, unknown> = {
      category: form.category,
      title: form.title.trim(),
      content: form.content.trim(),
      tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
      symbols: form.symbols.split(',').map((s) => s.trim()).filter(Boolean),
      confidence_score: form.confidence_score,
      is_shared: form.is_shared,
    }
    if (isEdit && form.change_reason.trim()) {
      payload.change_reason = form.change_reason.trim()
    }
    if (isEdit) {
      updateMut.mutate(payload)
    } else {
      createMut.mutate(payload)
    }
  }

  const isPending = createMut.isPending || updateMut.isPending

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Wiki Entry' : 'Add Wiki Entry'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Category</Label>
              <Select
                value={form.category}
                onValueChange={(v) => setForm((f) => ({ ...f, category: v }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ALL_CATEGORIES.map((cat) => (
                    <SelectItem key={cat} value={cat}>
                      {getCategoryMeta(cat).icon} {getCategoryMeta(cat).label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Confidence Score — {Math.round(form.confidence_score * 100)}%</Label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={form.confidence_score}
                onChange={(e) =>
                  setForm((f) => ({ ...f, confidence_score: parseFloat(e.target.value) }))
                }
                className="w-full accent-primary"
              />
              <ConfidenceBar score={form.confidence_score} />
            </div>
          </div>
          <div className="space-y-1">
            <Label>Title</Label>
            <Input
              placeholder="Short descriptive title..."
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            />
          </div>
          <div className="space-y-1">
            <Label>Content</Label>
            <Textarea
              placeholder="Full knowledge content, observations, analysis..."
              value={form.content}
              onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
              className="min-h-[160px] font-mono text-sm"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Tags (comma-separated)</Label>
              <Input
                placeholder="bearish, reversal, resistance"
                value={form.tags}
                onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label>Symbols (comma-separated)</Label>
              <Input
                placeholder="AAPL, SPY"
                value={form.symbols}
                onChange={(e) => setForm((f) => ({ ...f, symbols: e.target.value }))}
              />
            </div>
          </div>
          {isEdit && (
            <div className="space-y-1">
              <Label>Change Reason (optional)</Label>
              <Input
                placeholder="Why are you editing this entry?"
                value={form.change_reason}
                onChange={(e) => setForm((f) => ({ ...f, change_reason: e.target.value }))}
              />
            </div>
          )}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is-shared"
              checked={form.is_shared}
              onChange={(e) => setForm((f) => ({ ...f, is_shared: e.target.checked }))}
              className="h-4 w-4"
            />
            <Label htmlFor="is-shared" className="cursor-pointer">
              Share with Phoenix Brain (visible to all agents)
            </Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isPending}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isPending}>
            {isPending ? 'Saving...' : isEdit ? 'Update Entry' : 'Create Entry'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ─────────────────────────────────────────────
   Entry detail panel
───────────────────────────────────────────── */

interface EntryDetailProps {
  entry: WikiEntry
  agentId: string
  onEdit: (entry: WikiEntry) => void
  onDelete: (entryId: string) => void
  isDeleting: boolean
}

function EntryDetail({ entry, agentId, onEdit, onDelete, isDeleting }: EntryDetailProps) {
  const [showVersions, setShowVersions] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const { data: versions = [] } = useQuery<WikiVersion[]>({
    queryKey: ['wiki-versions', agentId, entry.id],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}/wiki/${entry.id}/versions`)).data,
    enabled: showVersions,
  })

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b space-y-2">
        <div className="flex items-start gap-2">
          <h3 className="font-semibold text-sm flex-1 leading-snug">{entry.title}</h3>
          <div className="flex gap-1 shrink-0">
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onEdit(entry)}>
              <Edit2 className="h-3.5 w-3.5" />
            </Button>
            {confirmDelete ? (
              <div className="flex gap-1">
                <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={() => onDelete(entry.id)} disabled={isDeleting}>
                  {isDeleting ? '...' : 'Confirm'}
                </Button>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setConfirmDelete(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive hover:text-destructive" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 items-center">
          <span className={cn('text-[10px] font-medium', getCategoryMeta(entry.category).color)}>
            {getCategoryMeta(entry.category).icon} {getCategoryMeta(entry.category).label}
          </span>
          <ConfidenceBadge score={entry.confidence_score} />
          {entry.is_shared && (
            <Badge variant="outline" className="text-[10px] border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400">
              <Share2 className="h-2.5 w-2.5 mr-1" />Shared
            </Badge>
          )}
          <Badge variant="outline" className="text-[10px]">v{entry.version}</Badge>
          <Badge
            variant="outline"
            className={cn('text-[10px] gap-0.5', entry.created_by === 'user' ? 'border-violet-500/40 bg-violet-500/10 text-violet-400' : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400')}
          >
            {entry.created_by === 'user' ? <User className="h-2.5 w-2.5" /> : <Bot className="h-2.5 w-2.5" />}
            {entry.created_by === 'user' ? 'User' : 'Agent'}
          </Badge>
        </div>
        <ConfidenceBar score={entry.confidence_score} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <p className="text-sm whitespace-pre-wrap leading-relaxed">{entry.content}</p>

        {entry.symbols.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
              <TrendingUp className="h-3 w-3" />Symbols
            </p>
            <div className="flex flex-wrap gap-1">
              {entry.symbols.map((s) => (
                <Badge key={s} variant="outline" className="text-xs font-mono">{s}</Badge>
              ))}
            </div>
          </div>
        )}

        {entry.tags.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
              <Tag className="h-3 w-3" />Tags
            </p>
            <div className="flex flex-wrap gap-1">
              {entry.tags.map((t) => (
                <Badge key={t} variant="secondary" className="text-[10px]">#{t}</Badge>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
            <Clock className="h-3 w-3" />Metadata
          </p>
          <div className="text-xs text-muted-foreground space-y-0.5">
            <p>Created by: <span className="text-foreground">{entry.created_by === 'user' ? '👤 User' : '🤖 Agent'}</span></p>
            <p>Created: <span className="text-foreground">{new Date(entry.created_at).toLocaleString()} ({formatRelativeTime(entry.created_at)})</span></p>
            <p>Updated: <span className="text-foreground">{new Date(entry.updated_at).toLocaleString()} ({formatRelativeTime(entry.updated_at)})</span></p>
          </div>
        </div>

        {/* Version history */}
        <div>
          <button
            className="text-[10px] text-muted-foreground underline hover:text-foreground"
            onClick={() => setShowVersions((v) => !v)}
          >
            {showVersions ? 'Hide version history' : `Show version history (v${entry.version})`}
          </button>
          {showVersions && versions.length > 0 && (
            <div className="mt-2 space-y-2">
              {versions.map((v) => (
                <div key={v.version} className="rounded border p-2 text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">v{v.version}</span>
                    <span className="text-muted-foreground">{formatRelativeTime(v.updated_at)}</span>
                  </div>
                  {v.change_reason && <p className="text-muted-foreground italic">{v.change_reason}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Entry card (list item)
───────────────────────────────────────────── */

interface EntryCardProps {
  entry: WikiEntry
  selected: boolean
  onClick: () => void
  isBrain?: boolean
}

function EntryCard({ entry, selected, onClick, isBrain = false }: EntryCardProps) {
  return (
    <button
      className={cn(
        'w-full text-left rounded-lg border p-3 space-y-1.5 transition-colors hover:bg-accent/50',
        selected && 'border-primary bg-accent/30',
      )}
      onClick={onClick}
    >
      <div className="flex items-start gap-2">
        <span className="text-base shrink-0 mt-0.5">{getCategoryMeta(entry.category).icon}</span>
        <p className="text-sm font-medium leading-snug flex-1 line-clamp-2">{entry.title}</p>
        {selected && <ChevronRight className="h-4 w-4 text-primary shrink-0 mt-0.5" />}
      </div>
      {entry.content && (
        <p className="text-[11px] text-muted-foreground line-clamp-2 pl-6">
          {entry.content.slice(0, 100)}{entry.content.length > 100 ? '…' : ''}
        </p>
      )}
      <ConfidenceBar score={entry.confidence_score} />
      <div className="flex flex-wrap gap-1 items-center">
        <ConfidenceBadge score={entry.confidence_score} />
        {isBrain && (
          <Badge variant="outline" className="text-[10px] border-violet-500/40 bg-violet-500/10 text-violet-400 gap-0.5">
            <Brain className="h-2.5 w-2.5" />Brain
          </Badge>
        )}
        {entry.is_shared && !isBrain && (
          <Badge variant="outline" className="text-[10px] border-sky-500/40 bg-sky-500/10 text-sky-600">
            Shared
          </Badge>
        )}
        {entry.created_by === 'user' ? (
          <Badge variant="outline" className="text-[10px] border-violet-500/40 bg-violet-500/10 text-violet-400 gap-0.5">
            <User className="h-2.5 w-2.5" />User
          </Badge>
        ) : (
          <Badge variant="outline" className="text-[10px] border-emerald-500/40 bg-emerald-500/10 text-emerald-400 gap-0.5">
            <Bot className="h-2.5 w-2.5" />Agent
          </Badge>
        )}
      </div>
      {entry.tags.slice(0, 3).length > 0 && (
        <div className="flex flex-wrap gap-0.5">
          {entry.tags.slice(0, 3).map((t) => (
            <span key={t} className="text-[10px] text-muted-foreground">#{t}</span>
          ))}
          {entry.tags.length > 3 && (
            <span className="text-[10px] text-muted-foreground">+{entry.tags.length - 3}</span>
          )}
        </div>
      )}
      {entry.symbols.length > 0 && (
        <div className="flex gap-0.5">
          {entry.symbols.slice(0, 3).map((s) => (
            <Badge key={s} variant="outline" className="text-[10px] font-mono">{s}</Badge>
          ))}
        </div>
      )}
      <p className="text-[10px] text-muted-foreground">{formatRelativeTime(entry.updated_at)}</p>
    </button>
  )
}

/* ─────────────────────────────────────────────
   Main component
───────────────────────────────────────────── */

export function AgentWikiTab({ agentId }: AgentWikiTabProps) {
  const queryClient = useQueryClient()
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedEntry, setSelectedEntry] = useState<WikiEntry | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page] = useState(1)
  const [showModal, setShowModal] = useState(false)
  const [editEntry, setEditEntry] = useState<WikiEntry | null>(null)
  const [brainMode, setBrainMode] = useState(false)

  // Debounce search
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value)
    const timer = setTimeout(() => setDebouncedSearch(value), 300)
    return () => clearTimeout(timer)
  }, [])

  // Build query params for agent wiki
  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = { page, per_page: 20 }
    if (selectedCategory) params.category = selectedCategory
    if (debouncedSearch) params.search = debouncedSearch
    return params
  }, [selectedCategory, debouncedSearch, page])

  // Agent-scoped wiki entries
  const { data: agentData, isLoading: agentLoading } = useQuery<WikiListResponse>({
    queryKey: ['wiki', agentId, selectedCategory, debouncedSearch, page],
    queryFn: async () => {
      const resp = await api.get(`/api/v2/agents/${agentId}/wiki`, { params: queryParams })
      return resp.data as WikiListResponse
    },
    enabled: !brainMode,
  })

  // Brain (cross-agent shared) wiki entries
  const brainParams = useMemo(() => {
    const params: Record<string, string> = {}
    if (selectedCategory) params.category = selectedCategory
    if (debouncedSearch) params.search = debouncedSearch
    return params
  }, [selectedCategory, debouncedSearch])

  const { data: brainData, isLoading: brainLoading } = useQuery<BrainWikiResponse>({
    queryKey: ['brain-wiki', selectedCategory, debouncedSearch],
    queryFn: async () => {
      const resp = await api.get('/api/v2/brain/wiki', { params: brainParams })
      return resp.data as BrainWikiResponse
    },
    enabled: brainMode,
  })

  const isLoading = brainMode ? brainLoading : agentLoading
  const entries: WikiEntry[] = brainMode ? (brainData?.entries ?? []) : (agentData?.entries ?? [])
  const total = brainMode ? (brainData?.total ?? 0) : (agentData?.total ?? 0)

  // Category counts from the current visible list
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    entries.forEach((e) => {
      counts[e.category] = (counts[e.category] ?? 0) + 1
    })
    return counts
  }, [entries])

  const deleteMut = useMutation({
    mutationFn: (entryId: string) => api.delete(`/api/v2/agents/${agentId}/wiki/${entryId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wiki', agentId] })
      setSelectedEntry(null)
      toast.success('Entry deleted')
    },
    onError: () => toast.error('Failed to delete entry'),
  })

  const handleExport = (format: 'json' | 'markdown') => {
    const url = `${import.meta.env.VITE_API_URL ?? ''}/api/v2/agents/${agentId}/wiki/export?format=${format}`
    const a = document.createElement('a')
    a.href = url
    a.download = `agent-wiki-${agentId}.${format === 'json' ? 'json' : 'md'}`
    a.click()
  }

  const handleEdit = (entry: WikiEntry) => {
    setEditEntry(entry)
    setShowModal(true)
  }

  const handleModalClose = () => {
    setShowModal(false)
    setEditEntry(null)
  }

  return (
    <div className="space-y-3">
      {/* Top toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search wiki entries..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-9 h-8 text-sm"
          />
        </div>

        {/* Phoenix Brain toggle */}
        <button
          onClick={() => { setBrainMode((b) => !b); setSelectedEntry(null) }}
          className={cn(
            'flex items-center gap-1.5 h-8 px-3 rounded-md text-xs font-medium border transition-colors',
            brainMode
              ? 'bg-violet-500/20 text-violet-400 border-violet-500/40 hover:bg-violet-500/30'
              : 'bg-transparent text-muted-foreground border-input hover:bg-accent',
          )}
        >
          <Brain className="h-3.5 w-3.5" />
          {brainMode ? '🧠 Brain ON' : 'Phoenix Brain'}
        </button>

        {!brainMode && (
          <Button size="sm" className="h-8 gap-1" onClick={() => { setEditEntry(null); setShowModal(true) }}>
            <Plus className="h-3.5 w-3.5" />New Entry
          </Button>
        )}

        {/* Export dropdown */}
        <div className="relative group">
          <Button size="sm" variant="outline" className="h-8 gap-1">
            <Download className="h-3.5 w-3.5" />Export
          </Button>
          <div className="absolute right-0 top-full mt-1 z-10 hidden group-hover:block bg-popover border rounded shadow-md min-w-36">
            <button
              className="w-full text-left px-3 py-2 text-sm hover:bg-accent"
              onClick={() => handleExport('markdown')}
            >
              Export Markdown (.md)
            </button>
            <button
              className="w-full text-left px-3 py-2 text-sm hover:bg-accent"
              onClick={() => handleExport('json')}
            >
              Export JSON (.json)
            </button>
          </div>
        </div>
      </div>

      {/* Brain mode info banner */}
      {brainMode && (
        <div className="flex items-center gap-2 rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-xs text-violet-400">
          <Brain className="h-3.5 w-3.5 shrink-0" />
          <span>Showing <strong>Phoenix Brain</strong> — shared knowledge entries visible to all agents. Read-only.</span>
        </div>
      )}

      {/* 3-pane layout */}
      <div className="grid grid-cols-[160px_1fr_2fr] gap-3 min-h-[600px]">
        {/* Category sidebar */}
        <Card className="overflow-hidden">
          <CardHeader className="py-2 px-3 border-b">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Categories</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <button
              className={cn(
                'w-full text-left px-3 py-2 text-sm flex items-center justify-between hover:bg-accent/50 transition-colors',
                !selectedCategory && 'bg-accent/30 font-medium',
              )}
              onClick={() => setSelectedCategory(null)}
            >
              <span>All</span>
              <Badge variant="secondary" className="text-[10px]">{total}</Badge>
            </button>
            {ALL_CATEGORIES.map((cat) => {
              const meta = getCategoryMeta(cat)
              return (
                <button
                  key={cat}
                  className={cn(
                    'w-full text-left px-3 py-2 text-xs flex items-center gap-1.5 hover:bg-accent/50 transition-colors',
                    selectedCategory === cat && 'bg-accent/30 font-medium',
                  )}
                  onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
                >
                  <span>{meta.icon}</span>
                  <span className={cn('truncate flex-1', meta.color)}>{meta.label}</span>
                  {categoryCounts[cat] != null && (
                    <Badge variant="secondary" className="text-[10px] shrink-0">{categoryCounts[cat]}</Badge>
                  )}
                </button>
              )
            })}
          </CardContent>
        </Card>

        {/* Entry list */}
        <Card className="overflow-hidden">
          <CardHeader className="py-2 px-3 border-b">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
              {brainMode && <Brain className="h-3 w-3 text-violet-400" />}
              Entries {total > 0 && <span className="normal-case font-normal">({total})</span>}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 overflow-y-auto max-h-[560px]">
            {isLoading ? (
              <EntrySkeleton />
            ) : entries.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 py-16 px-4 text-center">
                <Brain className="h-10 w-10 text-muted-foreground/30" />
                <p className="text-sm text-muted-foreground font-medium">No wiki entries yet.</p>
                <p className="text-xs text-muted-foreground/70">
                  {brainMode
                    ? 'No shared Brain entries found. Entries shared by agents appear here.'
                    : 'Your agent will start building knowledge after its first live trades.'}
                </p>
              </div>
            ) : (
              <div className="p-2 space-y-1.5">
                {entries.map((entry) => (
                  <EntryCard
                    key={entry.id}
                    entry={entry}
                    selected={selectedEntry?.id === entry.id}
                    onClick={() => setSelectedEntry(entry)}
                    isBrain={brainMode}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Entry detail panel */}
        <Card className="overflow-hidden">
          {selectedEntry ? (
            <EntryDetail
              entry={selectedEntry}
              agentId={agentId}
              onEdit={handleEdit}
              onDelete={(id) => deleteMut.mutate(id)}
              isDeleting={deleteMut.isPending}
            />
          ) : (
            <CardContent className="flex flex-col items-center justify-center gap-3 h-full min-h-[400px] text-center">
              <Brain className="h-12 w-12 text-muted-foreground/20" />
              <p className="text-sm text-muted-foreground">Select an entry to view details</p>
              {!brainMode && entries.length === 0 && !isLoading && (
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-2 gap-1"
                  onClick={() => setShowModal(true)}
                >
                  <Plus className="h-3.5 w-3.5" />Add First Entry
                </Button>
              )}
            </CardContent>
          )}
        </Card>
      </div>

      {/* Add / Edit modal — only available in agent mode */}
      {!brainMode && (
        <WikiEntryModal
          open={showModal}
          onClose={handleModalClose}
          agentId={agentId}
          existing={editEntry}
        />
      )}
    </div>
  )
}
