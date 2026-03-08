/**
 * Connectors page — data source connector management with Discord wizard.
 * Multi-step add flow: Credentials -> Server Discovery -> Channel Selection.
 * Full CRUD: create, test, delete connectors.
 */
import { useState, useEffect, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import {
  Plug, Plus, Loader2, Server, Hash, Trash2, MoreVertical,
  CheckSquare, Square as SquareIcon, ChevronRight, ChevronLeft, Wifi, X,
} from 'lucide-react'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

// ─── Types ──────────────────────────────────────────────────────────────────

interface Connector {
  id: string
  name: string
  type: string
  status: string
  config: Record<string, unknown>
  is_active: boolean
  last_connected_at: string | null
  error_message: string | null
  created_at: string
}

interface GuildInfo {
  guild_id: string
  guild_name: string
  channel_count: number
}

interface ChannelInfo {
  channel_id: string
  channel_name: string
  guild_id: string
  guild_name: string
  category: string | null
}

// ─── Constants ──────────────────────────────────────────────────────────────

const AUTH_HELP: Record<string, string> = {
  user_token:
    'Use your personal Discord token. Open Discord in browser, press F12, go to Network tab, and copy the "Authorization" header value.',
  bot: 'Create a bot at discord.com/developers, copy the bot token. Requires admin to invite the bot to the server.',
}

const EMPTY_FORM = {
  display_name: '',
  source_type: 'discord',
  auth_type: 'user_token',
  token: '',
  server_id: '',
  server_name: '',
}

// ─── Add Connector Wizard ───────────────────────────────────────────────────

function AddConnectorWizard({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: () => void
}) {
  const [step, setStep] = useState(1)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [servers, setServers] = useState<GuildInfo[]>([])
  const [channels, setChannels] = useState<ChannelInfo[]>([])
  const [selectedChannels, setSelectedChannels] = useState<Set<string>>(new Set())
  const [discovering, setDiscovering] = useState(false)
  const [discoveringChannels, setDiscoveringChannels] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setStep(1)
      setForm({ ...EMPTY_FORM })
      setServers([])
      setChannels([])
      setSelectedChannels(new Set())
      setError(null)
    }
  }, [open])

  const handleDiscoverServers = async () => {
    if (!form.token) return
    setDiscovering(true)
    setError(null)
    try {
      const res = await api.post('/api/v2/connectors/discover-servers', {
        token: form.token,
        auth_type: form.auth_type,
      })
      setServers(res.data.servers || [])
      setStep(2)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to discover servers. Check your token and try again.'
      setError(msg)
    }
    setDiscovering(false)
  }

  const handleDiscoverChannels = async () => {
    if (!form.server_id) return
    setDiscoveringChannels(true)
    setError(null)
    try {
      const res = await api.post('/api/v2/connectors/discover-channels', {
        token: form.token,
        auth_type: form.auth_type,
        server_id: form.server_id,
      })
      const discovered: ChannelInfo[] = res.data.channels || []
      setChannels(discovered)
      setSelectedChannels(new Set(discovered.map((c) => c.channel_id)))
      setStep(3)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to discover channels.'
      setError(msg)
    }
    setDiscoveringChannels(false)
  }

  const channelsByCategory = useMemo(() => {
    const groups: Record<string, ChannelInfo[]> = {}
    for (const ch of channels) {
      const cat = ch.category || 'Uncategorized'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(ch)
    }
    return Object.entries(groups).sort(([a], [b]) => {
      if (a === 'Uncategorized') return 1
      if (b === 'Uncategorized') return -1
      return a.localeCompare(b)
    })
  }, [channels])

  const toggleChannel = (id: string) => {
    setSelectedChannels((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAllChannels = () => {
    if (selectedChannels.size === channels.length) {
      setSelectedChannels(new Set())
    } else {
      setSelectedChannels(new Set(channels.map((c) => c.channel_id)))
    }
  }

  const handleSubmit = async () => {
    setCreating(true)
    setError(null)

    const credentials: Record<string, string> = {}
    if (form.auth_type === 'bot') credentials.bot_token = form.token
    else credentials.user_token = form.token

    const selected = channels
      .filter((c) => selectedChannels.has(c.channel_id))
      .map((c) => ({
        channel_id: c.channel_id,
        channel_name: c.channel_name,
        guild_id: c.guild_id,
        guild_name: c.guild_name,
      }))

    try {
      await api.post('/api/v2/connectors', {
        name: form.display_name,
        type: 'discord',
        config: {
          server_id: form.server_id,
          server_name: form.server_name,
          auth_type: form.auth_type,
          selected_channels: selected,
        },
        credentials,
      })
      onCreated()
      onOpenChange(false)
    } catch (err: unknown) {
      const resp = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
      let msg: string | undefined
      if (resp?.detail) {
        if (typeof resp.detail === 'string') msg = resp.detail
        else if (Array.isArray(resp.detail))
          msg = resp.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
      }
      setError(msg || 'Failed to create connector.')
    }
    setCreating(false)
  }

  const STEP_LABELS = ['Credentials', 'Server', 'Channels']
  const stepDescription =
    step === 1
      ? 'Enter your Discord credentials'
      : step === 2
        ? 'Select a Discord server'
        : 'Choose channels to monitor'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add Discord Connector</DialogTitle>
          <DialogDescription>{stepDescription}</DialogDescription>
        </DialogHeader>

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="shrink-0">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Step indicator */}
        <div className="flex gap-1.5 mb-1">
          {STEP_LABELS.map((label, i) => {
            const s = i + 1
            return (
              <div key={s} className="flex-1 flex flex-col items-center gap-1">
                <div
                  className={`w-full h-1.5 rounded-full transition-colors ${s <= step ? 'bg-primary' : 'bg-muted'}`}
                />
                <span
                  className={`text-[10px] ${s === step ? 'text-primary font-medium' : 'text-muted-foreground'}`}
                >
                  {label}
                </span>
              </div>
            )
          })}
        </div>

        {/* Step 1: Credentials */}
        {step === 1 && (
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="ds-name">Display Name</Label>
              <Input
                id="ds-name"
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                placeholder="e.g. Trading Alerts Server"
              />
            </div>
            <div className="space-y-2">
              <Label>Authentication Method</Label>
              <div className="flex gap-3">
                {(['user_token', 'bot'] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setForm({ ...form, auth_type: t })}
                    className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-colors ${
                      form.auth_type === t
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:border-primary/50'
                    }`}
                  >
                    {t === 'user_token' ? 'User Token' : 'Bot Token'}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{AUTH_HELP[form.auth_type]}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ds-token">
                {form.auth_type === 'bot' ? 'Bot Token' : 'User Token'}
              </Label>
              <Input
                id="ds-token"
                type="password"
                value={form.token}
                onChange={(e) => setForm({ ...form, token: e.target.value })}
                placeholder={
                  form.auth_type === 'bot'
                    ? 'Bot token from Developer Portal'
                    : 'Your Discord user token'
                }
                className="font-mono"
              />
            </div>
          </div>
        )}

        {/* Step 2: Server selection */}
        {step === 2 && (
          <div className="space-y-4 py-2">
            {servers.length > 0 ? (
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {servers.map((g) => (
                  <button
                    key={g.guild_id}
                    type="button"
                    onClick={() =>
                      setForm((f) => ({
                        ...f,
                        server_id: g.guild_id,
                        server_name: g.guild_name,
                      }))
                    }
                    className={`w-full flex items-center gap-3 rounded-lg border p-3.5 text-left transition-all ${
                      form.server_id === g.guild_id
                        ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
                        : 'border-border hover:border-primary/40 hover:bg-accent/50'
                    }`}
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500/10">
                      <Server className="h-5 w-5 text-indigo-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{g.guild_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {g.channel_count} channel{g.channel_count !== 1 ? 's' : ''}
                      </p>
                    </div>
                    {form.server_id === g.guild_id && (
                      <Badge variant="default" className="text-[10px]">
                        Selected
                      </Badge>
                    )}
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center">
                <Server className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  No servers found for this account.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Step 3: Channel selection */}
        {step === 3 && (
          <div className="space-y-3 py-2">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                {selectedChannels.size} of {channels.length} channel
                {channels.length !== 1 ? 's' : ''} selected
              </p>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs px-2"
                onClick={toggleAllChannels}
              >
                {selectedChannels.size === channels.length ? 'Deselect All' : 'Select All'}
              </Button>
            </div>
            {channels.length > 0 ? (
              <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
                {channelsByCategory.map(([category, chs]) => (
                  <div key={category}>
                    <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5 px-1">
                      {category}
                    </p>
                    <div className="space-y-1">
                      {chs.map((ch) => {
                        const isSelected = selectedChannels.has(ch.channel_id)
                        return (
                          <button
                            key={ch.channel_id}
                            type="button"
                            onClick={() => toggleChannel(ch.channel_id)}
                            className={`w-full flex items-center gap-2.5 rounded-md border px-3 py-2 text-left text-sm transition-all ${
                              isSelected
                                ? 'border-primary/40 bg-primary/5'
                                : 'border-transparent hover:bg-accent/50'
                            }`}
                          >
                            {isSelected ? (
                              <CheckSquare className="h-4 w-4 text-primary shrink-0" />
                            ) : (
                              <SquareIcon className="h-4 w-4 text-muted-foreground/40 shrink-0" />
                            )}
                            <Hash className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="truncate">{ch.channel_name}</span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center">
                <Hash className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  No channels found in this server.
                </p>
              </div>
            )}
          </div>
        )}

        <DialogFooter className="gap-2">
          {step > 1 && (
            <Button variant="outline" onClick={() => setStep(step - 1)}>
              <ChevronLeft className="mr-1 h-4 w-4" /> Back
            </Button>
          )}
          <div className="flex-1" />

          {step === 1 && (
            <Button
              onClick={handleDiscoverServers}
              disabled={!form.display_name || !form.token || discovering}
            >
              {discovering && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              {discovering ? 'Discovering…' : 'Next'}
              {!discovering && <ChevronRight className="ml-1 h-4 w-4" />}
            </Button>
          )}

          {step === 2 && (
            <Button
              onClick={handleDiscoverChannels}
              disabled={!form.server_id || discoveringChannels}
            >
              {discoveringChannels && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              {discoveringChannels ? 'Loading channels…' : 'Next'}
              {!discoveringChannels && <ChevronRight className="ml-1 h-4 w-4" />}
            </Button>
          )}

          {step === 3 && (
            <Button
              onClick={handleSubmit}
              disabled={selectedChannels.size === 0 || creating}
            >
              {creating && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              {creating ? 'Creating…' : 'Create Connector'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function ConnectorsPage() {
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Connector | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{
    id: string
    connection_status: string
    detail: string
  } | null>(null)

  const { data: connectors = [] } = useQuery<Connector[]>({
    queryKey: ['connectors'],
    queryFn: async () => {
      const res = await api.get('/api/v2/connectors')
      return res.data
    },
    refetchInterval: 15000,
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/api/v2/connectors/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connectors'] })
      setDeleteTarget(null)
    },
  })

  const handleTest = async (id: string) => {
    setTestingId(id)
    setTestResult(null)
    try {
      const res = await api.post(`/api/v2/connectors/${id}/test`)
      setTestResult({ id, ...res.data })
      qc.invalidateQueries({ queryKey: ['connectors'] })
    } catch {
      setTestResult({ id, connection_status: 'ERROR', detail: 'Test request failed' })
    }
    setTestingId(null)
  }

  const channelCount = (c: Connector): number => {
    const sel = c.config?.selected_channels
    return Array.isArray(sel) ? sel.length : 0
  }

  const platformColor = (type: string) => {
    if (type === 'discord') return 'bg-indigo-500/10 text-indigo-500'
    if (type === 'alpaca') return 'bg-emerald-500/10 text-emerald-500'
    return 'bg-muted text-muted-foreground'
  }

  const statusDot = (s: string) => {
    const u = s.toUpperCase()
    if (['CONNECTED', 'ONLINE'].includes(u)) return 'bg-emerald-500'
    if (u === 'ERROR') return 'bg-red-500'
    return 'bg-zinc-400'
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Plug} title="Connectors" description="Data source and broker connectors">
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="h-4 w-4 mr-2" /> Add Connector
        </Button>
      </PageHeader>

      {/* Test result banner */}
      {testResult && (
        <div
          className={`rounded-lg border p-3 text-sm flex items-center justify-between ${
            testResult.connection_status === 'connected'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
              : 'border-red-500/30 bg-red-500/10 text-red-400'
          }`}
        >
          <span>
            {testResult.connection_status === 'connected'
              ? `Connected successfully${testResult.detail ? ` — ${testResult.detail}` : ''}`
              : `Connection failed: ${testResult.detail}`}
          </span>
          <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setTestResult(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {connectors.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 p-12 text-center">
          <Plug className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
          <p className="text-muted-foreground mb-1">No connectors configured</p>
          <p className="text-sm text-muted-foreground/70 mb-4">
            Click "Add Connector" to connect your first Discord server.
          </p>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 mr-1.5" /> Add Connector
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {connectors.map((c) => (
            <div
              key={c.id}
              className="group relative rounded-xl border border-white/10 bg-card p-5 transition-colors hover:bg-white/[0.02]"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="relative">
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-lg ${platformColor(c.type)}`}
                    >
                      <Plug className="h-5 w-5" />
                    </div>
                    <span
                      className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-card ${statusDot(c.status)}`}
                    />
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-semibold text-sm truncate">{c.name}</h3>
                    {(c.config?.server_name as string) ? (
                      <p className="text-xs text-muted-foreground flex items-center gap-1">
                        <Server className="h-3 w-3" /> {c.config.server_name as string}
                      </p>
                    ) : (
                      <p className="text-xs text-muted-foreground capitalize">{c.type}</p>
                    )}
                  </div>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onClick={() => handleTest(c.id)}
                      disabled={testingId === c.id}
                    >
                      {testingId === c.id ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Wifi className="mr-2 h-4 w-4" />
                      )}
                      Test Connection
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onClick={() => setDeleteTarget(c)}
                    >
                      <Trash2 className="mr-2 h-4 w-4" /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>

              <div className="mt-4 flex items-center gap-2 flex-wrap">
                <StatusBadge status={c.status} />
                <Badge variant="outline" className="text-xs capitalize">
                  {c.type}
                </Badge>
                {channelCount(c) > 0 && (
                  <Badge variant="outline" className="text-xs">
                    <Hash className="h-3 w-3 mr-0.5" />
                    {channelCount(c)} channel{channelCount(c) !== 1 ? 's' : ''}
                  </Badge>
                )}
              </div>

              {c.last_connected_at && (
                <p className="mt-3 text-xs text-muted-foreground">
                  Last connected: {new Date(c.last_connected_at).toLocaleString()}
                </p>
              )}
              {c.error_message && (
                <p className="mt-1 text-xs text-red-400 truncate" title={c.error_message}>
                  {c.error_message}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Add wizard */}
      <AddConnectorWizard
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={() => qc.invalidateQueries({ queryKey: ['connectors'] })}
      />

      {/* Delete confirm */}
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => {
          if (!v) setDeleteTarget(null)
        }}
        title="Delete Connector"
        description={`Are you sure you want to delete "${deleteTarget?.name}"? This will remove the connector and all its channel mappings.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id)
        }}
      />
    </div>
  )
}
