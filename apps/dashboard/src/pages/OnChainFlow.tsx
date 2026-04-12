/**
 * On-Chain/Flow page — whale movements, unusual options flow, institutional positioning.
 * Phoenix v2.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { MetricCard } from '@/components/ui/MetricCard'
import {
  Activity,
  BarChart3,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
} from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'

type FlowDirection = 'ACCUMULATING' | 'DISTRIBUTING' | 'NEUTRAL'
type Sentiment = 'BULLISH' | 'BEARISH' | 'NEUTRAL'
type WhaleType = 'CALL' | 'PUT' | 'STOCK'

interface Mag7Card {
  ticker: string
  whale_trades: string[]
  call_put_ratio: number
  dark_pool_pct: number
  institutional_flow: FlowDirection
}

interface MemeCard extends Mag7Card {
  social_sentiment: number
}

interface SectorFlow {
  sector: string
  net_direction: FlowDirection
  top_movers: { ticker: string; flow_pct: number }[]
}

interface IndexFlow {
  symbol: string
  gex_level: string
  odte_volume: string
  put_call_skew: number
  dark_pool_pct: number
}

interface WhaleAlert {
  timestamp: string
  ticker: string
  type: WhaleType
  size: number
  premium: number
  sentiment: Sentiment
  exchange: string
}

interface FlowMetrics {
  whale_alerts_24h: number
  unusual_flow_volume: string
  dark_pool_activity: string
  institutional_sentiment: FlowDirection
}

const EMPTY_FLOW_METRICS: FlowMetrics = {
  whale_alerts_24h: 0,
  unusual_flow_volume: '$0',
  dark_pool_activity: '0%',
  institutional_sentiment: 'NEUTRAL',
}

function flowColor(dir: FlowDirection | Sentiment) {
  if (dir === 'ACCUMULATING' || dir === 'BULLISH') return 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/10'
  if (dir === 'DISTRIBUTING' || dir === 'BEARISH') return 'text-red-600 dark:text-red-400 bg-red-500/10'
  return 'text-amber-600 dark:text-amber-400 bg-amber-500/10'
}

function FlowIcon({ dir }: { dir: FlowDirection | Sentiment }) {
  if (dir === 'ACCUMULATING' || dir === 'BULLISH') return <TrendingUp className="h-3 w-3 inline mr-0.5" />
  if (dir === 'DISTRIBUTING' || dir === 'BEARISH') return <TrendingDown className="h-3 w-3 inline mr-0.5" />
  return <AlertTriangle className="h-3 w-3 inline mr-0.5" />
}

export default function OnChainFlowPage() {
  const [selectedInstance, setSelectedInstance] = useState('')
  const [minPremium, setMinPremium] = useState('500000')
  const [minSize, setMinSize] = useState('100')
  const [watchedTickers, setWatchedTickers] = useState('SPY,QQQ,NVDA,AAPL,TSLA')
  const queryClient = useQueryClient()

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data ?? [],
  })

  const { data: metrics = EMPTY_FLOW_METRICS } = useQuery<FlowMetrics>({
    queryKey: ['onchain-flow-metrics'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/onchain-flow/whale-alerts')
        return { ...EMPTY_FLOW_METRICS, whale_alerts_24h: Array.isArray(res.data) ? res.data.length : 0 }
      } catch {
        return EMPTY_FLOW_METRICS
      }
    },
  })

  const { data: whaleAlerts = [] } = useQuery<WhaleAlert[]>({
    queryKey: ['onchain-flow-whale-alerts'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/onchain-flow/whale-alerts')
        return Array.isArray(res.data) ? res.data : []
      } catch {
        return []
      }
    },
    refetchInterval: 30000,
  })

  const { data: mag7 = [] } = useQuery<Mag7Card[]>({
    queryKey: ['onchain-flow-mag7'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/onchain-flow/mag7')
        return res.data?.tickers ?? []
      } catch {
        return []
      }
    },
  })

  const { data: meme = [] } = useQuery<MemeCard[]>({
    queryKey: ['onchain-flow-meme'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/onchain-flow/meme')
        return res.data?.tickers ?? []
      } catch {
        return []
      }
    },
  })

  const { data: sectors = [] } = useQuery<SectorFlow[]>({
    queryKey: ['onchain-flow-sectors'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/onchain-flow/sectors')
        return res.data?.sectors ?? []
      } catch {
        return []
      }
    },
  })

  const { data: indices = [] } = useQuery<IndexFlow[]>({
    queryKey: ['onchain-flow-indices'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/onchain-flow/indices')
        return res.data?.indices ?? []
      } catch {
        return []
      }
    },
  })

  const deployMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/onchain-flow/agent/create', {
        instance_id: selectedInstance || 'inst-1',
        watched_tickers: watchedTickers.split(',').map((t) => t.trim()).filter(Boolean),
        min_premium: Number(minPremium) || 500000,
        min_size: Number(minSize) || 100,
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['onchain-flow-metrics'] }),
  })

  const formatTime = (iso: string) => {
    if (!iso) return 'N/A'
    const d = new Date(iso)
    return isNaN(d.getTime()) ? 'N/A' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  const formatPremium = (n: number) => {
    if (n == null || isNaN(n)) return '$0'
    return n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : `$${(n / 1e3).toFixed(0)}K`
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={BarChart3} title="On-Chain / Flow" description="Whale movements, unusual options flow, institutional positioning" />

      {/* Top Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <MetricCard
          title="Total Whale Alerts (24h)"
          value={metrics.whale_alerts_24h}
          trend="up"
          subtitle="Live feed"
        />
        <MetricCard title="Unusual Flow Volume" value={metrics.unusual_flow_volume} />
        <MetricCard title="Dark Pool Activity" value={metrics.dark_pool_activity} />
        <MetricCard
          title="Institutional Sentiment"
          value={metrics.institutional_sentiment}
          trend={metrics.institutional_sentiment === 'ACCUMULATING' ? 'up' : metrics.institutional_sentiment === 'DISTRIBUTING' ? 'down' : undefined}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 sm:gap-4">
        <div className="lg:col-span-3">
          <Tabs defaultValue="mag7">
            <TabsList className="flex flex-wrap h-auto gap-1">
              <TabsTrigger value="mag7">Mag 7</TabsTrigger>
              <TabsTrigger value="meme">Meme Stocks</TabsTrigger>
              <TabsTrigger value="sectors">Sector Flow</TabsTrigger>
              <TabsTrigger value="indices">Indices</TabsTrigger>
              <TabsTrigger value="whale">Whale Alerts</TabsTrigger>
            </TabsList>

            <TabsContent value="mag7" className="mt-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
                {(Array.isArray(mag7) ? mag7 : []).map((card) => (
                  <FlexCard key={card.ticker} title={card.ticker}>
                    <div className="space-y-2 text-sm">
                      <div>
                        <p className="text-muted-foreground text-xs mb-1">Latest whale trades</p>
                        <ul className="space-y-0.5">
                          {(card.whale_trades || []).slice(0, 2).map((t, i) => (
                            <li key={i} className="font-mono text-xs truncate">{t}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">C/P ratio</span>
                        <span>{(card.call_put_ratio ?? 0).toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Dark pool %</span>
                        <span>{card.dark_pool_pct ?? 0}%</span>
                      </div>
                      <Badge className={flowColor(card.institutional_flow)}><FlowIcon dir={card.institutional_flow} />{card.institutional_flow}</Badge>
                    </div>
                  </FlexCard>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="meme" className="mt-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
                {(Array.isArray(meme) ? meme : []).map((card) => (
                  <FlexCard key={card.ticker} title={card.ticker}>
                    <div className="space-y-2 text-sm">
                      <div>
                        <p className="text-muted-foreground text-xs mb-1">Latest whale trades</p>
                        <ul className="space-y-0.5">
                          {(card.whale_trades || []).slice(0, 2).map((t, i) => (
                            <li key={i} className="font-mono text-xs truncate">{t}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Social sentiment</span>
                        <span>{card.social_sentiment ?? 0}%</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">C/P ratio</span>
                        <span>{(card.call_put_ratio ?? 0).toFixed(2)}</span>
                      </div>
                      <Badge className={flowColor(card.institutional_flow)}><FlowIcon dir={card.institutional_flow} />{card.institutional_flow}</Badge>
                    </div>
                  </FlexCard>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="sectors" className="mt-4">
              <div className="space-y-4">
                {(Array.isArray(sectors) ? sectors : []).map((s) => (
                  <FlexCard key={s.sector} title={s.sector}>
                    <div className="flex flex-wrap items-center gap-4">
                      <Badge className={flowColor(s.net_direction)}><FlowIcon dir={s.net_direction} />{s.net_direction}</Badge>
                      <div className="flex gap-4">
                        {(s.top_movers || []).map((m) => (
                          <span key={m.ticker} className="font-mono text-sm">
                            {m.ticker} <span className={m.flow_pct >= 0 ? 'text-emerald-600' : 'text-red-600'}>{m.flow_pct >= 0 ? '+' : ''}{m.flow_pct}%</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  </FlexCard>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="indices" className="mt-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                {(Array.isArray(indices) ? indices : []).map((idx) => (
                  <FlexCard key={idx.symbol} title={idx.symbol}>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <span className="text-muted-foreground">GEX level</span>
                      <span>{idx.gex_level}</span>
                      <span className="text-muted-foreground">0DTE volume</span>
                      <span>{idx.odte_volume}</span>
                      <span className="text-muted-foreground">Put/call skew</span>
                      <span>{(idx.put_call_skew ?? 0).toFixed(2)}</span>
                      <span className="text-muted-foreground">Dark pool %</span>
                      <span>{idx.dark_pool_pct ?? 0}%</span>
                    </div>
                  </FlexCard>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="whale" className="mt-4">
              <FlexCard title="Live Whale Alerts">
                <div className="rounded-md border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Time</TableHead>
                        <TableHead>Ticker</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>Size</TableHead>
                        <TableHead>Premium</TableHead>
                        <TableHead>Sentiment</TableHead>
                        <TableHead>Exchange</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(Array.isArray(whaleAlerts) ? whaleAlerts : []).map((a, i) => (
                        <TableRow key={i}>
                          <TableCell className="text-muted-foreground">{formatTime(a.timestamp)}</TableCell>
                          <TableCell className="font-mono font-semibold">{a.ticker}</TableCell>
                          <TableCell><Badge variant="outline">{a.type}</Badge></TableCell>
                          <TableCell>{a.size}</TableCell>
                          <TableCell>{formatPremium(a.premium)}</TableCell>
                          <TableCell><Badge className={flowColor(a.sentiment)}><FlowIcon dir={a.sentiment} />{a.sentiment}</Badge></TableCell>
                          <TableCell className="text-muted-foreground">{a.exchange}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </FlexCard>
            </TabsContent>
          </Tabs>
        </div>

        {/* Agent Config Panel */}
        <FlexCard title="Flow Monitor Agent">
          <div className="space-y-4">
            <div>
              <Label className="text-xs">Instance</Label>
              <Select value={selectedInstance} onValueChange={setSelectedInstance}>
                <SelectTrigger className="mt-1">
                  <SelectValue placeholder="Select instance" />
                </SelectTrigger>
                <SelectContent>
                  {instances.map((inst) => (
                    <SelectItem key={inst.id} value={inst.id}>{inst.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              className="w-full"
              onClick={() => deployMutation.mutate()}
              disabled={deployMutation.isPending}
            >
              <Activity className="h-4 w-4 mr-2" />
              Deploy Flow Monitor
            </Button>
            <div>
              <Label className="text-xs">Watched tickers</Label>
              <Input
                className="mt-1"
                value={watchedTickers}
                onChange={(e) => setWatchedTickers(e.target.value)}
                placeholder="SPY, QQQ, NVDA, ..."
              />
            </div>
            <div>
              <Label className="text-xs">Min premium ($)</Label>
              <Input
                className="mt-1"
                type="number"
                value={minPremium}
                onChange={(e) => setMinPremium(e.target.value)}
                placeholder="500000"
              />
            </div>
            <div>
              <Label className="text-xs">Min size (contracts)</Label>
              <Input
                className="mt-1"
                type="number"
                value={minSize}
                onChange={(e) => setMinSize(e.target.value)}
                placeholder="100"
              />
            </div>
          </div>
        </FlexCard>
      </div>
    </div>
  )
}
