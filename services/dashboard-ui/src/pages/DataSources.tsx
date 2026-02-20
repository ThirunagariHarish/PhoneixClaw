import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent } from '@/components/ui/card'
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Plus, MoreVertical, Trash2, Database, Loader2 } from 'lucide-react'

interface Source {
  id: string
  display_name: string
  source_type: string
  auth_type: string
  connection_status: string
  enabled: boolean
  created_at: string
}

const AUTH_HELP: Record<string, string> = {
  user_token:
    'Use your personal Discord token. Open Discord in browser, press F12, go to Network tab, copy the "Authorization" header.',
  bot: 'Create a bot at discord.com/developers, copy the bot token. Requires admin to invite the bot.',
}

const emptyForm = { display_name: '', source_type: 'discord', auth_type: 'user_token', token: '', channels: '' }

export default function DataSources() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ ...emptyForm })

  const { data: sources } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => axios.get('/api/v1/sources').then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: (payload: object) => axios.post('/api/v1/sources', payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources'] })
      setOpen(false)
      setForm({ ...emptyForm })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => axios.delete(`/api/v1/sources/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const credentials: Record<string, string> = {}
    if (form.auth_type === 'bot') credentials.bot_token = form.token
    else credentials.user_token = form.token
    if (form.channels) credentials.channel_ids = form.channels

    createMutation.mutate({
      source_type: form.source_type,
      display_name: form.display_name,
      auth_type: form.auth_type,
      credentials,
    })
  }

  const platformIcon = (type: string) => {
    const colors: Record<string, string> = {
      discord: 'bg-indigo-500/10 text-indigo-500',
      twitter: 'bg-sky-500/10 text-sky-500',
      reddit: 'bg-orange-500/10 text-orange-500',
    }
    return colors[type] || 'bg-muted text-muted-foreground'
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">Connect Discord, Twitter, or Reddit for signal ingestion</p>
        </div>
        <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setForm({ ...emptyForm }) }}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" /> Add Source
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <form onSubmit={handleSubmit}>
              <DialogHeader>
                <DialogTitle>Add Data Source</DialogTitle>
                <DialogDescription>Configure a new message source for signal ingestion.</DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid gap-2">
                  <Label htmlFor="ds-name">Display Name</Label>
                  <Input
                    id="ds-name"
                    required
                    value={form.display_name}
                    onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                    placeholder="e.g. Trading Alerts Server"
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Platform</Label>
                  <Select value={form.source_type} onValueChange={(v) => setForm({ ...form, source_type: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="discord">Discord</SelectItem>
                      <SelectItem value="twitter">Twitter</SelectItem>
                      <SelectItem value="reddit">Reddit</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {form.source_type === 'discord' && (
                  <>
                    <div className="grid gap-2">
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
                    <div className="grid gap-2">
                      <Label htmlFor="ds-token">{form.auth_type === 'bot' ? 'Bot Token' : 'User Token'}</Label>
                      <Input
                        id="ds-token"
                        required
                        type="password"
                        value={form.token}
                        onChange={(e) => setForm({ ...form, token: e.target.value })}
                        placeholder={form.auth_type === 'bot' ? 'Bot token from Developer Portal' : 'Your Discord user token'}
                        className="font-mono"
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="ds-channels">
                        Channel IDs <span className="text-muted-foreground font-normal">(comma-separated, optional)</span>
                      </Label>
                      <Input
                        id="ds-channels"
                        value={form.channels}
                        onChange={(e) => setForm({ ...form, channels: e.target.value })}
                        placeholder="e.g. 1234567890,9876543210"
                        className="font-mono"
                      />
                    </div>
                  </>
                )}

                {form.source_type !== 'discord' && (
                  <div className="grid gap-2">
                    <Label htmlFor="ds-api-token">API Token</Label>
                    <Input
                      id="ds-api-token"
                      required
                      type="password"
                      value={form.token}
                      onChange={(e) => setForm({ ...form, token: e.target.value })}
                      placeholder="API token or access key"
                      className="font-mono"
                    />
                  </div>
                )}
              </div>
              <DialogFooter>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Save Source
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {(!sources || sources.length === 0) && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Database className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-muted-foreground">No data sources configured</p>
            <p className="text-sm text-muted-foreground/70 mt-1">Click &quot;Add Source&quot; to connect your first signal source.</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(sources || []).map((s) => (
          <Card key={s.id} className="group relative">
            <CardContent className="p-5">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${platformIcon(s.source_type)}`}>
                    <Database className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">{s.display_name}</h3>
                    <p className="text-xs text-muted-foreground capitalize">{s.source_type}</p>
                  </div>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity">
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onClick={() => deleteMutation.mutate(s.id)}
                    >
                      <Trash2 className="mr-2 h-4 w-4" /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <Badge variant={s.connection_status === 'CONNECTED' ? 'success' : 'secondary'}>
                  {s.connection_status}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {s.auth_type === 'bot' ? 'Bot' : 'User Token'}
                </Badge>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
