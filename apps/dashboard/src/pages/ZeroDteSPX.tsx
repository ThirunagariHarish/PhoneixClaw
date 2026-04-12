/**
 * 0DTE SPX Command Center — EOD SPX/SPY trading dashboard for 0DTE options.
 * Phoenix v2.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { getMetricTooltip } from '@/lib/metricTooltips'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts'

const EMPTY_SPX = { price: 0, change: 0, changePct: 0 }
const EMPTY_METRICS = {
  vix: 0,
  gexNet: 0,
  dealerGammaZone: 'Neutral',
  zeroDteVolume: 0,
  putCallRatio: 0,
  mocImbalance: 0,
}
const EMPTY_GAMMA_LEVELS: Array<{ strike: number; gex: number; type: string; distance: number }> = []
const EMPTY_MOC = {
  direction: 'Neutral',
  amount: 0,
  historicalAvg: 0,
  predictedImpact: 0,
  tradeSignal: 'Neutral',
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
  direction: 'NEUTRAL',
  instrument: 'SPX 0DTE Options',
  strikes: 'Awaiting data',
  size: 'N/A',
  entry: 'Awaiting data',
  stop: 'N/A',
  target: 'N/A',
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
  const [settingsSaved, setSettingsSaved] = useState(false)
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
        const data = res.data
        // Z2: Ensure we always return an array
        if (Array.isArray(data)) return data
        // If backend returns dict format, transform it
        if (data && typeof data === 'object' && !Array.isArray(data)) {
          const gexByStrike = data.gex_by_strike || data.gexByStrike || {}
          return Object.entries(gexByStrike).map(([strike, gex]) => ({
            strike: parseFloat(strike),
            gex: typeof gex === 'number' ? gex : parseFloat(String(gex)) || 0,
            type: (typeof gex === 'number' ? gex : 0) > 0 ? 'Support' : 'Resistance',
            distance: 0,
          }))
        }
        return EMPTY_GAMMA_LEVELS
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
        const d = res.data ?? {}
        // Z3: Normalize field names from backend
        return {
          direction: d.direction ?? 'Neutral',
          amount: d.amount ?? d.net_premium ?? 0,
          historicalAvg: d.historicalAvg ?? d.historical_avg ?? 0,
          predictedImpact: d.predictedImpact ?? d.predicted_impact ?? 0,
          tradeSignal: d.tradeSignal ?? d.trade_signal ?? 'Neutral',
          releaseTime: d.releaseTime ?? d.release_time ?? '15:50',
        }
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
        const d = res.data ?? {}
        return {
          vannaLevel: d.vannaLevel ?? 0,
          vannaDirection: d.vannaDirection ?? 'neutral',
          charmBidActive: d.charmBidActive ?? false,
          strikes: (Array.isArray(d.strikes) ? d.strikes : []).map((s: Record<string, unknown>) => ({
            strike: s.strike ?? 0,
            vanna: s.vanna ?? s.vanna_est ?? 0,
            charm: s.charm ?? 0,
          })),
        }
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
        const d = res.data ?? {}
        return {
          callVolume: d.callVolume ?? d.call_volume ?? 0,
          putVolume: d.putVolume ?? d.put_volume ?? 0,
          ratio: d.ratio ?? 0,
          // Z4: Normalize calls/puts field names
          volumeByStrike: (Array.isArray(d.volumeByStrike) ? d.volumeByStrike : []).map((v: Record<string, unknown>) => ({
            strike: v.strike ?? 0,
            calls: v.calls ?? v.call_volume ?? 0,
            puts: v.puts ?? v.put_volume ?? 0,
          })),
          largestTrades: (Array.isArray(d.largestTrades) ? d.largestTrades : []).map((t: Record<string, unknown>) => ({
            strike: t.strike ?? 0,
            type: t.type ?? t.option_type ?? '',
            size: t.size ?? t.volume ?? 0,
            premium: t.premium ?? 0,
          })),
          gammaSqueezeSignal: d.gammaSqueezeSignal ?? d.gamma_squeeze_signal ?? false,
        }
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
        const d = res.data ?? {}
        // Z5: Normalize trade plan response
        const rawSignals = d.signals ?? []
        // signals could be array of strings or array of objects
        const signals: string[] = rawSignals.map((s: unknown) =>
          typeof s === 'string' ? s : (s && typeof s === 'object' && 'source' in (s as Record<string, unknown>))
            ? `${(s as Record<string, unknown>).source}: ${(s as Record<string, unknown>).signal}`
            : String(s)
        )
        return {
          direction: d.direction ?? 'NEUTRAL',
          instrument: d.instrument ?? 'SPX 0DTE Options',
          strikes: typeof d.strikes === 'string' ? d.strikes
            : Array.isArray(d.strikes) ? d.strikes.join(', ')
            : 'Awaiting data',
          size: d.size ?? 'N/A',
          entry: d.entry ?? 'Awaiting data',
          stop: d.stop ?? 'N/A',
          target: d.target ?? 'N/A',
          signals,
        }
      } catch {
        return EMPTY_TRADE_PLAN
      }
    },
    refetchInterval: 60000,
  })

  // Z8: Load saved settings on mount
  useQuery({
    queryKey: ['zero-dte', 'settings'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/zero-dte/settings')
        const d = res.data ?? {}
        if (d.trading_mode) setTradingMode(d.trading_mode as 'observe' | 'paper' | 'live')
        if (d.max_risk_pct) setMaxRiskPct(d.max_risk_pct)
        if (d.auto_execute !== undefined) setAutoExecute(d.auto_execute)
        return d
      } catch {
        return {}
      }
    },
    staleTime: Infinity, // Load once
  })

  // Z8: Save settings mutation
  const saveSettingsMutation = useMutation({
    mutationFn: async () => {
      await api.post('/api/v2/zero-dte/settings', {
        trading_mode: tradingMode,
        max_risk_pct: maxRiskPct,
        auto_execute: autoExecute,
      })
    },
    onSuccess: () => {
      setSettingsSaved(true)
      setTimeout(() => setSettingsSaved(false), 2000)
    },
  })

  const formatGex = (v: number) => {
    const n = v ?? 0
    return n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(0)}M` : `${(n / 1e3).toFixed(0)}K`
  }
  const formatMoc = (v: number) => `${((v ?? 0) / 1e6).toFixed(0)}M`

  // Z6: Prepare GEX chart data (sorted by strike)
  const gexChartData = (Array.isArray(gammaLevels) ? gammaLevels : [])
    .slice()
    .sort((a, b) => a.strike - b.strike)
    .map((row) => ({
      strike: row.strike,
      gex: row.gex ?? 0,
      type: row.type,
    }))

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Activity} title="0DTE SPX Command Center" description="Zero days to expiration SPX options flow and signals">
        <div className="flex flex-wrap items-center gap-2 sm:gap-4 text-muted-foreground">
          <span className="font-mono text-base sm:text-lg font-semibold text-foreground">
            SPX {spxData.price ? spxData.price.toLocaleString() : '--'}
          </span>
          <span className={(spxData.change ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-600'}>
            {(spxData.change ?? 0) >= 0 ? '+' : ''}{spxData.change ?? 0} ({spxData.changePct ?? 0}%)
          </span>
          <span className="flex items-center gap-1">
            <Timer className="h-4 w-4" />
            Close in {countdownToClose}
          </span>
        </div>
      </PageHeader>

      {/* Top Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2 sm:gap-3">
        <MetricCard title="SPX Price" value={spxData.price ? spxData.price.toLocaleString() : '--'} tooltip={getMetricTooltip('SPX Price')} />
        <MetricCard title="VIX" value={spxMetrics.vix || '--'} tooltip={getMetricTooltip('VIX')} />
        <MetricCard
          title="GEX Net"
          value={spxMetrics.gexNet ? formatGex(spxMetrics.gexNet) : '--'}
          trend={(spxMetrics.gexNet ?? 0) >= 0 ? 'up' : 'down'}
          tooltip={getMetricTooltip('GEX Net')}
        />
        <MetricCard
          title="Dealer Gamma Zone"
          value={spxMetrics.dealerGammaZone ?? '--'}
          trend={spxMetrics.dealerGammaZone === 'Positive' ? 'up' : 'down'}
          tooltip={getMetricTooltip('Dealer Gamma Zone')}
        />
        <MetricCard title="0DTE Volume" value={spxMetrics.zeroDteVolume ? formatGex(spxMetrics.zeroDteVolume) : '--'} tooltip={getMetricTooltip('ODTE Volume')} />
        <MetricCard title="Put/Call Ratio" value={spxMetrics.putCallRatio ? (spxMetrics.putCallRatio ?? 0).toFixed(2) : '--'} tooltip={getMetricTooltip('Put/Call Ratio')} />
        <MetricCard
          title="MOC Imbalance"
          value={spxMetrics.mocImbalance ? `$${formatMoc(Math.abs(spxMetrics.mocImbalance))}` : '--'}
          trend={(spxMetrics.mocImbalance ?? 0) >= 0 ? 'up' : 'down'}
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

                {/* Z6: GEX Bar Chart */}
                {gexChartData.length > 0 && (
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={gexChartData} layout="horizontal" margin={{ top: 5, right: 20, left: 20, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                        <XAxis dataKey="strike" tick={{ fontSize: 11 }} className="fill-muted-foreground" />
                        <YAxis tick={{ fontSize: 11 }} className="fill-muted-foreground" tickFormatter={(v) => formatGex(v)} />
                        <RechartsTooltip
                          contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }}
                          labelStyle={{ color: 'hsl(var(--foreground))' }}
                          formatter={(value: number) => [formatGex(value), 'GEX']}
                        />
                        <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
                        <Bar dataKey="gex" radius={[2, 2, 0, 0]}>
                          {gexChartData.map((entry, index) => (
                            <Cell
                              key={`cell-${index}`}
                              fill={entry.type === 'Flip' ? '#eab308' : entry.gex >= 0 ? '#22c55e' : '#ef4444'}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                <div className="flex gap-2 text-sm">
                  <span className="px-2 py-1 rounded bg-emerald-500/20 text-emerald-600 dark:text-emerald-400">
                    Positive Gamma
                  </span>
                  <span className="px-2 py-1 rounded bg-red-500/20 text-red-600 dark:text-red-400">
                    Negative Gamma
                  </span>
                  <span className="px-2 py-1 rounded bg-yellow-500/20 text-yellow-600 dark:text-yellow-400">
                    Gamma Flip
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
                      {(Array.isArray(gammaLevels) ? gammaLevels : []).map((row: { strike: number; gex: number; type: string; distance: number }) => (
                        <TableRow
                          key={row.strike}
                          className={
                            row.type === 'Flip'
                              ? 'bg-yellow-500/20 font-bold'
                              : (row.gex ?? 0) > 0
                                ? 'bg-emerald-500/5'
                                : 'bg-red-500/5'
                          }
                        >
                          <TableCell className="font-mono">{row.strike}</TableCell>
                          <TableCell>{formatGex(row.gex ?? 0)}</TableCell>
                          <TableCell>
                            {row.type === 'Flip' ? (
                              <Badge className="bg-yellow-500 text-yellow-950">Gamma Flip</Badge>
                            ) : (
                              row.type ?? '--'
                            )}
                          </TableCell>
                          <TableCell>{(row.distance ?? 0) > 0 ? `+${row.distance}` : row.distance ?? 0}</TableCell>
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
                  <MetricCard title="Direction" value={mocData.direction ?? '--'} trend={mocData.direction === 'Buy' ? 'up' : 'down'} />
                  <MetricCard title="Amount" value={`$${formatMoc(Math.abs(mocData.amount ?? 0))}`} />
                  <MetricCard title="Historical Avg" value={`$${formatMoc(Math.abs(mocData.historicalAvg ?? 0))}`} />
                  <MetricCard title="Predicted Impact" value={`${(mocData.predictedImpact ?? 0) > 0 ? '+' : ''}${mocData.predictedImpact ?? 0}%`} />
                </div>
                <div className="p-4 rounded-lg border">
                  <h4 className="font-medium mb-2">Trade Signal</h4>
                  <Badge variant={mocData.tradeSignal === 'Bullish' ? 'default' : 'destructive'} className="text-sm">
                    {mocData.tradeSignal ?? '--'}
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
                    value={(vannaCharm.vannaLevel ?? 0).toFixed(2)}
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
                      {(Array.isArray(vannaCharm.strikes) ? vannaCharm.strikes : []).map((s: { strike: number; vanna: number; charm: number }) => (
                        <TableRow key={s.strike}>
                          <TableCell className="font-mono">{s.strike ?? 0}</TableCell>
                          <TableCell>{(s.vanna ?? 0).toFixed(2)}</TableCell>
                          <TableCell>{(s.charm ?? 0).toFixed(2)}</TableCell>
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
                  <MetricCard title="Call Volume" value={(volume.callVolume ?? 0).toLocaleString()} />
                  <MetricCard title="Put Volume" value={(volume.putVolume ?? 0).toLocaleString()} />
                  <MetricCard title="C/P Ratio" value={(volume.ratio ?? 0).toFixed(2)} />
                  <MetricCard
                    title="Gamma Squeeze"
                    value={volume.gammaSqueezeSignal ? 'Yes' : 'No'}
                    trend={volume.gammaSqueezeSignal ? 'up' : 'neutral'}
                  />
                </div>
                <div>
                  <h4 className="font-medium mb-2">Volume by Strike (heatmap)</h4>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
                    {(Array.isArray(volume.volumeByStrike) ? volume.volumeByStrike : []).map((v: { strike: number; calls: number; puts: number }) => {
                      const total = (v.calls ?? 0) + (v.puts ?? 0)
                      const intensity = Math.min(100, (total / 150) * 100)
                      return (
                        <div
                          key={v.strike}
                          className="p-2 rounded text-center text-xs"
                          style={{ backgroundColor: `rgba(34, 197, 94, ${intensity / 100})` }}
                        >
                          <div className="font-mono font-medium">{v.strike}</div>
                          <div>C:{v.calls ?? 0} P:{v.puts ?? 0}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
                <div>
                  <h4 className="font-medium mb-2">Largest Trades</h4>
                  <div className="space-y-2">
                    {(Array.isArray(volume.largestTrades) ? volume.largestTrades : []).map((t: { strike: number; type: string; size: number; premium: number }, i: number) => (
                      <div key={i} className="flex justify-between text-sm p-2 rounded border">
                        <span className="font-mono">{t.strike ?? 0}{t.type ?? ''}</span>
                        <span>{t.size ?? 0} @ ${((t.size ?? 0) ? ((t.premium ?? 0) / (t.size ?? 1) / 100) : 0).toFixed(2)}</span>
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
                    <Badge variant={tradePlan.direction === 'LONG' ? 'default' : 'destructive'}>{tradePlan.direction ?? '--'}</Badge>
                    <span className="text-muted-foreground">Instrument</span>
                    <span>{tradePlan.instrument ?? '--'}</span>
                    <span className="text-muted-foreground">Strikes</span>
                    <span className="font-mono">{tradePlan.strikes ?? '--'}</span>
                    <span className="text-muted-foreground">Size</span>
                    <span>{tradePlan.size ?? '--'}</span>
                    <span className="text-muted-foreground">Entry</span>
                    <span>{tradePlan.entry ?? '--'}</span>
                    <span className="text-muted-foreground">Stop</span>
                    <span>{tradePlan.stop ?? '--'}</span>
                    <span className="text-muted-foreground">Target</span>
                    <span>{tradePlan.target ?? '--'}</span>
                  </div>
                  <div className="pt-2">
                    <p className="text-xs text-muted-foreground mb-1">Signals:</p>
                    <div className="flex flex-wrap gap-1">
                      {(Array.isArray(tradePlan.signals) ? tradePlan.signals : []).map((s: string, i: number) => (
                        <Badge key={i} variant="outline" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </div>
                  {/* Z7: Execute button disabled with tooltip when not wired */}
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="w-full inline-block">
                          <Button
                            className="w-full mt-4"
                            disabled={tradingMode === 'observe'}
                          >
                            <Target className="h-4 w-4 mr-2" />
                            {tradingMode === 'observe' ? 'Observe Mode (no execution)' : 'Execute Plan (Coming Soon)'}
                          </Button>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        {tradingMode === 'observe'
                          ? <p>Switch to Paper or Live mode to enable execution</p>
                          : <p>Coming soon -- auto-execution is under development</p>
                        }
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
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
                  {(instances || []).map((inst) => (
                    <SelectItem key={inst.id} value={inst.id}>{inst.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {/* Z7: Deploy button with "Coming soon" tooltip */}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="w-full inline-block">
                    <Button
                      className="w-full"
                      disabled
                    >
                      <Zap className="h-4 w-4 mr-2" />
                      Deploy 0DTE Agent
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Coming soon -- agent deployment is under development</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
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
            {/* Z8: Save settings button */}
            <Button
              variant="outline"
              className="w-full"
              onClick={() => saveSettingsMutation.mutate()}
              disabled={saveSettingsMutation.isPending}
            >
              {settingsSaved ? 'Settings Saved' : 'Save Settings'}
            </Button>
          </div>
        </FlexCard>
      </div>
    </div>
  )
}
