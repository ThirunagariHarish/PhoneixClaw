/**
 * VenueSelectorPills — Phase 15.7
 * Three-pill segmented control for selecting active venue.
 * Reads agent health to show a live status dot per venue.
 */
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

export type VenueId = 'robinhood' | 'polymarket' | 'all'

interface VenueHealth {
  venue: string
  status: 'healthy' | 'degraded' | 'dead'
  last_seen_at?: string | null
}

interface VenueSelectorPillsProps {
  selected: VenueId
  onChange: (v: VenueId) => void
}

const VENUES: { id: VenueId; label: string }[] = [
  { id: 'robinhood', label: 'Robinhood Predictions' },
  { id: 'polymarket', label: 'Polymarket' },
  { id: 'all', label: 'All Venues' },
]

const STATUS_DOT: Record<string, string> = {
  healthy: 'bg-emerald-400',
  degraded: 'bg-yellow-400',
  dead: 'bg-red-400',
}

export function VenueSelectorPills({ selected, onChange }: VenueSelectorPillsProps) {
  const { data: health = [] } = useQuery({
    queryKey: ['pm-agents-health'],
    queryFn: async () =>
      (await api.get<VenueHealth[]>('/api/polymarket/agents/health')).data,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  const statusMap = new Map(health.map((h) => [h.venue, h.status]))

  return (
    <div className="flex gap-1 rounded-lg border border-border bg-muted/30 p-1 w-fit">
      {VENUES.map(({ id, label }) => {
        const status = id !== 'all' ? statusMap.get(id) : undefined
        return (
          <button
            key={id}
            type="button"
            onClick={() => onChange(id)}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              selected === id
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {status && (
              <span
                className={cn(
                  'inline-block h-2 w-2 rounded-full shrink-0',
                  STATUS_DOT[status] ?? 'bg-gray-400',
                )}
              />
            )}
            {label}
          </button>
        )
      })}
    </div>
  )
}
