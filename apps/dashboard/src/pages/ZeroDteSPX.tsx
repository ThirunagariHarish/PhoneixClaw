/**
 * 0DTE SPX Command Center — EOD SPX/SPY trading dashboard for 0DTE options.
 * Phoenix v2.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { MetricCard } from '@/components/ui/MetricCard'
import {
  Timer,
  Target,
  Zap,
  Activity,
} from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { getMetricTooltip } from '@/lib/metricTooltips'

const EMPTY_SPX = { price: 0, change: 0, changePct: 0 }
const EMPTY_METRICS = {
  vix: 0,
  gexNet: 0,
  dealerGammaZone: '—',
  zeroDteVolume: 0,
  putCallRatio: 0,
  mocImbalance: 0,
}
const EMPTY_GAMMA_LEVELS: Array<{ strike: number; gex: number; type: string; distance: number }> = []
const EMPTY_MOC = {
  direction: '—',
  amount: 0,
  historicalAvg: 0,
  predictedImpact: 0,
  tradeSignal: '—',
  releaseTime: '15:50',
}
const EMPTY_VANNA_CHARM = {
  vannaLevel: 0,
  vannaDirection: 'up',
  charmBidActive: false,
  strikes: [] as Array<{ strike: number; vanna: number; charm: number }>,
}
const EMPTY_VOLUME = {
  callVolume: 0,
  putVolume: 0,
  ratio: 0,
  volumeByStrike: [] as Array<{ strike: number; calls: number; puts: number }>,
  largestTrades: [] as Array<{ strike: number; type: string; size: number; premium: number }>,
  gammaSqueezeSignal: false,
}
const EMPTY_TRADE_PLAN = {
  direction: '—',
  instrument: '—',
  strikes: '—',
  size: '—',
  entry: '—',
  stop: '—',
  target: '—',
  signals: [] as string[],
}

function useCountdownTo(targetHour: number, targetMin: number) {
  const [remaining, setRemaining] = useState<string>('')
  useEffect(() => {
    const tick = () => {
      const now = new Date()
      const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }))
      const target = new Date(et)
      target.setHours(targetHour, targetMin, 0, 0)
      if (et >= target) target.setDate(target.getDate() + 1)
      const ms = target.getTime() - et.getTime()
      const m = Math.floor(ms / 60000)
      const s = Math.floor((ms % 60000) / 1000)
      setRemaining(`${m}m ${s}s`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [targetHour, targetMin])
  return remaining
}

export default function ZeroDteSPXPage() {
  const [selectedInstance, setSelectedInstance] = useState<string>('')
  const [tradingMode, setTradingMode] = useState<'observe' | 'paper' | 'live'>('observe')
  const [maxRiskPct, setMaxRiskPct] = useState(1)
  const [autoExecute, setAutoExecute] = useState(false)
  const queryClient = useQueryClient()
  const countdownToClose = useCountdownTo(16, 0)
  const countdownToMoc = useCountdownTo(15, 50)

  const { data: spxData = EMPTY_SPX } = useQuery({
    queryKey: ['zero-dte', 'spx-price'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/spx-price')
        return res.data ?? EMPTY_SPX
      } catch {
        return EMPTY_SPX
      }
    },
    refetchInterval: 10000,
  })

  const { data: spxMetrics = EMPTY_METRICS } = useQuery({
    queryKey: ['zero-dte', 'metrics'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/metrics')
        return res.data ?? EMPTY_METRICS
      } catch {
        return EMPTY_METRICS
      }
    },
    refetchInterval: 30000,
  })

  const { data: instances = [] } = useQuery<Array<{ id: string; name: string }>>({
    queryKey: ['instances'],
    queryFn: async () => (await api.get('/api/v2/instances')).data ?? [],
  })

  const { data: gammaLevels = EMPTY_GAMMA_LEVELS } = useQuery({
    queryKey: ['zero-dte', 'gamma-levels'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/gamma-levels')
        return res.data ?? EMPTY_GAMMA_LEVELS
      } catch {
        return EMPTY_GAMMA_LEVELS
      }
    },
    refetchInterval: 30000,
  })

  const { data: mocData = EMPTY_MOC } = useQuery({
    queryKey: ['zero-dte', 'moc-imbalance'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/moc-imbalance')
        return res.data ?? EMPTY_MOC
      } catch {
        return EMPTY_MOC
      }
    },
    refetchInterval: 60000,
  })

  const { data: vannaCharm = EMPTY_VANNA_CHARM } = useQuery({
    queryKey: ['zero-dte', 'vanna-charm'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/vanna-charm')
        return res.data ?? EMPTY_VANNA_CHARM
      } catch {
        return EMPTY_VANNA_CHARM
      }
    },
    refetchInterval: 30000,
  })

  const { data: volume = EMPTY_VOLUME } = useQuery({
    queryKey: ['zero-dte', 'volume'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/volume')
        return res.data ?? EMPTY_VOLUME
      } catch {
        return EMPTY_VOLUME
      }
    },
    refetchInterval: 15000,
  })

  const { data: tradePlan = EMPTY_TRADE_PLAN } = useQuery({
    queryKey: ['zero-dte', 'trade-plan'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/trade-plan')
        return res.data ?? EMPTY_TRADE_PLAN
      } catch {
        return EMPTY_TRADE_PLAN
      }
    },
    refetchInterval: 60000,
  })

  const deployMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/zero-dte/agent/create', { instance_id: selectedInstance || 'inst-1' })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zero-dte'] }),
  })

  const executeMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/zero-dte/execute', { plan: tradePlan })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zero-dte'] }),
  })

  const formatGex = (v: number) =>
    v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : `${(v / 1e3).toFixed(0)}K`
  const formatMoc = (v: number) => `${(v / 1e6).toFixed(0)}M`

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Activity} title="0DTE SPX Command Center" description="Zero days to expiration SPX options flow and signals">
        <div className="flex flex-wrap items-center gap-2 sm:gap-4 text-muted-foreground">
          <span className="font-mono text-base sm:text-lg font-semibold text-foreground">
            SPX {spxData.price ? spxData.price.toLocaleString() : '—'}
          </span>
          <span className={spxData.change >= 0 ? 'text-emerald-600' : 'text-red-600'}>
            {spxData.change >= 0 ? '+' : ''}{spxData.change} ({spxData.changePct}%)
          </span>
          <span className="flex items-center gap-1">
            <Timer className="h-4 w-4" />
            Close in {countdownToClose}
          </span>
        </div>
      </PageHeader>

      {/* Top Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2 sm:gap-3">
        <MetricCard title="SPX Price" value={spxData.price ? spxData.price.toLocaleString() : '—'} tooltip={getMetricTooltip('SPX Price')} />
        <MetricCard title="VIX" value={spxMetrics.vix || '—'} tooltip={getMetricTooltip('VIX')} />
        <MetricCard
          title="GEX Net"
          value={spxMetrics.gexNet ? formatGex(spxMetrics.gexNet) : '—'}
          trend={spxMetrics.gexNet >= 0 ? 'up' : 'down'}
          tooltip={getMetricTooltip('GEX Net')}
        />
        <MetricCard
          title="Dealer Gamma Zone"
          value={spxMetrics.dealerGammaZone}
          trend={spxMetrics.dealerGammaZone === 'Positive' ? 'up' : 'down'}
          tooltip={getMetricTooltip('Dealer Gamma Zone')}
        />
        <MetricCard title="0DTE Volume" value={spxMetrics.zeroDteVolume ? formatGex(spxMetrics.zeroDteVolume) : '—'} tooltip={getMetricTooltip('ODTE Volume')} />
        <MetricCard title="Put/Call Ratio" value={spxMetrics.putCallRatio ? spxMetrics.putCallRatio.toFixed(2) : '—'} tooltip={getMetricTooltip('Put/Call Ratio')} />
        <MetricCard
          title="MOC Imbalance"
          value={spxMetrics.mocImbalance ? `$${formatMoc(Math.abs(spxMetrics.mocImbalance))}` : '—'}
          trend={spxMetrics.mocImbalance >= 0 ? 'up' : 'down'}
          tooltip={getMetricTooltip('MOC Imbalance')}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Main Tabs */}
        <div className="lg:col-span-3 overflow-visible">
          <FlexCard>
            <Tabs defaultValue="gamma">
              <TabsList className="flex w-full overflow-x-auto sm:grid sm:grid-cols-5">
                <TabsTrigger value="gamma" className="min-w-max sm:min-w-0">Gamma Levels</TabsTrigger>
                <TabsTrigger value="moc" className="min-w-max sm:min-w-0">MOC Imbalance</TabsTrigger>
                <TabsTrigger value="vanna" className="min-w-max sm:min-w-0">Vanna & Charm</TabsTrigger>
                <TabsTrigger value="volume" className="min-w-max sm:min-w-0">0DTE Volume</TabsTrigger>
                <TabsTrigger value="plan" className="min-w-max sm:min-w-0">EOD Trade Plan</TabsTrigger>
              </TabsList>

              <TabsContent value="gamma" className="space-y-4">
                <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm text-muted-foreground space-y-1.5">
                  <p className="font-medium text-foreground">What are Gamma Levels?</p>
                  <p>Gamma Exposure (GEX) shows where market makers have concentrated hedging positions at specific strike prices. These levels act as magnets or walls for price action.</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                      <span><strong className="text-emerald-600 dark:text-emerald-400">Bullish:</strong> Price above the Gamma Flip level, positive GEX = dealers suppress volatility, expect mean-reversion toward high-GEX strikes (support holds).</span>
                    </div>
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
                      <span><strong className="text-red-600 dark:text-red-400">Bearish:</strong> Price below Gamma Flip, negative GEX = dealers amplify moves, expect trend-following & volatility expansion toward resistance walls.</span>
                    </div>
                  </div>
                  <p className="text-xs">Look for: <strong>Gamma Flip</strong> (yellow) = key pivot, <strong>Support</strong> = price floor, <strong>Wall/Resistance</strong> = price ceiling.</p>
                </div>
                <div className="flex gap-2 text-sm">
                  <span className="px-2 py-1 rounded bg-emerald-500/20 text-emerald-600 dark:text-emerald-400">
                    Positive Gamma
                  </span>
                  <span className="px-2 py-1 rounded bg-red-500/20 text-red-600 dark:text-red-400">
                    Negative Gamma
                  </span>
                </div>
                <div className="rounded-md border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Strike</TableHead>
                        <TableHead>GEX Value</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>Distance</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {gammaLevels.map((row: { strike: number; gex: number; type: string; distance: number }) => (
                        <TableRow
                          key={row.strike}
                          className={
                            row.type === 'Flip'
                              ? 'bg-yellow-500/20 font-bold'
                              : row.gex > 0
                                ? 'bg-emerald-500/5'
                                : 'bg-red-500/5'
                          }
                        >
                          <TableCell className="font-mono">{row.strike}</TableCell>
                          <TableCell>{formatGex(row.gex)}</TableCell>
                          <TableCell>
                            {row.type === 'Flip' ? (
                              <Badge className="bg-yellow-500 text-yellow-950">Gamma Flip</Badge>
                            ) : (
                              row.type
                            )}
                          </TableCell>
                          <TableCell>{row.distance > 0 ? `+${row.distance}` : row.distance}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </TabsContent>

              <TabsContent value="moc" className="space-y-4">
                <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm text-muted-foreground space-y-1.5">
                  <p className="font-medium text-foreground">What is MOC Imbalance?</p>
                  <p>Market-On-Close (MOC) orders are large institutional orders executed at the closing price. The NYSE publishes the net imbalance at 3:50 PM ET. This is one of the strongest directional signals for the final 10 minutes of trading.</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                      <span><strong className="text-emerald-600 dark:text-emerald-400">Bullish:</strong> Buy imbalance (positive) means more buy orders at close. Expect a last-minute push higher. Larger imbalances (&gt;$500M) create stronger moves.</span>
                    </div>
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
                      <span><strong className="text-red-600 dark:text-red-400">Bearish:</strong> Sell imbalance (negative) means more sell orders at close. Expect a late-day selloff. Compare to Historical Avg — if current amount is 2x+ the average, the signal is stronger.</span>
                    </div>
                  </div>
                  <p className="text-xs"><strong>Key:</strong> Watch &quot;Predicted Impact&quot; — this estimates the % move SPX may make in the final minutes based on the imbalance size relative to historical patterns.</p>
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">
                    MOC released at 3:50 PM ET — Countdown: <strong>{countdownToMoc}</strong>
                  </p>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
                  <MetricCard title="Direction" value={mocData.direction} trend={mocData.direction === 'Buy' ? 'up' : 'down'} />
                  <MetricCard title="Amount" value={`$${formatMoc(Math.abs(mocData.amount))}`} />
                  <MetricCard title="Historical Avg" value={`$${formatMoc(Math.abs(mocData.historicalAvg))}`} />
                  <MetricCard title="Predicted Impact" value={`${mocData.predictedImpact > 0 ? '+' : ''}${mocData.predictedImpact}%`} />
                </div>
                <div className="p-4 rounded-lg border">
                  <h4 className="font-medium mb-2">Trade Signal</h4>
                  <Badge variant={mocData.tradeSignal === 'Bullish' ? 'default' : 'destructive'} className="text-sm">
                    {mocData.tradeSignal}
                  </Badge>
                </div>
              </TabsContent>

              <TabsContent value="vanna" className="space-y-4">
                <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm text-muted-foreground space-y-1.5">
                  <p className="font-medium text-foreground">What are Vanna & Charm?</p>
                  <p><strong>Vanna</strong> measures how delta changes with implied volatility. <strong>Charm</strong> measures how delta decays over time. Together they reveal the invisible force of market-maker hedging as options expire.</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                      <span><strong className="text-emerald-600 dark:text-emerald-400">Bullish:</strong> High positive Vanna + Active Charm Bid = dealers are forced to buy futures to stay hedged as IV drops and time decays. This creates a &quot;gravity pull&quot; upward, especially into the close.</span>
                    </div>
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
                      <span><strong className="text-red-600 dark:text-red-400">Bearish:</strong> Negative or low Vanna + Inactive Charm Bid = dealers selling into the close. Rising IV amplifies the selling. Watch for acceleration below key strikes.</span>
                    </div>
                  </div>
                  <p className="text-xs"><strong>Pro tip:</strong> Vanna is strongest when VIX is declining. Charm is strongest in the final 2 hours of 0DTE expiration. The combination creates the well-known &quot;afternoon drift.&quot;</p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                  <MetricCard
                    title="Vanna Level"
                    value={vannaCharm.vannaLevel.toFixed(2)}
                    trend={vannaCharm.vannaDirection === 'up' ? 'up' : 'down'}
                  />
                  <MetricCard
                    title="Charm Bid"
                    value={vannaCharm.charmBidActive ? 'Active' : 'Inactive'}
                    trend={vannaCharm.charmBidActive ? 'up' : 'down'}
                  />
                </div>
                <p className="text-sm text-muted-foreground">
                  Vanna exposure chart (mock) — Charm decay curve: dealer buying pressure as 0DTE expires.
                </p>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Strike</TableHead>
                        <TableHead>Vanna</TableHead>
                        <TableHead>Charm</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {vannaCharm.strikes.map((s: { strike: number; vanna: number; charm: number }) => (
                        <TableRow key={s.strike}>
                          <TableCell className="font-mono">{s.strike}</TableCell>
                          <TableCell>{s.vanna.toFixed(2)}</TableCell>
                          <TableCell>{s.charm.toFixed(2)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </TabsContent>

              <TabsContent value="volume" className="space-y-4">
                <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm text-muted-foreground space-y-1.5">
                  <p className="font-medium text-foreground">What is 0DTE Volume?</p>
                  <p>Zero-days-to-expiration option volume shows real-time call and put activity on contracts expiring today. These short-dated options have massive gamma, making volume patterns powerful directional signals.</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                      <span><strong className="text-emerald-600 dark:text-emerald-400">Bullish:</strong> Call/Put ratio &gt; 1.2, heavy call volume above current price, and no gamma squeeze signal = institutions positioning for upside. Watch for large block trades on OTM calls.</span>
                    </div>
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
                      <span><strong className="text-red-600 dark:text-red-400">Bearish:</strong> Put volume surging, C/P ratio &lt; 0.8, put-heavy strikes below current price = hedging/downside bets. A Gamma Squeeze signal (Yes) means dealers may chase price lower fast.</span>
                    </div>
                  </div>
                  <p className="text-xs"><strong>Heatmap:</strong> Brighter green = more activity at that strike. Look for clusters — they reveal where the &quot;battle&quot; is happening. <strong>Largest Trades</strong> show institutional-sized bets.</p>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
                  <MetricCard title="Call Volume" value={volume.callVolume?.toLocaleString() ?? '-'} />
                  <MetricCard title="Put Volume" value={volume.putVolume?.toLocaleString() ?? '-'} />
                  <MetricCard title="C/P Ratio" value={volume.ratio?.toFixed(2) ?? '-'} />
                  <MetricCard
                    title="Gamma Squeeze"
                    value={volume.gammaSqueezeSignal ? 'Yes' : 'No'}
                    trend={volume.gammaSqueezeSignal ? 'up' : 'neutral'}
                  />
                </div>
                <div>
                  <h4 className="font-medium mb-2">Volume by Strike (heatmap)</h4>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
                    {volume.volumeByStrike?.map((v: { strike: number; calls: number; puts: number }) => {
                      const total = v.calls + v.puts
                      const intensity = Math.min(100, (total / 150) * 100)
                      return (
                        <div
                          key={v.strike}
                          className="p-2 rounded text-center text-xs"
                          style={{ backgroundColor: `rgba(34, 197, 94, ${intensity / 100})` }}
                        >
                          <div className="font-mono font-medium">{v.strike}</div>
                          <div>C:{v.calls} P:{v.puts}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
                <div>
                  <h4 className="font-medium mb-2">Largest Trades</h4>
                  <div className="space-y-2">
                    {volume.largestTrades?.map((t: { strike: number; type: string; size: number; premium: number }, i: number) => (
                      <div key={i} className="flex justify-between text-sm p-2 rounded border">
                        <span className="font-mono">{t.strike}{t.type}</span>
                        <span>{t.size} @ ${(t.premium / t.size / 100).toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="plan" className="space-y-4">
                <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm text-muted-foreground space-y-1.5">
                  <p className="font-medium text-foreground">What is the EOD Trade Plan?</p>
                  <p>This is an AI-generated composite trade plan that synthesizes all signals — gamma levels, MOC imbalance, vanna/charm flows, and 0DTE volume — into a single actionable recommendation for the last hour of trading.</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                      <span><strong className="text-emerald-600 dark:text-emerald-400">LONG signal:</strong> Multiple bullish confirmations — positive GEX, MOC buy imbalance, active charm bid, heavy call volume. The plan will suggest call spreads or outright calls with defined risk.</span>
                    </div>
                    <div className="flex gap-2 items-start">
                      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
                      <span><strong className="text-red-600 dark:text-red-400">SHORT signal:</strong> Multiple bearish confirmations — negative GEX, MOC sell imbalance, inactive charm, put-heavy flow. The plan will suggest put spreads with a tight stop above the gamma flip.</span>
                    </div>
                  </div>
                  <p className="text-xs"><strong>Important:</strong> Always check the &quot;Signals&quot; list to see which factors are driving the recommendation. More signals aligned = higher confidence. Use &quot;Observe Only&quot; mode until you trust the system.</p>
                </div>
                <div className="rounded-lg border p-4 space-y-3">
                  <h4 className="font-semibold">AI Composite Trade Plan</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    <span className="text-muted-foreground">Direction</span>
                    <Badge variant={tradePlan.direction === 'LONG' ? 'default' : 'destructive'}>{tradePlan.direction}</Badge>
                    <span className="text-muted-foreground">Instrument</span>
                    <span>{tradePlan.instrument}</span>
                    <span className="text-muted-foreground">Strikes</span>
                    <span className="font-mono">{tradePlan.strikes}</span>
                    <span className="text-muted-foreground">Size</span>
                    <span>{tradePlan.size}</span>
                    <span className="text-muted-foreground">Entry</span>
                    <span>{tradePlan.entry}</span>
                    <span className="text-muted-foreground">Stop</span>
                    <span>{tradePlan.stop}</span>
                    <span className="text-muted-foreground">Target</span>
                    <span>{tradePlan.target}</span>
                  </div>
                  <div className="pt-2">
                    <p className="text-xs text-muted-foreground mb-1">Signals:</p>
                    <div className="flex flex-wrap gap-1">
                      {tradePlan.signals?.map((s: string, i: number) => (
                        <Badge key={i} variant="outline" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </div>
                  <Button
                    className="w-full mt-4"
                    onClick={() => executeMutation.mutate()}
                    disabled={executeMutation.isPending || tradingMode === 'observe'}
                  >
                    <Target className="h-4 w-4 mr-2" />
                    Execute Plan
                  </Button>
                </div>
              </TabsContent>
            </Tabs>
          </FlexCard>
        </div>

        {/* Agent Config Sidebar */}
        <FlexCard title="Agent Config" className="overflow-visible">
          <div className="space-y-4">
            <div>
              <Label className="text-sm">Instance</Label>
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
              <Zap className="h-4 w-4 mr-2" />
              Deploy 0DTE Agent
            </Button>
            <div>
              <Label className="text-sm">Trading Mode</Label>
              <Select value={tradingMode} onValueChange={(v) => setTradingMode(v as 'observe' | 'paper' | 'live')}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="observe">Observe Only</SelectItem>
                  <SelectItem value="paper">Paper</SelectItem>
                  <SelectItem value="live">Live</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-sm">Max Risk per Trade: {maxRiskPct}%</Label>
              <input
                type="range"
                min="0.5"
                max="3"
                step="0.5"
                value={maxRiskPct}
                onChange={(e) => setMaxRiskPct(parseFloat(e.target.value))}
                className="w-full mt-1"
              />
            </div>
            <div className="flex items-center justify-between">
              <Label className="text-sm">Auto-execute</Label>
              <Switch checked={autoExecute} onCheckedChange={setAutoExecute} />
            </div>
          </div>
        </FlexCard>
      </div>
    </div>
  )
}
