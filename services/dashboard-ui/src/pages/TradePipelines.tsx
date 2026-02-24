import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useAuth } from '@/hooks/useAuth'
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
  Database, Hash, Wallet, AlertCircle, CheckCircle2, XCircle,
  ChevronRight, Search, Server, ChevronLeft, Activity, FlaskConical,
  ChevronDown, ChevronUp,
} from 'lucide-react'

interface Source {
  id: string
  display_name: string
  source_type: string
  connection_status: string
  enabled: boolean
  server_id?: string | null
  server_name?: string | null
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

interface GuildInfo {
  guild_id: string
  guild_name: string
  channel_count: number
}

const STATUS_CONFIG: Record<string, { color: string; icon: React.ElementType }> = {
  CONNECTED: { color: 'bg-green-500', icon: CheckCircle2 },
  CONNECTING: { color: 'bg-yellow-500 animate-pulse', icon: Loader2 },
  RUNNING: { color: 'bg-green-500', icon: CheckCircle2 },
  STOPPED: { color: 'bg-gray-400', icon: Square },
  ERROR: { color: 'bg-red-500', icon: XCircle },
  DISCONNECTED: { color: 'bg-gray-400', icon: Square },
}

const STEP_LABELS = [
  'Select data source',
  'Select server',
  'Select channel',
  'Configure pipeline',
]

function channelDisplayName(ch: Channel): string {
  const raw = ch.display_name || ''
  const stripped = raw.replace(/^.+\/\s*#/, '')
  return stripped || ch.channel_identifier
}

export default function TradePipelines() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [step, setStep] = useState(1)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedGuild, setSelectedGuild] = useState<string>('')
  const [channelSearch, setChannelSearch] = useState('')
  const [diagOpen, setDiagOpen] = useState(false)
  const [testingPipeline, setTestingPipeline] = useState<string | null>(null)

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
      const t = setTimeout(() => setError(null), 6000)
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

  const { data: diagnostics, isLoading: diagLoading, refetch: refetchDiag } = useQuery({
    queryKey: ['pipeline-diagnostics'],
    queryFn: () => axios.get('/api/v1/pipelines/diagnostics').then(r => r.data),
    enabled: isAdmin && diagOpen,
    refetchInterval: diagOpen ? 15_000 : false,
  })

  const testMutation = useMutation({
    mutationFn: (pipelineId: string) => axios.post(`/api/v1/pipelines/${pipelineId}/test`).then(r => r.data),
    onSettled: () => setTestingPipeline(null),
  })

