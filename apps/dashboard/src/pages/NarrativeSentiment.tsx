/**
 * Narrative & Sentiment — NLP-powered sentiment intelligence from the Narrative Sentinel agent.
 * Phoenix v3.
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
import {
  LineChart as RechartsLineChart,
  Line as RechartsLine,
  XAxis as RechartsXAxis,
  YAxis as RechartsYAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer as RechartsResponsiveContainer,
} from 'recharts'
import type { ComponentType } from 'react'
import { MessageCircle, Brain, TrendingUp, AlertTriangle, Newspaper } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const ResponsiveContainer = RechartsResponsiveContainer as unknown as ComponentType<any>
const LineChart = RechartsLineChart as unknown as ComponentType<any>
const XAxis = RechartsXAxis as unknown as ComponentType<any>
const YAxis = RechartsYAxis as unknown as ComponentType<any>
const Tooltip = RechartsTooltip as unknown as ComponentType<any>
const Line = RechartsLine as unknown as ComponentType<any>

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

function heatmapCellColor(score: number): string {
  if (score >= 0.5) return 'bg-emerald-600 text-white'
  if (score >= 0.2) return 'bg-emerald-400/60'
  if (score >= -0.2) return 'bg-slate-200 dark:bg-slate-700'
  if (score >= -0.5) return 'bg-red-400/60'
  return 'bg-red-600 text-white'
}

export default function NarrativeSentimentPage() {
  const [selectedInstance, setSelectedInstance] = useState<string>('')
  const [agentPanelOpen, setAgentPanelOpen] = useState(false)
  const [alertThreshold, setAlertThreshold] = useState(0.7)
  const [sentimentDays, setSentimentDays] = useState('7')
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

  // N2: Sentiment heatmap
  const { data: heatmapData = { heatmap: [] } } = useQuery({
    queryKey: ['narrative-heatmap'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/sentiment-heatmap')
        return res.data ?? { heatmap: [] }
      } catch {
        return { heatmap: [] }
      }
    },
  })

  // N3: Fear & Greed
  const { data: fearGreedData = { score: 50, label: 'Neutral', components: {} } } = useQuery({
    queryKey: ['narrative-fear-greed'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/fear-greed')
        return res.data ?? { score: 50, label: 'Neutral', components: {} }
      } catch {
        return { score: 50, label: 'Neutral', components: {} }
      }
    },
  })

  // N4: Sentiment time-series
  const { data: sentimentTs = { timeseries: [] } } = useQuery({
    queryKey: ['narrative-sentiment-ts', sentimentDays],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/narrative/sentiment-timeseries?days=${sentimentDays}`)
        return res.data ?? { timeseries: [] }
      } catch {
        return { timeseries: [] }
      }
    },
  })

  // N6: Earnings history
  const { data: earningsHistory = [] } = useQuery({
    queryKey: ['narrative-earnings-history'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/narrative/earnings-history')
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
  const heatmapItems = Array.isArray(heatmapData.heatmap) ? heatmapData.heatmap : []
  const timeseriesItems = Array.isArray(sentimentTs.timeseries) ? sentimentTs.timeseries : []
  const earningsHistoryItems = Array.isArray(earningsHistory) ? earningsHistory : []

  // Fear & Greed gauge color
  const fgScore = fearGreedData.score ?? 50
  const fgColor = fgScore >= 60 ? 'text-emerald-600' : fgScore >= 40 ? 'text-amber-600' : 'text-red-600'
  const fgBg = fgScore >= 60 ? 'bg-emerald-500' : fgScore >= 40 ? 'bg-amber-500' : 'bg-red-500'

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
          value={fgScore}
          subtitle={fearGreedData.label ?? '0-100'}
          trend={fgScore >= 50 ? 'up' : 'down'}
        />
        <MetricCard
          title="Discord Activity"
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
              <label className="text-sm font-medium">Active sources</label>
              <div className="flex flex-wrap gap-2 mt-2">
                <Badge variant="default" className="bg-primary text-primary-foreground">Discord</Badge>
                <Badge variant="secondary" className="text-muted-foreground">FinBERT NLP</Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Twitter/Reddit sources planned for future release
              </p>
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
          <TabsTrigger value="heatmap" className="gap-1">
            <TrendingUp className="h-4 w-4" />
            Heatmap
          </TabsTrigger>
          <TabsTrigger value="feargreed" className="gap-1">
            <AlertTriangle className="h-4 w-4" />
            Fear/Greed
          </TabsTrigger>
          <TabsTrigger value="timeseries" className="gap-1">
            <TrendingUp className="h-4 w-4" />
            Trend
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
            Earnings
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

        {/* N2: Sentiment Heatmap */}
        <TabsContent value="heatmap" className="space-y-4">
          <FlexCard title="Sentiment Heatmap by Ticker">
            {heatmapItems.length > 0 ? (
              <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-6 lg:grid-cols-8 gap-2">
                {heatmapItems.map((h: { ticker: string; sentiment: number; mentions: number; label: string }) => (
                  <div
                    key={h.ticker}
                    className={cn(
                      'p-3 rounded-lg text-center',
                      heatmapCellColor(h.sentiment)
                    )}
                    title={`${h.ticker}: ${h.sentiment.toFixed(2)} (${h.mentions} mentions)`}
                  >
                    <p className="font-mono font-bold text-sm">{h.ticker}</p>
                    <p className="text-xs">{h.sentiment.toFixed(2)}</p>
                    <p className="text-xs opacity-70">{h.mentions}m</p>
                    <p className="text-[10px] opacity-80">{h.label}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No heatmap data available. Sentiment is computed from Discord messages with ticker mentions.</p>
            )}
          </FlexCard>
        </TabsContent>

        {/* N3: Fear & Greed */}
        <TabsContent value="feargreed" className="space-y-4">
          <FlexCard title="Fear & Greed Index">
            <div className="flex flex-col items-center gap-4">
              {/* Gauge visualization */}
              <div className="relative w-48 h-24 overflow-hidden">
                <div className="absolute w-48 h-48 rounded-full border-[16px] border-muted -top-24" />
                <div
                  className={cn('absolute w-48 h-48 rounded-full border-[16px] -top-24', fgBg)}
                  style={{
                    clipPath: `polygon(0 50%, ${fgScore}% 50%, ${fgScore}% 100%, 0 100%)`,
                    opacity: 0.7,
                  }}
                />
              </div>
              <div className="text-center">
                <p className={cn('text-4xl font-bold', fgColor)}>{fgScore}</p>
                <p className="text-lg font-medium text-muted-foreground">{fearGreedData.label}</p>
              </div>

              {/* Component breakdown */}
              <div className="w-full space-y-3 mt-4">
                {Object.entries(fearGreedData.components ?? {}).map(([key, comp]: [string, any]) => (
                  <div key={key} className="flex items-center gap-3">
                    <span className="w-40 text-sm text-muted-foreground">{comp.label}</span>
                    <div className="flex-1 h-3 rounded bg-muted overflow-hidden">
                      <div
                        className={cn('h-full rounded', comp.score >= 50 ? 'bg-emerald-500' : 'bg-red-500')}
                        style={{ width: `${comp.score}%` }}
                      />
                    </div>
                    <span className="w-10 text-xs text-right">{comp.score}</span>
                  </div>
                ))}
              </div>
            </div>
          </FlexCard>
        </TabsContent>

        {/* N4: Sentiment time-series */}
        <TabsContent value="timeseries" className="space-y-4">
          <FlexCard title="Sentiment Over Time">
            <div className="flex items-center gap-2 mb-4">
              <label className="text-sm text-muted-foreground">Period:</label>
              <Select value={sentimentDays} onValueChange={setSentimentDays}>
                <SelectTrigger className="w-24">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="7">7 days</SelectItem>
                  <SelectItem value="14">14 days</SelectItem>
                  <SelectItem value="30">30 days</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {timeseriesItems.length > 0 ? (
              <div className="h-[300px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={timeseriesItems}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                    <YAxis tick={{ fontSize: 11 }} domain={[-1, 1]} />
                    <Tooltip />
                    <Line type="monotone" dataKey="sentiment" name="Avg Sentiment" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No time-series data available</p>
            )}
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
                <p className="text-sm font-medium text-muted-foreground mb-2">Trending cashtags (Discord)</p>
                <div className="flex flex-wrap gap-2">
                  {(social.cashtags ?? []).map((t: string) => (
                    <Badge key={t} variant="secondary">{t}</Badge>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Top contributors</p>
                <div className="flex flex-wrap gap-2">
                  {(social.wsbMomentum ?? []).map((t: string) => (
                    <Badge key={t} variant="outline">{t}</Badge>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground mb-2">Sentiment by ticker</p>
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
          <FlexCard title="Upcoming Earnings" action={<AlertTriangle className="h-4 w-4 text-muted-foreground" />}>
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

          {/* N6: Earnings beat/miss history */}
          {earningsHistoryItems.length > 0 && (
            <FlexCard title="EPS Beat/Miss History">
              <div className="rounded-md border overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Ticker</TableHead>
                      <TableHead>Date</TableHead>
                      <TableHead>EPS Est</TableHead>
                      <TableHead>EPS Actual</TableHead>
                      <TableHead>Surprise %</TableHead>
                      <TableHead>Result</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {earningsHistoryItems.map((eh: any, i: number) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono font-semibold">{eh.ticker}</TableCell>
                        <TableCell className="text-muted-foreground">{eh.date ?? 'N/A'}</TableCell>
                        <TableCell>{eh.epsEstimate != null ? `$${eh.epsEstimate.toFixed(2)}` : 'N/A'}</TableCell>
                        <TableCell>{eh.epsActual != null ? `$${eh.epsActual.toFixed(2)}` : 'N/A'}</TableCell>
                        <TableCell className={eh.surprisePct > 0 ? 'text-emerald-600' : eh.surprisePct < 0 ? 'text-red-600' : ''}>
                          {eh.surprisePct != null ? `${eh.surprisePct.toFixed(1)}%` : 'N/A'}
                        </TableCell>
                        <TableCell>
                          <Badge variant={eh.result === 'Beat' ? 'default' : eh.result === 'Miss' ? 'destructive' : 'secondary'}>
                            {eh.result}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </FlexCard>
          )}
        </TabsContent>

        <TabsContent value="analyst" className="space-y-4">
          <FlexCard title="Analyst Moves" action={<TrendingUp className="h-4 w-4 text-muted-foreground" />}>
            <div className="space-y-4">
              {analystItems.map((a: { ticker: string; action: string; firm: string; target: number; impact: string }, i: number) => (
                <div key={`${a.ticker}-${i}`} className="p-4 rounded-lg border flex flex-col sm:flex-row justify-between sm:items-center gap-2">
                  <div>
                    <p className="font-semibold">{a.ticker}</p>
                    <p className="text-sm text-muted-foreground">{a.firm} -- {a.action}</p>
                    {a.target > 0 && <p className="text-sm">Target: ${a.target}</p>}
                  </div>
                  <Badge variant={a.impact.startsWith('+') ? 'default' : a.impact.startsWith('-') ? 'destructive' : 'secondary'}>{a.impact}</Badge>
                </div>
              ))}
            </div>
          </FlexCard>
        </TabsContent>
      </Tabs>
    </div>
  )
}
