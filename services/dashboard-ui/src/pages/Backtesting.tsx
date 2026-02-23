import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Plus, Loader2, BarChart3, TrendingUp, TrendingDown, DollarSign, Activity, ChevronRight, X, RefreshCw } from 'lucide-react'

interface Source {
  id: string
  display_name: string
  source_type: string
}

interface Channel {
  id: string
  channel_identifier: string
  display_name: string
}

interface Account {
  id: string
  display_name: string
  broker_type: string
}

interface BacktestRun {
  id: string
  name: string | null
  data_source_id: string | null
  channel_id: string | null
  trading_account_id: string | null
  start_date: string
  end_date: string
  status: string
  summary: Record<string, unknown> | null
  error_message: string | null
  created_at: string
}

interface BacktestTrade {
  id: number
  trade_id: string
  ticker: string
  strike: number
  option_type: string
  action: string
  quantity: string
  entry_price: number
  exit_price: number | null
  entry_ts: string
  exit_ts: string | null
  exit_reason: string | null
  realized_pnl: number | null
  raw_message: string | null
}

const wizardSteps = [
  { label: 'Timeframe', key: 'timeframe' },
  { label: 'Data Source & Channel', key: 'source' },
  { label: 'Trading Account', key: 'account' },
  { label: 'Run', key: 'run' },
]

