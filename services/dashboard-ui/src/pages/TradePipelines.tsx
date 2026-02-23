import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Plus, Loader2, Play, Square, Trash2, RefreshCw, Workflow,
  Database, Hash, Wallet, AlertCircle, CheckCircle2, XCircle, ChevronRight,
} from 'lucide-react'

interface Source {
  id: string
  display_name: string
  source_type: string
  connection_status: string
  enabled: boolean
}

interface Channel {
  id: string
  channel_identifier: string
  display_name: string
  guild_id?: string
  guild_name?: string
  enabled: boolean
}

interface Account {
  id: string
  display_name: string
  broker_type: string
  paper_mode: boolean
}

interface Pipeline {
  id: string
  name: string
  data_source_id: string
  data_source_name: string | null
  channel_id: string
  channel_name: string | null
  channel_identifier: string | null
  trading_account_id: string
  trading_account_name: string | null
  enabled: boolean
  status: string
  error_message: string | null
  auto_approve: boolean
  paper_mode: boolean
  last_message_at: string | null
  messages_count: number
  trades_count: number
  created_at: string
  updated_at: string
}

const STATUS_CONFIG: Record<string, { color: string; icon: React.ElementType }> = {
  CONNECTED: { color: 'bg-green-500', icon: CheckCircle2 },
  CONNECTING: { color: 'bg-yellow-500 animate-pulse', icon: Loader2 },
  RUNNING: { color: 'bg-green-500', icon: CheckCircle2 },
  STOPPED: { color: 'bg-gray-400', icon: Square },
  ERROR: { color: 'bg-red-500', icon: XCircle },
  DISCONNECTED: { color: 'bg-gray-400', icon: Square },
}

