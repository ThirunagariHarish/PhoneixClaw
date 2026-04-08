/**
 * AgentWikiTab — Knowledge Wiki for a single agent.
 * Shows the agent's accumulated knowledge entries, lets users browse,
 * search, add, edit, and delete entries.
 *
 * Layout (3-pane):
 *   [Category sidebar] | [Entry list] | [Entry detail]
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
  BookOpen, Brain, Edit2, Trash2, Plus, Download,
  Share2, ChevronRight, Search, Clock, Tag, TrendingUp,
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
  created_by: string
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
}

/* ─────────────────────────────────────────────
   Constants
───────────────────────────────────────────── */

const ALL_CATEGORIES = [
  'TRADE_OBSERVATION',
  'MARKET_PATTERN',
  'STRATEGY_LEARNING',
  'RISK_NOTE',
  'SECTOR_INSIGHT',
  'INDICATOR_NOTE',
  'EARNINGS_PLAYBOOK',
  'GENERAL',
] as const

const CATEGORY_LABELS: Record<string, string> = {
  TRADE_OBSERVATION: 'Trade Observations',
  MARKET_PATTERN: 'Market Patterns',
  STRATEGY_LEARNING: 'Strategy Learnings',
  RISK_NOTE: 'Risk Notes',
  SECTOR_INSIGHT: 'Sector Insights',
  INDICATOR_NOTE: 'Indicator Notes',
  EARNINGS_PLAYBOOK: 'Earnings Playbook',
  GENERAL: 'General',
}

/* ─────────────────────────────────────────────
   Confidence badge helper
───────────────────────────────────────────── */

function ConfidenceBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    score > 0.7
      ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/30'
      : score >= 0.4
        ? 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border-amber-500/30'
        : 'bg-rose-500/20 text-rose-700 dark:text-rose-400 border-rose-500/30'
  return (
    <Badge variant="outline" className={cn('text-[10px] font-semibold border', color)}>
      {pct}% conf
    </Badge>
  )
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
                      {CATEGORY_LABELS[cat] ?? cat}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Confidence Score (0–1)</Label>
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={form.confidence_score}
                onChange={(e) =>
                  setForm((f) => ({ ...f, confidence_score: parseFloat(e.target.value) || 0 }))
                }
              />
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
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="secondary" className="text-[10px]">{entry.category}</Badge>
          <ConfidenceBadge score={entry.confidence_score} />
          {entry.is_shared && (
            <Badge variant="outline" className="text-[10px] border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400">
              <Share2 className="h-2.5 w-2.5 mr-1" />Shared
            </Badge>
          )}
          <Badge variant="outline" className="text-[10px]">v{entry.version}</Badge>
        </div>
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
            <p>Created by: <span className="text-foreground">{entry.created_by || 'agent'}</span></p>
            <p>Created: <span className="text-foreground">{new Date(entry.created_at).toLocaleString()}</span></p>
            <p>Updated: <span className="text-foreground">{new Date(entry.updated_at).toLocaleString()}</span></p>
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
                    <span className="text-muted-foreground">{new Date(v.updated_at).toLocaleDateString()}</span>
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

function EntryCard({ entry, selected, onClick }: { entry: WikiEntry; selected: boolean; onClick: () => void }) {
  return (
    <button
      className={cn(
        'w-full text-left rounded-lg border p-3 space-y-1.5 transition-colors hover:bg-accent/50',
        selected && 'border-primary bg-accent/30',
      )}
      onClick={onClick}
    >
      <div className="flex items-start gap-2">
        <p className="text-sm font-medium leading-snug flex-1 line-clamp-2">{entry.title}</p>
        {selected && <ChevronRight className="h-4 w-4 text-primary shrink-0 mt-0.5" />}
      </div>
      <div className="flex flex-wrap gap-1">
        <Badge variant="secondary" className="text-[10px]">{entry.category}</Badge>
        <ConfidenceBadge score={entry.confidence_score} />
        {entry.is_shared && (
          <Badge variant="outline" className="text-[10px] border-sky-500/40 bg-sky-500/10 text-sky-600">
            Shared
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
      <p className="text-[10px] text-muted-foreground">{new Date(entry.updated_at).toLocaleDateString()}</p>
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

  // Debounce search
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value)
    const timer = setTimeout(() => setDebouncedSearch(value), 300)
    return () => clearTimeout(timer)
  }, [])

  // Build query params
  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = { page, per_page: 20 }
    if (selectedCategory) params.category = selectedCategory
    if (debouncedSearch) params.search = debouncedSearch
    return params
  }, [selectedCategory, debouncedSearch, page])

  const { data, isLoading } = useQuery<WikiListResponse>({
    queryKey: ['wiki', agentId, selectedCategory, debouncedSearch, page],
    queryFn: async () => {
      const resp = await api.get(`/api/v2/agents/${agentId}/wiki`, { params: queryParams })
      return resp.data as WikiListResponse
    },
  })

  const entries = data?.entries ?? []
  const total = data?.total ?? 0

  // Category counts from the current list (approximate — full list not paginated here)
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
    a.download = `wiki-${agentId}.${format === 'json' ? 'json' : 'md'}`
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
            placeholder="Search entries..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-9 h-8 text-sm"
          />
        </div>
        <Button size="sm" className="h-8 gap-1" onClick={() => { setEditEntry(null); setShowModal(true) }}>
          <Plus className="h-3.5 w-3.5" />Add Entry
        </Button>
        {/* Export dropdown */}
        <div className="relative group">
          <Button size="sm" variant="outline" className="h-8 gap-1">
            <Download className="h-3.5 w-3.5" />Export
          </Button>
          <div className="absolute right-0 top-full mt-1 z-10 hidden group-hover:block bg-popover border rounded shadow-md min-w-36">
            <button
              className="w-full text-left px-3 py-2 text-sm hover:bg-accent"
              onClick={() => handleExport('json')}
            >
              Export JSON
            </button>
            <button
              className="w-full text-left px-3 py-2 text-sm hover:bg-accent"
              onClick={() => handleExport('markdown')}
            >
              Export Markdown
            </button>
          </div>
        </div>
      </div>

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
            {ALL_CATEGORIES.map((cat) => (
              <button
                key={cat}
                className={cn(
                  'w-full text-left px-3 py-2 text-xs flex items-center justify-between hover:bg-accent/50 transition-colors',
                  selectedCategory === cat && 'bg-accent/30 font-medium',
                )}
                onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
              >
                <span className="truncate pr-1">{CATEGORY_LABELS[cat] ?? cat}</span>
                {categoryCounts[cat] != null && (
                  <Badge variant="secondary" className="text-[10px] shrink-0">{categoryCounts[cat]}</Badge>
                )}
              </button>
            ))}
          </CardContent>
        </Card>

        {/* Entry list */}
        <Card className="overflow-hidden">
          <CardHeader className="py-2 px-3 border-b">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Entries {total > 0 && <span className="normal-case font-normal">({total})</span>}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 overflow-y-auto max-h-[560px]">
            {isLoading ? (
              <EntrySkeleton />
            ) : entries.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 py-16 px-4 text-center">
                <BookOpen className="h-10 w-10 text-muted-foreground/30" />
                <p className="text-sm text-muted-foreground font-medium">No wiki entries yet.</p>
                <p className="text-xs text-muted-foreground/70">
                  The agent will start building knowledge as it trades.
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
            </CardContent>
          )}
        </Card>
      </div>

      {/* Add / Edit modal */}
      <WikiEntryModal
        open={showModal}
        onClose={handleModalClose}
        agentId={agentId}
        existing={editEntry}
      />
    </div>
  )
}
