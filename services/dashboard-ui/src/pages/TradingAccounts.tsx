import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Plus, Wallet, MoreVertical, Trash2, Loader2 } from 'lucide-react'

interface Account {
  id: string
  display_name: string
  paper_mode: boolean
  broker_type: string
  health_status: string
}

const emptyForm = { display_name: '', broker_type: 'alpaca', paper_mode: true, api_key: '', api_secret: '' }

export default function TradingAccounts() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ ...emptyForm })
  const [error, setError] = useState<string | null>(null)

  const { data: accounts, isLoading: accountsLoading, isError: accountsError, refetch } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => axios.get('/api/v1/accounts').then((r) => r.data),
  })

  useEffect(() => {
    if (error) {
      const t = setTimeout(() => setError(null), 5000)
      return () => clearTimeout(t)
    }
  }, [error])

  const createMutation = useMutation({
    mutationFn: (payload: object) => axios.post('/api/v1/accounts', payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['accounts'] })
      setOpen(false)
      setForm({ ...emptyForm })
      setError(null)
    },
    onError: () => setError('Failed to create account. Please check your credentials.'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => axios.delete(`/api/v1/accounts/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['accounts'] }); setError(null) },
    onError: () => setError('Failed to delete account.'),
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, paper_mode }: { id: string; paper_mode: boolean }) =>
      axios.patch(`/api/v1/accounts/${id}`, { paper_mode }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['accounts'] }); setError(null) },
    onError: () => setError('Failed to update trading mode.'),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    createMutation.mutate({
      display_name: form.display_name,
      broker_type: form.broker_type,
      paper_mode: form.paper_mode,
      credentials: { api_key: form.api_key, api_secret: form.api_secret },
    })
  }

  const brokerColor = (type: string) => {
    const m: Record<string, string> = {
      alpaca: 'bg-yellow-500/10 text-yellow-500',
      interactive_brokers: 'bg-red-500/10 text-red-500',
    }
    return m[type] || 'bg-muted text-muted-foreground'
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">Connect and manage your brokerage accounts</p>
        </div>
        <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setForm({ ...emptyForm }) }}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" /> Add Account
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <form onSubmit={handleSubmit}>
              <DialogHeader>
                <DialogTitle>Add Trading Account</DialogTitle>
                <DialogDescription>Connect a brokerage account for trade execution.</DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid gap-2">
                  <Label htmlFor="ta-name">Display Name</Label>
                  <Input
                    id="ta-name"
                    required
                    value={form.display_name}
                    onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                    placeholder="e.g. My Alpaca Paper"
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Broker</Label>
                  <Select value={form.broker_type} onValueChange={(v) => setForm({ ...form, broker_type: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="alpaca">Alpaca</SelectItem>
                      <SelectItem value="interactive_brokers">Interactive Brokers</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div>
                    <Label>Paper Trading</Label>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {form.paper_mode ? 'Using simulated money — no real trades' : 'Live mode — real money at risk'}
                    </p>
                  </div>
                  <Switch checked={form.paper_mode} onCheckedChange={(v) => setForm({ ...form, paper_mode: v })} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ta-key">API Key</Label>
                  <Input
                    id="ta-key"
                    required
                    type="password"
                    value={form.api_key}
                    onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                    placeholder="Your API key"
                    className="font-mono"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ta-secret">API Secret</Label>
                  <Input
                    id="ta-secret"
                    required
                    type="password"
                    value={form.api_secret}
                    onChange={(e) => setForm({ ...form, api_secret: e.target.value })}
                    placeholder="Your API secret"
                    className="font-mono"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Save Account
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-400 flex items-center justify-between">
          <span>{error}</span>
          <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setError(null)}>Dismiss</Button>
        </div>
      )}

      {accountsLoading && (
        <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      )}

      {accountsError && (
        <Card className="border-destructive/30">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-destructive font-medium">Failed to load accounts</p>
            <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>Retry</Button>
          </CardContent>
        </Card>
      )}

      {!accountsLoading && !accountsError && (!accounts || accounts.length === 0) && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Wallet className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-muted-foreground">No trading accounts configured</p>
            <p className="text-sm text-muted-foreground/70 mt-1">Click &quot;Add Account&quot; to connect your first brokerage.</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(accounts || []).map((a) => (
          <Card key={a.id} className="group relative">
            <CardContent className="p-5">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${brokerColor(a.broker_type)}`}>
                    <Wallet className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">{a.display_name}</h3>
                    <p className="text-xs text-muted-foreground capitalize">{a.broker_type.replace('_', ' ')}</p>
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
                      onClick={() => {
                        if (window.confirm(`Delete trading account "${a.display_name}"? This cannot be undone.`)) {
                          deleteMutation.mutate(a.id)
                        }
                      }}
                    >
                      <Trash2 className="mr-2 h-4 w-4" /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant={a.paper_mode ? 'warning' : 'success'}>
                    {a.paper_mode ? 'Paper' : 'Live'}
                  </Badge>
                  <Badge variant={a.health_status === 'healthy' ? 'success' : 'secondary'}>
                    {a.health_status}
                  </Badge>
                </div>
                <Switch
                  checked={!a.paper_mode}
                  onCheckedChange={(live) => toggleMutation.mutate({ id: a.id, paper_mode: !live })}
                />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