export default function TradePipelines() {
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [step, setStep] = useState(1)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [form, setForm] = useState({
    name: '',
    data_source_id: '',
    channel_id: '',
    trading_account_id: '',
    auto_approve: true,
    paper_mode: false,
  })

  useEffect(() => {
    if (error) {
      const t = setTimeout(() => setError(null), 5000)
      return () => clearTimeout(t)
    }
  }, [error])

  const { data: pipelines, isLoading, refetch } = useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: () => axios.get('/api/v1/pipelines').then(r => r.data),
    refetchInterval: 10_000,
  })

  const { data: sources } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => axios.get('/api/v1/sources').then(r => r.data),
  })

  const { data: channels, isLoading: channelsLoading, refetch: refetchChannels } = useQuery<Channel[]>({
    queryKey: ['pipeline-channels', form.data_source_id],
    queryFn: () => axios.get(`/api/v1/sources/${form.data_source_id}/channels`).then(r => r.data),
    enabled: !!form.data_source_id,
  })

  const { data: accounts } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => axios.get('/api/v1/accounts').then(r => r.data),
  })

  const createMutation = useMutation({
    mutationFn: (data: typeof form) => axios.post('/api/v1/pipelines', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      resetDialog()
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Failed to create pipeline')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => axios.delete(`/api/v1/pipelines/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pipelines'] }),
  })

  const startMutation = useMutation({
    mutationFn: (id: string) => axios.post(`/api/v1/pipelines/${id}/start`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pipelines'] }),
  })

  const stopMutation = useMutation({
    mutationFn: (id: string) => axios.post(`/api/v1/pipelines/${id}/stop`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pipelines'] }),
  })

  const handleSyncChannels = async () => {
    if (!form.data_source_id) return
    setSyncing(true)
    try {
      await axios.post(`/api/v1/sources/${form.data_source_id}/sync-channels`)
      await refetchChannels()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to discover channels')
    }
    setSyncing(false)
  }

  const resetDialog = () => {
    setDialogOpen(false)
    setStep(1)
    setForm({ name: '', data_source_id: '', channel_id: '', trading_account_id: '', auto_approve: true, paper_mode: false })
    setError(null)
  }

  const handleCreate = () => {
    if (!form.name || !form.data_source_id || !form.channel_id || !form.trading_account_id) {
      setError('Please fill in all fields')
      return
    }
    createMutation.mutate(form)
  }

  const selectedChannel = channels?.find(c => c.id === form.channel_id)
  const selectedSource = sources?.find(s => s.id === form.data_source_id)

  const groupedChannels = channels?.reduce<Record<string, Channel[]>>((acc, ch) => {
    const guild = ch.guild_name || 'Unknown Server'
    if (!acc[guild]) acc[guild] = []
    acc[guild].push(ch)
    return acc
  }, {}) || {}

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Trade Pipelines</h2>
          <p className="text-muted-foreground">
            Connect Discord channels to trading accounts for real-time trade execution
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="mr-1 h-4 w-4" /> Refresh
          </Button>
          <Dialog open={dialogOpen} onOpenChange={v => { if (!v) resetDialog(); else setDialogOpen(true) }}>
            <DialogTrigger asChild>
              <Button><Plus className="mr-1 h-4 w-4" /> New Pipeline</Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
              <DialogHeader>
                <DialogTitle>Create Trade Pipeline</DialogTitle>
                <DialogDescription>
                  {step === 1 && 'Step 1: Select your Discord data source'}
                  {step === 2 && 'Step 2: Choose a channel to monitor'}
                  {step === 3 && 'Step 3: Configure pipeline and trading account'}
                </DialogDescription>
              </DialogHeader>

              {error && (
                <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-400">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {error}
                </div>
              )}

              <div className="flex gap-2 mb-4">
                {[1, 2, 3].map(s => (
                  <div key={s} className={`flex-1 h-1.5 rounded-full transition-colors ${s <= step ? 'bg-primary' : 'bg-muted'}`} />
                ))}
              </div>

              {step === 1 && (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Data Source</Label>
                    <Select
                      value={form.data_source_id}
                      onValueChange={v => setForm(f => ({ ...f, data_source_id: v, channel_id: '' }))}
                    >
                      <SelectTrigger><SelectValue placeholder="Select a Discord connection" /></SelectTrigger>
                      <SelectContent>
                        {sources?.filter(s => s.source_type === 'discord').map(s => (
                          <SelectItem key={s.id} value={s.id}>
                            <div className="flex items-center gap-2">
                              <Database className="h-4 w-4 text-muted-foreground" />
                              {s.display_name}
                              <Badge variant={s.connection_status === 'CONNECTED' ? 'default' : 'secondary'} className="text-[10px] ml-1">
                                {s.connection_status}
                              </Badge>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {!sources?.filter(s => s.source_type === 'discord').length && (
                    <p className="text-sm text-muted-foreground">
                      No Discord data sources found. Create one in the Data Sources page first.
                    </p>
                  )}
                </div>
              )}

              {step === 2 && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <Label>Channel</Label>
                    <Button
                      type="button" variant="outline" size="sm"
                      onClick={handleSyncChannels} disabled={syncing}
                    >
                      {syncing ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />}
                      Discover Channels
                    </Button>
                  </div>

                  {channelsLoading ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground py-4 justify-center">
                      <Loader2 className="h-4 w-4 animate-spin" /> Loading channels...
                    </div>
                  ) : channels && channels.length > 0 ? (
                    <div className="max-h-64 overflow-y-auto space-y-3 pr-1">
                      {Object.entries(groupedChannels).map(([guild, chs]) => (
                        <div key={guild}>
                          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">{guild}</p>
                          <div className="space-y-1">
                            {chs.map(ch => (
                              <button
                                key={ch.id}
                                type="button"
                                onClick={() => setForm(f => ({ ...f, channel_id: ch.id }))}
                                className={`w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm text-left transition-colors ${
                                  form.channel_id === ch.id
                                    ? 'bg-primary/10 text-primary ring-1 ring-primary/30'
                                    : 'hover:bg-accent text-foreground'
                                }`}
                              >
                                <Hash className="h-4 w-4 text-muted-foreground shrink-0" />
                                <span className="truncate">{ch.display_name.replace(/^.+\/ #/, '')}</span>
                                <span className="text-[10px] text-muted-foreground ml-auto shrink-0">{ch.channel_identifier}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-6 space-y-2">
                      <Hash className="h-8 w-8 text-muted-foreground mx-auto" />
                      <p className="text-sm text-muted-foreground">
                        No channels found. Click "Discover Channels" to fetch channels from Discord.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {step === 3 && (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Pipeline Name</Label>
                    <Input
                      placeholder={selectedChannel ? `${selectedChannel.display_name.replace(/^.+\/ #/, '')} Pipeline` : 'My Pipeline'}
                      value={form.name}
                      onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Trading Account</Label>
                    <Select
                      value={form.trading_account_id}
                      onValueChange={v => setForm(f => ({ ...f, trading_account_id: v }))}
                    >
                      <SelectTrigger><SelectValue placeholder="Select a trading account" /></SelectTrigger>
                      <SelectContent>
                        {accounts?.map(a => (
                          <SelectItem key={a.id} value={a.id}>
                            <div className="flex items-center gap-2">
                              <Wallet className="h-4 w-4 text-muted-foreground" />
                              {a.display_name}
                              {a.paper_mode && <Badge variant="outline" className="text-[10px]">Paper</Badge>}
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="flex items-center justify-between rounded-md border p-3">
                    <div>
                      <p className="text-sm font-medium">Auto-Approve Trades</p>
                      <p className="text-xs text-muted-foreground">Automatically approve parsed trades without manual review</p>
                    </div>
                    <Switch checked={form.auto_approve} onCheckedChange={v => setForm(f => ({ ...f, auto_approve: v }))} />
                  </div>

                  <div className="flex items-center justify-between rounded-md border p-3">
                    <div>
                      <p className="text-sm font-medium">Paper Trading Mode</p>
                      <p className="text-xs text-muted-foreground">Simulate trades without real money</p>
                    </div>
                    <Switch checked={form.paper_mode} onCheckedChange={v => setForm(f => ({ ...f, paper_mode: v }))} />
                  </div>

                  {selectedSource && selectedChannel && (
                    <div className="rounded-md border bg-muted/30 p-3 text-sm space-y-1">
                      <p><span className="text-muted-foreground">Source:</span> {selectedSource.display_name}</p>
                      <p><span className="text-muted-foreground">Channel:</span> {selectedChannel.display_name}</p>
                    </div>
                  )}
                </div>
              )}

              <DialogFooter className="gap-2">
                {step > 1 && (
                  <Button variant="outline" onClick={() => setStep(s => s - 1)}>Back</Button>
                )}
                {step < 3 ? (
                  <Button
                    onClick={() => setStep(s => s + 1)}
                    disabled={
                      (step === 1 && !form.data_source_id) ||
                      (step === 2 && !form.channel_id)
                    }
                  >
                    Next <ChevronRight className="ml-1 h-4 w-4" />
                  </Button>
                ) : (
                  <Button onClick={handleCreate} disabled={createMutation.isPending}>
                    {createMutation.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                    Create Pipeline
                  </Button>
                )}
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : !pipelines?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 space-y-4">
            <Workflow className="h-12 w-12 text-muted-foreground" />
            <div className="text-center space-y-1">
              <h3 className="text-lg font-semibold">No Pipelines Yet</h3>
              <p className="text-sm text-muted-foreground max-w-sm">
                Create a trade pipeline to connect a Discord channel to a trading account
                for real-time automated trade execution.
              </p>
            </div>
            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="mr-1 h-4 w-4" /> Create Your First Pipeline
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {pipelines.map(p => {
            const statusCfg = STATUS_CONFIG[p.status] || STATUS_CONFIG.STOPPED
            const StatusIcon = statusCfg.icon

            return (
              <Card key={p.id} className="relative">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div className="space-y-1 min-w-0 flex-1">
                      <CardTitle className="text-base truncate">{p.name}</CardTitle>
                      <div className="flex items-center gap-2">
                        <div className={`h-2 w-2 rounded-full ${statusCfg.color}`} />
                        <Badge
                          variant={p.status === 'CONNECTED' ? 'default' : p.status === 'ERROR' ? 'destructive' : 'secondary'}
                          className="text-[10px]"
                        >
                          {p.status === 'CONNECTING' ? (
                            <><Loader2 className="mr-1 h-3 w-3 animate-spin" /> Connecting</>
                          ) : p.status}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      {p.enabled ? (
                        <Button
                          variant="ghost" size="icon" className="h-8 w-8"
                          onClick={() => stopMutation.mutate(p.id)}
                          title="Stop pipeline"
                        >
                          <Square className="h-4 w-4" />
                        </Button>
                      ) : (
                        <Button
                          variant="ghost" size="icon" className="h-8 w-8"
                          onClick={() => startMutation.mutate(p.id)}
                          title="Start pipeline"
                        >
                          <Play className="h-4 w-4" />
                        </Button>
                      )}
                      <Button
                        variant="ghost" size="icon" className="h-8 w-8 text-destructive"
                        onClick={() => {
                          if (window.confirm('Delete this pipeline?')) deleteMutation.mutate(p.id)
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 pt-0">
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Database className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">{p.data_source_name || 'Unknown'}</span>
                    </div>
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Hash className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">{p.channel_name || p.channel_identifier || 'Unknown'}</span>
                    </div>
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Wallet className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">{p.trading_account_name || 'Unknown'}</span>
                    </div>
                  </div>

                  {p.error_message && (
                    <div className="text-xs text-red-500 bg-red-500/10 rounded p-2 truncate" title={p.error_message}>
                      {p.error_message}
                    </div>
                  )}

                  <div className="flex gap-4 text-xs text-muted-foreground pt-1 border-t">
                    <span>{p.messages_count} messages</span>
                    <span>{p.trades_count} trades</span>
                    {p.auto_approve && <Badge variant="outline" className="text-[10px]">Auto</Badge>}
                    {p.paper_mode && <Badge variant="outline" className="text-[10px]">Paper</Badge>}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