  const { data: accounts } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => axios.get('/api/v1/accounts').then(r => r.data),
  })

  const guilds = useMemo<GuildInfo[]>(() => {
    if (!channels) return []
    const map = new Map<string, GuildInfo>()
    for (const ch of channels) {
      const gid = ch.guild_id || '_unknown'
      const gname = ch.guild_name || 'Unknown Server'
      if (!map.has(gid)) {
        map.set(gid, { guild_id: gid, guild_name: gname, channel_count: 0 })
      }
      map.get(gid)!.channel_count++
    }
    return Array.from(map.values()).sort((a, b) => a.guild_name.localeCompare(b.guild_name))
  }, [channels])

  const filteredChannels = useMemo(() => {
    if (!channels) return []
    let list = channels.filter(ch => (ch.guild_id || '_unknown') === selectedGuild)
    if (channelSearch.trim()) {
      const q = channelSearch.toLowerCase()
      list = list.filter(ch => channelDisplayName(ch).toLowerCase().includes(q))
    }
    return list.sort((a, b) => channelDisplayName(a).localeCompare(channelDisplayName(b)))
  }, [channels, selectedGuild, channelSearch])

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

  useEffect(() => {
    if ((step === 2 || step === 3) && form.data_source_id && channels !== undefined && channels.length === 0 && !syncing) {
      handleSyncChannels()
    }
  }, [step, form.data_source_id, channels])

  const resetDialog = () => {
    setDialogOpen(false)
    setStep(1)
    setForm({ name: '', data_source_id: '', channel_id: '', trading_account_id: '', auto_approve: true, paper_mode: false })
    setSelectedGuild('')
    setChannelSearch('')
    setError(null)
  }

  const handleCreate = () => {
    if (!form.name || !form.data_source_id || !form.channel_id || !form.trading_account_id) {
      setError('Please fill in all fields')
      return
    }
    createMutation.mutate(form)
  }

  const canAdvance = () => {
    if (step === 1) return !!form.data_source_id
    if (step === 2) return !!selectedGuild
    if (step === 3) return !!form.channel_id
    return false
  }

  const handleNext = () => {
    if (step === 1 && form.data_source_id) {
      const src = sources?.find(s => s.id === form.data_source_id)
      if (src?.server_id) {
        setSelectedGuild(src.server_id)
        setStep(3)
        return
      }
    }
    setStep(s => s + 1)
  }

  const handleBack = () => {
    if (step === 3) {
      setForm(f => ({ ...f, channel_id: '' }))
      setChannelSearch('')
      const src = sources?.find(s => s.id === form.data_source_id)
      if (src?.server_id) {
        setStep(1)
        return
      }
    }
    if (step === 2) {
      setSelectedGuild('')
    }
    setStep(s => s - 1)
  }

  const selectedChannel = channels?.find(c => c.id === form.channel_id)
  const selectedSource = sources?.find(s => s.id === form.data_source_id)
  const selectedGuildInfo = guilds.find(g => g.guild_id === selectedGuild)

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
                  Step {step} of 4: {STEP_LABELS[step - 1]}
                </DialogDescription>
              </DialogHeader>

              {error && (
                <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-400">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{error}</span>
                </div>
              )}

              {/* Progress bar */}
              <div className="flex gap-1.5">
                {[1, 2, 3, 4].map(s => (
                  <div key={s} className="flex-1 flex flex-col items-center gap-1">
                    <div className={`w-full h-1.5 rounded-full transition-colors duration-300 ${s <= step ? 'bg-primary' : 'bg-muted'}`} />
                    <span className={`text-[10px] transition-colors ${s === step ? 'text-primary font-medium' : 'text-muted-foreground'}`}>
                      {s === 1 ? 'Source' : s === 2 ? 'Server' : s === 3 ? 'Channel' : 'Config'}
                    </span>
                  </div>
                ))}
              </div>

              {/* Step 1: Data Source */}
              {step === 1 && (
                <div className="space-y-4 py-2">
                  <div className="space-y-2">
                    <Label className="text-sm font-medium">Discord Connection</Label>
                    {sources?.filter(s => s.source_type === 'discord').length ? (
                      <div className="space-y-2">
                        {sources.filter(s => s.source_type === 'discord').map(s => (
                          <button
                            key={s.id}
                            type="button"
                            onClick={() => setForm(f => ({ ...f, data_source_id: s.id, channel_id: '' }))}
                            className={`w-full flex items-center gap-3 rounded-lg border p-3.5 text-left transition-all ${
                              form.data_source_id === s.id
                                ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
                                : 'border-border hover:border-primary/40 hover:bg-accent/50'
                            }`}
                          >
                            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                              <Database className="h-5 w-5 text-primary" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium truncate">{s.display_name}</p>
                              <p className="text-xs text-muted-foreground">
                                {s.server_name ? s.server_name : 'Discord'} &middot; {s.enabled ? 'Enabled' : 'Disabled'}
                              </p>
                            </div>
                            <Badge
                              variant={s.connection_status === 'CONNECTED' ? 'default' : 'secondary'}
                              className="text-[10px] shrink-0"
                            >
                              {s.connection_status}
                            </Badge>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-6 text-center">
                        <Database className="h-8 w-8 text-muted-foreground" />
                        <p className="text-sm text-muted-foreground">
                          No Discord data sources found.<br />
                          Create one in the <strong>Data Sources</strong> page first.
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Step 2: Server */}
              {step === 2 && (
                <div className="space-y-4 py-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Discord Server</Label>
                    <Button
                      type="button" variant="outline" size="sm"
                      onClick={handleSyncChannels} disabled={syncing}
                      className="h-8"
                    >
                      {syncing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                      {syncing ? 'Discovering...' : 'Refresh Servers'}
                    </Button>
                  </div>

                  {(channelsLoading || syncing) ? (
                    <div className="flex flex-col items-center gap-3 py-8">
                      <Loader2 className="h-6 w-6 animate-spin text-primary" />
                      <p className="text-sm text-muted-foreground">Discovering servers and channels...</p>
                    </div>
                  ) : guilds.length > 0 ? (
                    <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                      {guilds.map(g => (
                        <button
                          key={g.guild_id}
                          type="button"
                          onClick={() => setSelectedGuild(g.guild_id)}
                          className={`w-full flex items-center gap-3 rounded-lg border p-3.5 text-left transition-all ${
                            selectedGuild === g.guild_id
                              ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
                              : 'border-border hover:border-primary/40 hover:bg-accent/50'
                          }`}
                        >
                          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500/10">
                            <Server className="h-5 w-5 text-indigo-500" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate">{g.guild_name}</p>
                            <p className="text-xs text-muted-foreground">{g.channel_count} channel{g.channel_count !== 1 ? 's' : ''}</p>
                          </div>
                          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center">
                      <Server className="h-8 w-8 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">No servers found</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Click "Refresh Servers" to discover channels from your Discord account.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Step 3: Channel */}
              {step === 3 && (
                <div className="space-y-3 py-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <Label className="text-sm font-medium">Channel</Label>
                      {selectedGuildInfo && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          in {selectedGuildInfo.guild_name}
                        </p>
                      )}
                    </div>
                    <Badge variant="outline" className="text-xs">
                      {filteredChannels.length} channel{filteredChannels.length !== 1 ? 's' : ''}
                    </Badge>
                  </div>

                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search channels..."
                      value={channelSearch}
                      onChange={e => setChannelSearch(e.target.value)}
                      className="pl-9 h-9"
                    />
                  </div>

                  {filteredChannels.length > 0 ? (
                    <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
                      {filteredChannels.map(ch => {
                        const name = channelDisplayName(ch)
                        return (
                          <button
                            key={ch.id}
                            type="button"
                            onClick={() => setForm(f => ({ ...f, channel_id: ch.id }))}
                            className={`w-full flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm text-left transition-all ${
                              form.channel_id === ch.id
                                ? 'bg-primary/10 text-primary ring-1 ring-primary/20'
                                : 'hover:bg-accent/70 text-foreground'
                            }`}
                          >
                            <Hash className={`h-4 w-4 shrink-0 ${form.channel_id === ch.id ? 'text-primary' : 'text-muted-foreground'}`} />
                            <span className="truncate font-medium">{name}</span>
                            {form.channel_id === ch.id && (
                              <CheckCircle2 className="h-4 w-4 text-primary ml-auto shrink-0" />
                            )}
                          </button>
                        )
                      })}
                    </div>
                  ) : channelSearch ? (
                    <div className="flex flex-col items-center gap-2 py-6 text-center">
                      <Search className="h-6 w-6 text-muted-foreground" />
                      <p className="text-sm text-muted-foreground">
                        No channels match "{channelSearch}"
                      </p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2 py-6 text-center">
                      <Hash className="h-6 w-6 text-muted-foreground" />
                      <p className="text-sm text-muted-foreground">No channels in this server</p>
                    </div>
                  )}
                </div>
              )}

              {/* Step 4: Configure */}
              {step === 4 && (
                <div className="space-y-4 py-2">
                  {selectedSource && selectedChannel && (
                    <div className="rounded-lg border bg-muted/30 p-3 space-y-1.5 text-sm">
                      <div className="flex items-center gap-2">
                        <Database className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="text-muted-foreground">Source:</span>
                        <span className="font-medium">{selectedSource.display_name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Server className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="text-muted-foreground">Server:</span>
                        <span className="font-medium">{selectedGuildInfo?.guild_name || 'Unknown'}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Hash className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="text-muted-foreground">Channel:</span>
                        <span className="font-medium">{channelDisplayName(selectedChannel)}</span>
                      </div>
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label className="text-sm font-medium">Pipeline Name</Label>
                    <Input
                      placeholder={selectedChannel ? `${channelDisplayName(selectedChannel)} Pipeline` : 'My Pipeline'}
                      value={form.name}
                      onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label className="text-sm font-medium">Trading Account</Label>
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

                  <div className="space-y-2">
                    <div className="flex items-center justify-between rounded-lg border p-3">
                      <div>
                        <p className="text-sm font-medium">Auto-Approve Trades</p>
                        <p className="text-xs text-muted-foreground">Execute parsed trades without manual review</p>
                      </div>
                      <Switch checked={form.auto_approve} onCheckedChange={v => setForm(f => ({ ...f, auto_approve: v }))} />
                    </div>

                    <div className="flex items-center justify-between rounded-lg border p-3">
                      <div>
                        <p className="text-sm font-medium">Paper Trading</p>
                        <p className="text-xs text-muted-foreground">Simulate trades without real money</p>
                      </div>
                      <Switch checked={form.paper_mode} onCheckedChange={v => setForm(f => ({ ...f, paper_mode: v }))} />
                    </div>
                  </div>
                </div>
              )}

              <DialogFooter className="gap-2 pt-2">
                {step > 1 && (
                  <Button variant="outline" onClick={handleBack}>
                    <ChevronLeft className="mr-1 h-4 w-4" /> Back
                  </Button>
                )}
                <div className="flex-1" />
                {step < 4 ? (
                  <Button onClick={handleNext} disabled={!canAdvance()}>
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

      {/* Admin Diagnostics Panel */}
      {isAdmin && (
        <Card>
          <button
            className="flex items-center justify-between w-full p-4 text-left"
            onClick={() => { setDiagOpen(o => !o); if (!diagOpen) refetchDiag() }}
          >
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-sm">Pipeline Diagnostics</span>
              {diagnostics && (
                <Badge variant={
                  diagnostics.orchestrator?.active_workers && !diagnostics.orchestrator?.error
                    ? 'default' : 'destructive'
                } className="text-[10px]">
                  {diagnostics.orchestrator?.error ? 'Orchestrator Down' :
                    `${diagnostics.orchestrator?.worker_count ?? 0} workers`}
                </Badge>
              )}
            </div>
            {diagOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {diagOpen && (
            <CardContent className="pt-0 pb-4 space-y-4">
              {diagLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading diagnostics...
                </div>
              ) : diagnostics ? (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  {/* Orchestrator */}
                  <div className="rounded-lg border p-3 space-y-1.5">
                    <div className="flex items-center gap-2 text-xs font-medium">
                      <div className={`h-2 w-2 rounded-full ${
                        diagnostics.orchestrator?.running ? 'bg-green-500' : 'bg-red-500'
                      }`} />
                      Source Orchestrator
                    </div>
                    {diagnostics.orchestrator?.error ? (
                      <p className="text-xs text-red-500">{diagnostics.orchestrator.error}</p>
                    ) : (
                      <>
                        <p className="text-xs text-muted-foreground">
                          Workers: {diagnostics.orchestrator?.worker_count ?? 0}
                        </p>
                        {diagnostics.orchestrator?.active_workers && Object.entries(diagnostics.orchestrator.active_workers).map(([k, v]: [string, any]) => (
                          <div key={k} className="flex items-center gap-1.5 text-xs">
                            <div className={`h-1.5 w-1.5 rounded-full ${v.alive ? 'bg-green-500' : 'bg-red-500'}`} />
                            <span className="truncate font-mono">{k.replace('pipe:', '').slice(0, 8)}...</span>
                            <Badge variant="outline" className="text-[9px] ml-auto">{v.status}</Badge>
                          </div>
                        ))}
                        {diagnostics.orchestrator?.backoff && Object.keys(diagnostics.orchestrator.backoff).length > 0 && (
                          <div className="text-xs text-yellow-600">
                            {Object.keys(diagnostics.orchestrator.backoff).length} worker(s) in backoff
                          </div>
                        )}
                      </>
                    )}
                  </div>
                  {/* Audit Writer */}
                  <div className="rounded-lg border p-3 space-y-1.5">
                    <div className="flex items-center gap-2 text-xs font-medium">
                      <div className={`h-2 w-2 rounded-full ${
                        diagnostics.audit_writer?.status === 'ready' ? 'bg-green-500' : 'bg-red-500'
                      }`} />
                      Audit Writer
                    </div>
                    {diagnostics.audit_writer?.error ? (
                      <p className="text-xs text-red-500">{diagnostics.audit_writer.error}</p>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Status: {diagnostics.audit_writer?.status ?? 'unknown'}
                      </p>
                    )}
                  </div>
                  {/* Kafka */}
                  <div className="rounded-lg border p-3 space-y-1.5">
                    <div className="flex items-center gap-2 text-xs font-medium">
                      <div className={`h-2 w-2 rounded-full ${
                        diagnostics.kafka?.status === 'reachable' ? 'bg-green-500' : 'bg-red-500'
                      }`} />
                      Kafka
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {diagnostics.kafka?.status === 'reachable' ? 'Connected' : diagnostics.kafka?.error || 'Unreachable'}
                    </p>
                  </div>
                  {/* Raw Messages */}
                  <div className="rounded-lg border p-3 space-y-1.5">
                    <div className="flex items-center gap-2 text-xs font-medium">
                      <Database className="h-3 w-3" />
                      Raw Messages
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Total: {diagnostics.raw_messages?.total_count ?? 0}
                    </p>
                    {diagnostics.raw_messages?.recent?.length > 0 && (
                      <p className="text-xs text-muted-foreground truncate">
                        Latest: {diagnostics.raw_messages.recent[0]?.created_at
                          ? new Date(diagnostics.raw_messages.recent[0].created_at).toLocaleString()
                          : 'N/A'}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Failed to load diagnostics</p>
              )}
              <div className="flex gap-2 pt-1">
                <Button variant="outline" size="sm" onClick={() => refetchDiag()}>
                  <RefreshCw className="mr-1 h-3 w-3" /> Refresh
                </Button>
                {testMutation.data && (
                  <div className={`flex items-center gap-1.5 text-xs px-3 py-1 rounded-lg border ${
                    testMutation.data.success ? 'text-green-700 border-green-300 bg-green-50 dark:text-green-400 dark:border-green-800 dark:bg-green-900/20' : 'text-red-700 border-red-300 bg-red-50 dark:text-red-400 dark:border-red-800 dark:bg-red-900/20'
                  }`}>
                    {testMutation.data.success
                      ? <><CheckCircle2 className="h-3 w-3" /> Test passed ({testMutation.data.latency_seconds}s)</>
                      : <><XCircle className="h-3 w-3" /> Test failed: {testMutation.data.stage} - {testMutation.data.detail || testMutation.data.error}</>}
                  </div>
                )}
              </div>
            </CardContent>
          )}
        </Card>
      )}

      {/* Pipeline list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : !pipelines?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 space-y-4">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
              <Workflow className="h-8 w-8 text-primary" />
            </div>
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

            return (
              <Card
                key={p.id}
                className="group relative overflow-hidden cursor-pointer transition-shadow hover:shadow-md hover:ring-1 hover:ring-primary/20"
                onClick={() => navigate(`/pipelines/${p.id}`)}
              >
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
                    <div className="flex gap-1 shrink-0" onClick={e => e.stopPropagation()}>
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
                      {isAdmin && (
                        <Button
                          variant="ghost" size="icon" className="h-8 w-8"
                          onClick={() => { setTestingPipeline(p.id); testMutation.mutate(p.id) }}
                          disabled={testingPipeline === p.id}
                          title="Test pipeline end-to-end"
                        >
                          {testingPipeline === p.id
                            ? <Loader2 className="h-4 w-4 animate-spin" />
                            : <FlaskConical className="h-4 w-4" />}
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
                    <div className="text-xs text-red-500 bg-red-500/10 rounded-lg p-2 truncate" title={p.error_message}>
                      {p.error_message}
                    </div>
                  )}

                  <div className="flex items-center gap-3 text-xs text-muted-foreground pt-2 border-t">
                    <span>{p.messages_count} msgs</span>
                    <span>{p.trades_count} trades</span>
                    <div className="flex items-center gap-1 ml-auto">
                      {p.auto_approve && <Badge variant="outline" className="text-[10px]">Auto</Badge>}
                      {p.paper_mode && <Badge variant="outline" className="text-[10px]">Paper</Badge>}
                      <ChevronRight className="h-4 w-4 text-muted-foreground/50 group-hover:text-primary transition-colors ml-1" />
                    </div>
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
