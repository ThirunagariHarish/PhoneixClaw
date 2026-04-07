/**
 * Briefing History — scheduler message archive.
 * Route: /briefings
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronRight, Clock, Mail } from 'lucide-react'

interface Briefing {
  id: number
  kind: string
  title: string
  body: string
  data: Record<string, unknown>
  agents_woken: number
  dispatched_to: string[]
  created_at: string | null
}

const KIND_FILTERS = [
  { value: '', label: 'All' },
  { value: 'morning', label: 'Morning' },
  { value: 'eod', label: 'EOD' },
  { value: 'daily_summary', label: 'Daily Summary' },
  { value: 'supervisor', label: 'Supervisor' },
]

export default function BriefingHistory() {
  const [kind, setKind] = useState('')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const { data, isLoading } = useQuery<{ briefings: Briefing[]; count: number }>({
    queryKey: ['briefings', kind],
    queryFn: async () => {
      const q = kind ? `?kind=${kind}&limit=100` : `?limit=100`
      return (await api.get(`/api/v2/briefings${q}`)).data
    },
    refetchInterval: 30000,
  })

  const briefings = data?.briefings ?? []

  const toggle = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Mail}
        title="Briefing History"
        description="Every scheduled briefing the system has ever sent"
      />

      <div className="flex gap-2">
        {KIND_FILTERS.map((f) => (
          <Button
            key={f.value}
            variant={kind === f.value ? 'default' : 'outline'}
            size="sm"
            onClick={() => setKind(f.value)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-center py-8 text-muted-foreground">Loading…</div>
      ) : briefings.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            <Clock className="h-8 w-8 mx-auto mb-3 opacity-50" />
            <p className="text-sm">No briefings yet.</p>
            <p className="text-xs mt-1">
              The scheduler will log every morning / EOD / daily summary run here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {briefings.map((b) => {
            const isOpen = expanded.has(b.id)
            return (
              <Card key={b.id}>
                <CardContent className="p-0">
                  <button
                    onClick={() => toggle(b.id)}
                    className="w-full p-3 flex items-center justify-between hover:bg-muted/30 transition-colors text-left"
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      {isOpen ? (
                        <ChevronDown className="w-4 h-4 shrink-0" />
                      ) : (
                        <ChevronRight className="w-4 h-4 shrink-0" />
                      )}
                      <Badge variant="outline" className="text-xs">
                        {b.kind}
                      </Badge>
                      <span className="font-medium text-sm truncate">{b.title}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
                      {b.agents_woken > 0 && (
                        <span>{b.agents_woken} woken</span>
                      )}
                      {b.dispatched_to.map((ch) => (
                        <Badge key={ch} variant="outline" className="text-[10px]">
                          {ch}
                        </Badge>
                      ))}
                      <span>
                        {b.created_at
                          ? new Date(b.created_at).toLocaleString()
                          : ''}
                      </span>
                    </div>
                  </button>
                  {isOpen && (
                    <div className="px-4 pb-4 pt-1 border-t">
                      <pre className="text-sm whitespace-pre-wrap font-sans leading-relaxed">
                        {b.body}
                      </pre>
                      {b.data && Object.keys(b.data).length > 0 && (
                        <details className="mt-3 text-xs text-muted-foreground">
                          <summary className="cursor-pointer hover:text-foreground">
                            Raw data
                          </summary>
                          <pre className="mt-2 bg-muted p-2 rounded overflow-x-auto font-mono">
                            {JSON.stringify(b.data, null, 2)}
                          </pre>
                        </details>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
