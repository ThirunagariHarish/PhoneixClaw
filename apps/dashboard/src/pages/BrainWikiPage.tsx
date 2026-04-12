/**
 * BrainWikiPage — Phoenix Brain: all is_shared=true wiki entries across all agents.
 * Route: /brain/wiki
 * Read-only view of the collective knowledge base.
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Brain, BookOpen, Search, TrendingUp, Tag, Share2, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

/* ─────────────────────────────────────────────
   Types
───────────────────────────────────────────── */

interface BrainWikiEntry {
  id: string
  agent_id: string
  agent_name?: string
  category: string
  subcategory?: string
  title: string
  content: string
  tags: string[]
  symbols: string[]
  confidence_score: number
  is_shared: boolean
  version: number
  created_at: string
  updated_at: string
}

interface BrainWikiResponse {
  entries: BrainWikiEntry[]
  total: number
  page: number
  per_page: number
}

/* ─────────────────────────────────────────────
   Constants
───────────────────────────────────────────── */

const ALL_CATEGORIES = [
  'ALL',
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
  ALL: 'All Categories',
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
   Confidence badge
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
   Entry card
───────────────────────────────────────────── */

function BrainEntryCard({ entry }: { entry: BrainWikiEntry }) {
  const [expanded, setExpanded] = useState(false)
  const excerpt = entry.content.length > 200 ? entry.content.slice(0, 200) + '...' : entry.content

  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardContent className="p-4 space-y-2">
        <div className="flex items-start gap-2">
          <div className="flex-1 space-y-1">
            <h3 className="text-sm font-semibold leading-snug">{entry.title}</h3>
            {entry.agent_name && (
              <p className="text-[10px] text-muted-foreground">
                by <span className="font-medium">{entry.agent_name}</span>
              </p>
            )}
          </div>
          <Share2 className="h-3.5 w-3.5 text-sky-500 shrink-0 mt-0.5" />
        </div>

        <div className="flex flex-wrap gap-1">
          <Badge variant="secondary" className="text-[10px]">{entry.category}</Badge>
          <ConfidenceBadge score={entry.confidence_score} />
        </div>

        <p className="text-xs text-muted-foreground leading-relaxed">
          {expanded ? entry.content : excerpt}
          {entry.content.length > 200 && (
            <button
              className="ml-1 text-primary underline"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? 'less' : 'more'}
            </button>
          )}
        </p>

        <div className="flex flex-wrap gap-2">
          {entry.symbols.length > 0 && (
            <div className="flex items-center gap-1">
              <TrendingUp className="h-3 w-3 text-muted-foreground" />
              <div className="flex gap-0.5">
                {entry.symbols.slice(0, 4).map((s) => (
                  <Badge key={s} variant="outline" className="text-[10px] font-mono">{s}</Badge>
                ))}
              </div>
            </div>
          )}
          {entry.tags.length > 0 && (
            <div className="flex items-center gap-1">
              <Tag className="h-3 w-3 text-muted-foreground" />
              <div className="flex gap-0.5 flex-wrap">
                {entry.tags.slice(0, 4).map((t) => (
                  <span key={t} className="text-[10px] text-muted-foreground">#{t}</span>
                ))}
              </div>
            </div>
          )}
        </div>

        <p className="text-[10px] text-muted-foreground">
          {new Date(entry.updated_at).toLocaleDateString()}
        </p>
      </CardContent>
    </Card>
  )
}

/* ─────────────────────────────────────────────
   Skeleton grid
───────────────────────────────────────────── */

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {[...Array(6)].map((_, i) => (
        <Card key={i}>
          <CardContent className="p-4 space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

/* ─────────────────────────────────────────────
   Main page
───────────────────────────────────────────── */

const ENTRIES_PER_PAGE = 10

export default function BrainWikiPage() {
  const [category, setCategory] = useState('ALL')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [minConfidence, setMinConfidence] = useState(0)
  const [page, setPage] = useState(1)

  const handleSearchChange = (value: string) => {
    setSearch(value)
    setPage(1) // Reset to first page on search change
    setTimeout(() => setDebouncedSearch(value), 300)
  }

  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      per_page: 50,
      min_confidence: minConfidence,
    }
    if (category !== 'ALL') params.category = category
    if (debouncedSearch) params.search = debouncedSearch
    return params
  }, [category, debouncedSearch, minConfidence])

  const { data, isLoading } = useQuery<BrainWikiResponse>({
    queryKey: ['brain-wiki', category, debouncedSearch, minConfidence],
    queryFn: async () => {
      const resp = await api.get('/api/v2/brain/wiki', { params: queryParams })
      return resp.data as BrainWikiResponse
    },
  })

  const entries = data?.entries ?? []

  // Client-side pagination
  const totalPages = Math.max(1, Math.ceil(entries.length / ENTRIES_PER_PAGE))
  const paginatedEntries = entries.slice((page - 1) * ENTRIES_PER_PAGE, page * ENTRIES_PER_PAGE)

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <Brain className="h-7 w-7 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Phoenix Brain</h1>
          <p className="text-sm text-muted-foreground">
            Collective knowledge shared across all agents — {data?.total ?? 0} entries
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search knowledge base..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Category</Label>
          <Select value={category} onValueChange={(v) => { setCategory(v); setPage(1) }}>
            <SelectTrigger className="w-48">
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
          <Label className="text-xs">Min Confidence: {Math.round(minConfidence * 100)}%</Label>
          <div className="relative w-36">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(e) => { setMinConfidence(parseFloat(e.target.value)); setPage(1) }}
              className="w-full h-2 rounded-full appearance-none cursor-pointer bg-muted accent-primary
                [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4
                [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:shadow-md
                [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-background
                [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full
                [&::-moz-range-thumb]:bg-primary [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-background"
            />
            <div
              className="absolute top-0 left-0 h-2 rounded-full bg-primary/30 pointer-events-none"
              style={{ width: `${minConfidence * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <SkeletonGrid />
      ) : entries.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
          <BookOpen className="h-14 w-14 text-muted-foreground/20" />
          <p className="text-lg font-medium text-muted-foreground">No shared knowledge yet</p>
          <p className="text-sm text-muted-foreground/70">
            Agents will share knowledge here as they trade and learn.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {paginatedEntries.map((entry) => (
              <BrainEntryCard key={entry.id} entry={entry} />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 pt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                <ChevronLeft className="h-4 w-4 mr-1" /> Prev
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
              >
                Next <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
