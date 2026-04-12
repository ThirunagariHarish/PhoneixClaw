/**
 * Narrative & Sentiment — NLP-powered sentiment intelligence from the Narrative Sentinel agent.
 * Phoenix v2.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { MetricCard } from '@/components/ui/MetricCard'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MessageCircle, Brain, TrendingUp, AlertTriangle, Newspaper } from 'lucide-react'
import { cn } from '@/lib/utils'

const EMPTY_SOCIAL = {
  cashtags: [] as string[],
  wsbMomentum: [] as string[],
  heatmap: [] as Array<{ ticker: string; sentiment: number }>,
}

function sentimentColor(score: number) {
  if (score >= 0.5) return 'bg-emerald-500'
  if (score >= 0) return 'bg-emerald-300'
  if (score >= -0.5) return 'bg-red-300'
  return 'bg-red-500'
}

export default function NarrativeSentimentPage() {
  const [selectedInstance, setSelectedInstance] = useState<string>('')
  const [agentPanelOpen, setAgentPanelOpen] = useState(false)
  const [alertThreshold, setAlertThreshold] = useState(0.7)
  const [sourceToggles, setSourceToggles] = useState({ twitter: true, news: true, reddit: true, sec: true })
  const queryClient = useQueryClient()

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data ?? [],
  })

  const { data: feedResponse } = useQuery({
    queryKey: ['narrative-feed'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/feed')
        return res.data
      } catch {
        return { items: [], metrics: { marketSentiment: 0, fearGreed: 0, twitterVelocity: 0, newsSentimentAvg: 0 } }
      }
    },
  })

  const metrics = feedResponse?.metrics ?? {
    marketSentiment: 0,
    fearGreed: 0,
    twitterVelocity: 0,
    newsSentimentAvg: 0,
  }

  const feed = feedResponse?.items ?? []

  const { data: fedWatch = [] } = useQuery({
    queryKey: ['narrative-fed-watch'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/fed-watch')
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: social = EMPTY_SOCIAL } = useQuery({
    queryKey: ['narrative-social'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/social')
        return res.data ?? EMPTY_SOCIAL
      } catch {
        return EMPTY_SOCIAL
      }
    },
  })

  const { data: earnings = [] } = useQuery({
    queryKey: ['narrative-earnings'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/earnings')
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: analystMoves = [] } = useQuery({
    queryKey: ['narrative-analyst-moves'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/analyst-moves')
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const createAgentMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/narrative/agent/create', {
        instance_id: selectedInstance || 'inst-1',
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['narrative-feed'] }),
  })

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  const feedItems = Array.isArray(feed) ? feed : []
  const fedItems = Array.isArray(fedWatch) ? fedWatch : []
  const earningsItems = Array.isArray(earnings) ? earnings : []
  const analystItems = Array.isArray(analystMoves) ? analystMoves : []

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Brain} title="Narrative & Sentiment" description="Fed watch, earnings, and analyst sentiment" />

      {/* Top Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <MetricCard
          title="Market Sentiment"
          value={`${(((metrics.marketSentiment != null ? metrics.marketSentiment : 0)) * 100).toFixed(0)}%`}
          subtitle="-1 to +1 gauge"
          trend={(metrics.marketSentiment != null ? metrics.marketSentiment : 0) >= 0 ? 'up' : 'down'}
        />
        <MetricCard
          title="Fear & Greed Index"
          value={metrics.fearGreed != null ? metrics.fearGreed : 50}
          subtitle="0-100"
          trend={(metrics.fearGreed ?? 50) >= 50 ? 'up' : 'down'}
        />
        <MetricCard
          title="Twitter Velocity"
          value={((metrics.twitterVelocity != null ? metrics.twitterVelocity : 0) * 100).toFixed(0) + '%'}
          subtitle="Activity score"
        />
        <MetricCard
          title="News Sentiment Avg"
          value={((metrics.newsSentimentAvg != null ? metrics.newsSentimentAvg : 0) * 100).toFixed(0) + '%'}
          subtitle="Aggregate"
        />
      </div>

      {/* Agent Config Panel */}
      {agentPanelOpen && (
        <FlexCard title="Agent Config" className="border-primary/20">
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">Instance</label>
              <Select value={selectedInstance} onValueChange={setSelectedInstance}>
                <SelectTrigger className="mt-1">
                  <SelectValue placeholder="Select instance" />
                </SelectTrigger>
                <SelectContent>
                  {instances.map((inst) => (
                    <SelectItem key={inst.id} value={inst.id}>
                      {inst.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              className="w-full"
              onClick={() => createAgentMutation.mutate()}
              disabled={createAgentMutation.isPending}
            >
              Deploy Sentiment Agent
            </Button>
            <div>
              <label className="text-sm font-medium">Source toggles</label>
              <div className="flex flex-wrap gap-2 mt-2">
                {(['twitter', 'news', 'reddit', 'sec'] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setSourceToggles((s) => ({ ...s, [k]: !s[k] }))}
                    className={cn(
                      'px-3 py-1 rounded text-xs font-medium',
                      sourceToggles[k] ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                    )}
                  >
                    {k}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-sm font-medium">Alert threshold: {alertThreshold}</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={alertThreshold}
                onChange={(e) => setAlertThreshold(Number(e.target.value))}
                className="w-full mt-1"
              />
            </div>
          </div>
        </FlexCard>
      )}

      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => setAgentPanelOpen(!agentPanelOpen)}>
          <Brain className="h-4 w-4 mr-2" />
          Agent Config
        </Button>
      </div>

      {/* Sub-tabs */}
      <Tabs defaultValue="feed" className="space-y-4">
        <TabsList className="flex flex-wrap gap-1">
          <TabsTrigger value="feed" className="gap-1">
            <Newspaper className="h-4 w-4" />
            Sentiment Feed
          </TabsTrigger>
          <TabsTrigger value="fed" className="gap-1">
            <MessageCircle className="h-4 w-4" />
            Fed Watch
          </TabsTrigger>
          <TabsTrigger value="social" className="gap-1">
            <TrendingUp className="h-4 w-4" />
            Social Pulse
          </TabsTrigger>
          <TabsTrigger value="earnings" className="gap-1">
            <AlertTriangle className="h-4 w-4" />
            Earnings Intelligence
          </TabsTrigger>
          <TabsTrigger value="analyst" className="gap-1">
            <TrendingUp className="h-4 w-4" />
            Analyst Moves
          </TabsTrigger>
        </TabsList>

        <TabsContent value="feed" className="space-y-4">
          <FlexCard title="Live Sentiment Feed" action={<Newspaper className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-3">
              {feedItems.map((item: { id: string; ts: string; source: string; headline: string; score: number; tickers: string[]; urgent?: boolean }) => (
                <div
                  key={item.id}
                  className={cn(
                    'p-4 rounded-lg border transition-colors',
                    item.urgent && 'border-amber-500/50 bg-amber-500/5 animate-pulse'
                  )}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span>{formatTime(item.ts)}</span>
                        <Badge variant="outline">{item.source}</Badge>
                        {item.urgent && <AlertTriangle className="h-4 w-4 text-amber-500" />}
                      </div>
                      <p className="font-medium mt-1">{item.headline}</p>
                      <div className="flex flex-wrap gap-1 mt-2">
                        {item.tickers.map((t) => (
                          <Badge key={t} variant="secondary" className="text-xs">
                            {t}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <div className="flex flex-col items-end shrink-0">
                      <span className="text-sm font-mono">{item.score.toFixed(2)}</span>
                      <div className="w-16 h-2 rounded-full bg-muted overflow-hidden mt-1">
                        <div
                          className={cn('h-full rounded-full', sentimentColor(item.score))}
                          style={{ width: `${((item.score + 1) / 2) * 100}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="fed" className="space-y-4">
          <FlexCard title="Fed Watch" action={<MessageCircle className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              {fedItems.map((s: { id: string; name: string; date: string; summary: string; hawkish: number; dovish: number }) => (
                <div key={s.id} className="p-4 rounded-lg border">
                  <div className="flex flex-col sm:flex-row justify-between items-start gap-2">
                    <div className="min-w-0">
                      <p className="font-semibold truncate">{s.name}</p>
                      <p className="text-sm text-muted-foreground">{s.date}</p>
                      <p className="text-sm mt-2">{s.summary}</p>
                    </div>
                    <div className="flex gap-2">
                      <Badge variant="outline" className="bg-amber-500/20">Hawkish {Math.round(s.hawkish * 100)}%</Badge>
                      <Badge variant="outline" className="bg-blue-500/20">Dovish {Math.round(s.dovish * 100)}%</Badge>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="social" className="space-y-4">
          <FlexCard title="Social Pulse" action={<TrendingUp className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Twitter trending cashtags</p>
                <div className="flex flex-wrap gap-2">
                  {(social.cashtags ?? []).map((t: string) => (
                    <Badge key={t} variant="secondary">{t}</Badge>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">WSB momentum tickers</p>
                <div className="flex flex-wrap gap-2">
                  {(social.wsbMomentum ?? []).map((t: string) => (
                    <Badge key={t} variant="outline">{t}</Badge>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Sentiment heatmap by ticker</p>
                <div className="space-y-2">
                  {(social.heatmap ?? []).map((h: { ticker: string; sentiment: number }) => (
                    <div key={h.ticker} className="flex items-center gap-2">
                      <span className="w-12 font-mono text-sm">{h.ticker}</span>
                      <div className="flex-1 h-4 rounded bg-muted overflow-hidden">
                        <div
                          className={cn('h-full rounded', sentimentColor(h.sentiment))}
                          style={{ width: `${((h.sentiment + 1) / 2) * 100}%` }}
                        />
                      </div>
                      <span className="text-xs w-8">{h.sentiment.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="earnings" className="space-y-4">
          <FlexCard title="Earnings Intelligence" action={<AlertTriangle className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              {earningsItems.map((e: { ticker: string; date: string; expectation: number; postRisk: string | null }) => (
                <div key={e.ticker} className="p-4 rounded-lg border">
                  <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-2">
                    <div>
                      <p className="font-semibold">{e.ticker}</p>
                      <p className="text-sm text-muted-foreground">{e.date}</p>
                      <p className="text-sm mt-1">Sentiment expectation: {(e.expectation * 100).toFixed(0)}%</p>
                      {e.postRisk && (
                        <Badge variant="destructive" className="mt-2">{e.postRisk}</Badge>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="analyst" className="space-y-4">
          <FlexCard title="Analyst Moves" action={<TrendingUp className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              {analystItems.map((a: { ticker: string; action: string; firm: string; target: number; impact: string }) => (
                <div key={a.ticker} className="p-4 rounded-lg border flex flex-col sm:flex-row justify-between sm:items-center gap-2">
                  <div>
                    <p className="font-semibold">{a.ticker}</p>
                    <p className="text-sm text-muted-foreground">{a.firm} — {a.action}</p>
                    <p className="text-sm">Target: ${a.target}</p>
                  </div>
                  <Badge variant={a.impact.startsWith('+') ? 'default' : 'destructive'}>{a.impact}</Badge>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>
      </Tabs>
    </div>
  )
}