export default function Backtesting() {
  const qc = useQueryClient()
  const [wizardOpen, setWizardOpen] = useState(false)
  const [step, setStep] = useState(0)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [form, setForm] = useState({
    start_date: '',
    end_date: '',
    data_source_id: '',
    channel_id: '',
    trading_account_id: '',
    name: '',
  })

  const { data: runs, isLoading: runsLoading } = useQuery<BacktestRun[]>({
    queryKey: ['backtest'],
    queryFn: () => axios.get('/api/v1/backtest').then(r => r.data),
  })

  const { data: sources } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => axios.get('/api/v1/sources').then(r => r.data),
  })

  const { data: channels, isLoading: channelsLoading, refetch: refetchChannels } = useQuery<Channel[]>({
    queryKey: ['channels', form.data_source_id],
    queryFn: () => axios.get(`/api/v1/sources/${form.data_source_id}/channels`).then(r => r.data),
    enabled: !!form.data_source_id,
  })

  const [syncing, setSyncing] = useState(false)
  const handleSyncChannels = async () => {
    if (!form.data_source_id) return
    setSyncing(true)
    try {
      await axios.post(`/api/v1/sources/${form.data_source_id}/sync-channels`)
      await refetchChannels()
    } catch {
      setBtError('Failed to sync channels. Check that the data source has channel IDs configured.')
    }
    setSyncing(false)
  }

  const { data: accounts } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => axios.get('/api/v1/accounts').then(r => r.data),
  })

  const selectedRun = runs?.find(r => r.id === selectedRunId)

  const { data: tradesData } = useQuery<{ trades: BacktestTrade[] }>({
    queryKey: ['backtest', selectedRunId, 'trades'],
    queryFn: () => axios.get(`/api/v1/backtest/${selectedRunId}/trades`).then(r => r.data),
    enabled: !!selectedRunId,
  })

  const [btError, setBtError] = useState<string | null>(null)

  useEffect(() => {
    if (btError) {
      const t = setTimeout(() => setBtError(null), 5000)
      return () => clearTimeout(t)
    }
  }, [btError])

  const createMutation = useMutation({
    mutationFn: (payload: object) => axios.post('/api/v1/backtest', payload),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['backtest'] })
      setWizardOpen(false)
      setStep(0)
      setForm({ start_date: '', end_date: '', data_source_id: '', channel_id: '', trading_account_id: '', name: '' })
      setSelectedRunId(res.data.id)
    },
    onError: (err: unknown) => {
      const msg = axios.isAxiosError(err) && err.response?.data?.detail
        ? err.response.data.detail
        : 'Failed to create backtest. Please try again.'
      setBtError(msg)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => axios.delete(`/api/v1/backtest/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['backtest'] })
      if (selectedRunId) setSelectedRunId(null)
    },
    onError: () => setBtError('Failed to delete backtest run.'),
  })

  const handleDeleteRun = (id: string, name: string | null) => {
    if (window.confirm(`Delete backtest "${name || id.slice(0, 8)}"? This cannot be undone.`)) {
      deleteMutation.mutate(id)
    }
  }

  const handleRun = () => {
    const start = form.start_date ? `${form.start_date}T00:00:00Z` : ''
    const end = form.end_date ? `${form.end_date}T23:59:59Z` : ''
    createMutation.mutate({
      start_date: start,
      end_date: end,
      data_source_id: form.data_source_id,
      channel_id: form.channel_id,
      trading_account_id: form.trading_account_id,
      name: form.name || undefined,
    })
  }

  const canProceed = () => {
    if (step === 0) return form.start_date && form.end_date && form.start_date <= form.end_date
    if (step === 1) return form.data_source_id && form.channel_id
    if (step === 2) return form.trading_account_id
    return true
  }

  const summary = selectedRun?.summary as Record<string, number> | undefined
  const trades = tradesData?.trades ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Simulate trading signals from Discord history against your account config
        </p>
        <Dialog open={wizardOpen} onOpenChange={setWizardOpen}>
          <DialogTrigger asChild>
            <Button onClick={() => { setStep(0); setForm({ start_date: '', end_date: '', data_source_id: '', channel_id: '', trading_account_id: '', name: '' }) }}>
              <Plus className="mr-2 h-4 w-4" /> New Backtest
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>New Backtest</DialogTitle>
              <DialogDescription>Configure and run a backtest over historical Discord messages.</DialogDescription>
            </DialogHeader>
            <div className="space-y-6 py-4">
              <div className="flex gap-2">
                {wizardSteps.map((s, i) => (
                  <div key={s.key} className="flex items-center gap-1">
                    <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium ${i <= step ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>
                      {i + 1}
                    </div>
                    {i < wizardSteps.length - 1 && <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                  </div>
                ))}
              </div>

              {step === 0 && (
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label>Start Date</Label>
                    <Input type="date" value={form.start_date} onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))} />
                  </div>
                  <div className="grid gap-2">
                    <Label>End Date</Label>
                    <Input type="date" value={form.end_date} onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))} />
                  </div>
                </div>
              )}

              {step === 1 && (
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label>Data Source</Label>
                    <Select value={form.data_source_id} onValueChange={v => setForm(f => ({ ...f, data_source_id: v, channel_id: '' }))}>
                      <SelectTrigger><SelectValue placeholder="Select source" /></SelectTrigger>
                      <SelectContent>
                        {sources?.map(s => <SelectItem key={s.id} value={s.id}>{s.display_name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-2">
                    <Label>Channel</Label>
                    {channelsLoading ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                        <Loader2 className="h-4 w-4 animate-spin" /> Loading channels...
                      </div>
                    ) : channels && channels.length > 0 ? (
                      <Select value={form.channel_id} onValueChange={v => setForm(f => ({ ...f, channel_id: v }))} disabled={!form.data_source_id}>
                        <SelectTrigger><SelectValue placeholder="Select channel" /></SelectTrigger>
                        <SelectContent>
                          {channels.map(c => <SelectItem key={c.id} value={c.id}>{c.display_name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    ) : form.data_source_id ? (
                      <div className="flex items-center gap-2">
                        <p className="text-sm text-muted-foreground">No channels found.</p>
                        <Button type="button" variant="outline" size="sm" onClick={handleSyncChannels} disabled={syncing}>
                          {syncing ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />}
                          Sync Channels
                        </Button>
                      </div>
                    ) : (
                      <Select disabled><SelectTrigger><SelectValue placeholder="Select a source first" /></SelectTrigger><SelectContent /></Select>
                    )}
                  </div>
                </div>
              )}

              {step === 2 && (
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label>Trading Account</Label>
                    <Select value={form.trading_account_id} onValueChange={v => setForm(f => ({ ...f, trading_account_id: v }))}>
                      <SelectTrigger><SelectValue placeholder="Select account" /></SelectTrigger>
                      <SelectContent>
                        {accounts?.map(a => <SelectItem key={a.id} value={a.id}>{a.display_name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              )}

              {step === 3 && (
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label>Name (optional)</Label>
                    <Input placeholder="e.g. SPX Weekly Jan 2025" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
                  </div>
                  <p className="text-sm text-muted-foreground">Click Run to fetch Discord messages and simulate trades.</p>
                </div>
              )}
            </div>

            <DialogFooter>
              {step > 0 && <Button variant="outline" onClick={() => setStep(s => s - 1)}>Back</Button>}
              {step < 3 ? (
                <Button onClick={() => setStep(s => s + 1)} disabled={!canProceed()}>Next</Button>
              ) : (
                <Button onClick={handleRun} disabled={!canProceed() || createMutation.isPending}>
                  {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Run Backtest
                </Button>
              )}
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {btError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-400 flex items-center justify-between">
          <span>{btError}</span>
          <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setBtError(null)}>Dismiss</Button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5" /> Backtest Runs
            </CardTitle>
          </CardHeader>
          <CardContent>
            {runsLoading ? (
              <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
            ) : !runs?.length ? (
              <p className="text-center text-muted-foreground py-8">No backtests yet. Click New Backtest to start.</p>
            ) : (
              <div className="space-y-2 max-h-[320px] overflow-y-auto">
                {runs.map(r => (
                  <div
                    key={r.id}
                    onClick={() => setSelectedRunId(r.id)}
                    className={`flex items-center justify-between rounded-lg border p-3 cursor-pointer transition-colors ${selectedRunId === r.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/50'}`}
                  >
                    <div>
                      <p className="font-medium">{r.name || `${r.start_date?.slice(0, 10)} → ${r.end_date?.slice(0, 10)}`}</p>
                      <p className="text-xs text-muted-foreground">{new Date(r.created_at).toLocaleString()}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={r.status === 'completed' ? 'default' : r.status === 'failed' ? 'destructive' : 'secondary'}>
                        {r.status}
                      </Badge>
                      {r.summary && (
                        <span className={`text-sm font-medium ${(r.summary as Record<string, number>).total_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          ${((r.summary as Record<string, number>).total_pnl ?? 0).toFixed(0)}
                        </span>
                      )}
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={e => { e.stopPropagation(); handleDeleteRun(r.id, r.name) }}>
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {selectedRun ? (
          <Card>
            <CardHeader>
              <CardTitle>Results</CardTitle>
              <CardDescription>{selectedRun.name || `Run ${selectedRun.id.slice(0, 8)}`}</CardDescription>
            </CardHeader>
            <CardContent>
              {selectedRun.status === 'failed' && (
                <p className="text-destructive text-sm mb-4">{selectedRun.error_message}</p>
              )}
              {summary && (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Total Trades</p>
                      <p className="text-lg font-semibold">{summary.total_trades ?? 0}</p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Win Rate</p>
                      <p className="text-lg font-semibold">{summary.win_rate_pct ?? 0}%</p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Total P&L</p>
                      <p className={`text-lg font-semibold ${(summary.total_pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        ${(summary.total_pnl ?? 0).toFixed(2)}
                      </p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Avg Win</p>
                      <p className="text-lg font-semibold text-green-600">${(summary.avg_win ?? 0).toFixed(2)}</p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Avg Loss</p>
                      <p className="text-lg font-semibold text-red-600">${(summary.avg_loss ?? 0).toFixed(2)}</p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Max Drawdown</p>
                      <p className="text-lg font-semibold">${(summary.max_drawdown ?? 0).toFixed(2)}</p>
                    </div>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium mb-2">Trades</h4>
                    <div className="rounded-md border max-h-[300px] overflow-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Ticker</TableHead>
                            <TableHead>Action</TableHead>
                            <TableHead>Entry</TableHead>
                            <TableHead>Exit</TableHead>
                            <TableHead>P&L</TableHead>
                            <TableHead>Reason</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {trades.map(t => (
                            <TableRow key={t.id}>
                              <TableCell className="font-mono">{t.ticker} {t.strike}{t.option_type === 'CALL' ? 'C' : 'P'}</TableCell>
                              <TableCell>{t.action}</TableCell>
                              <TableCell>${t.entry_price.toFixed(2)}</TableCell>
                              <TableCell>{t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : '—'}</TableCell>
                              <TableCell className={t.realized_pnl != null ? (t.realized_pnl >= 0 ? 'text-green-600' : 'text-red-600') : ''}>
                                {t.realized_pnl != null ? `$${t.realized_pnl.toFixed(2)}` : '—'}
                              </TableCell>
                              <TableCell className="text-xs">{t.exit_reason ?? '—'}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                </>
              )}
              {!summary && selectedRun.status === 'completed' && (
                <p className="text-muted-foreground">No summary available.</p>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
              <Activity className="h-12 w-12 mb-4 opacity-50" />
              <p>Select a backtest run to view results</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
