import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Users,
  Database,
  Link2,
  ShieldCheck,
  ShieldOff,
  Loader2,
  CheckCircle2,
  XCircle,
  Wifi,
  WifiOff,
} from 'lucide-react'

interface AdminUser {
  id: string
  email: string
  name: string | null
  is_active: boolean
  is_admin: boolean
  created_at: string
  last_login: string | null
}

interface AdminSource {
  id: string
  user_id: string
  owner_email: string
  owner_name: string | null
  source_type: string
  display_name: string
  auth_type: string
  enabled: boolean
  connection_status: string
  channel_count: number
  created_at: string
}

interface AdminChannel {
  id: string
  channel_identifier: string
  display_name: string
  enabled: boolean
}

interface TradingAccount {
  id: string
  broker_type: string
  display_name: string
  paper_mode: boolean
  enabled: boolean
}

export default function Admin() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'users' | 'sources'>('users')
  const [mapDialog, setMapDialog] = useState<{
    sourceId: string
    sourceName: string
  } | null>(null)
  const [channels, setChannels] = useState<AdminChannel[]>([])
  const [selectedChannel, setSelectedChannel] = useState('')
  const [selectedAccount, setSelectedAccount] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  useEffect(() => {
    if (error) {
      const t = setTimeout(() => setError(null), 5000)
      return () => clearTimeout(t)
    }
  }, [error])

  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(null), 3000)
      return () => clearTimeout(t)
    }
  }, [success])

  const { data: users, isLoading: usersLoading } = useQuery<AdminUser[]>({
    queryKey: ['admin-users'],
    queryFn: () => axios.get('/api/v1/admin/users').then((r) => r.data),
    enabled: tab === 'users',
  })

  const { data: sources, isLoading: sourcesLoading } = useQuery<AdminSource[]>({
    queryKey: ['admin-sources'],
    queryFn: () => axios.get('/api/v1/admin/sources').then((r) => r.data),
    enabled: tab === 'sources',
  })

  const { data: myAccounts } = useQuery<TradingAccount[]>({
    queryKey: ['accounts'],
    queryFn: () => axios.get('/api/v1/accounts').then((r) => r.data),
  })

  const promoteMut = useMutation({
    mutationFn: (userId: string) => axios.post(`/api/v1/admin/users/${userId}/promote`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      setSuccess('User promoted to admin')
    },
    onError: () => setError('Failed to promote user'),
  })

  const demoteMut = useMutation({
    mutationFn: (userId: string) => axios.post(`/api/v1/admin/users/${userId}/demote`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      setSuccess('Admin access removed')
    },
    onError: () => setError('Failed to demote user'),
  })

  const mapMut = useMutation({
    mutationFn: (body: { trading_account_id: string; channel_id: string }) =>
      axios.post('/api/v1/admin/mappings', body),
    onSuccess: () => {
      setMapDialog(null)
      setSuccess('Channel mapped to your trading account')
    },
    onError: (err: unknown) => {
      const msg =
        axios.isAxiosError(err) && err.response?.data?.detail
          ? err.response.data.detail
          : 'Failed to create mapping'
      setError(msg)
    },
  })

  const openMapDialog = async (sourceId: string, sourceName: string) => {
    setError(null)
    try {
      const res = await axios.get(`/api/v1/admin/sources/${sourceId}/channels`)
      setChannels(res.data)
      setSelectedChannel('')
      setSelectedAccount('')
      setMapDialog({ sourceId, sourceName })
    } catch {
      setError('Failed to load channels')
    }
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-400 flex items-center justify-between">
          <span>{error}</span>
          <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setError(null)}>
            Dismiss
          </Button>
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-400 flex items-center justify-between">
          <span>{success}</span>
          <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setSuccess(null)}>
            Dismiss
          </Button>
        </div>
      )}

      <div className="flex gap-2">
        <Button
          variant={tab === 'users' ? 'default' : 'outline'}
          onClick={() => setTab('users')}
          className="gap-2"
        >
          <Users className="h-4 w-4" />
          Users
        </Button>
        <Button
          variant={tab === 'sources' ? 'default' : 'outline'}
          onClick={() => setTab('sources')}
          className="gap-2"
        >
          <Database className="h-4 w-4" />
          All Data Sources
        </Button>
      </div>

      {tab === 'users' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Users className="h-5 w-5" />
              All Users ({users?.length ?? 0})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {usersLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last Login</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(users ?? []).map((u) => (
                    <TableRow key={u.id}>
                      <TableCell className="font-medium">{u.email}</TableCell>
                      <TableCell>{u.name || '—'}</TableCell>
                      <TableCell>
                        {u.is_admin ? (
                          <Badge className="bg-purple-500/15 text-purple-600 border-purple-500/30 gap-1">
                            <ShieldCheck className="h-3 w-3" /> Admin
                          </Badge>
                        ) : (
                          <Badge variant="secondary">User</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {u.is_active ? (
                          <Badge variant="success" className="gap-1">
                            <CheckCircle2 className="h-3 w-3" /> Active
                          </Badge>
                        ) : (
                          <Badge variant="destructive" className="gap-1">
                            <XCircle className="h-3 w-3" /> Inactive
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {u.last_login ? new Date(u.last_login).toLocaleString() : 'Never'}
                      </TableCell>
                      <TableCell>
                        {u.is_admin ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => demoteMut.mutate(u.id)}
                            disabled={demoteMut.isPending}
                            className="text-amber-600 hover:text-amber-700 gap-1"
                          >
                            <ShieldOff className="h-3.5 w-3.5" /> Remove Admin
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => promoteMut.mutate(u.id)}
                            disabled={promoteMut.isPending}
                            className="text-purple-600 hover:text-purple-700 gap-1"
                          >
                            <ShieldCheck className="h-3.5 w-3.5" /> Make Admin
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {tab === 'sources' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Database className="h-5 w-5" />
              All Data Sources ({sources?.length ?? 0})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {sourcesLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Owner</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Channels</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(sources ?? []).map((s) => (
                    <TableRow key={s.id}>
                      <TableCell>
                        <div>
                          <p className="font-medium text-sm">{s.owner_email}</p>
                          {s.owner_name && (
                            <p className="text-xs text-muted-foreground">{s.owner_name}</p>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="font-medium">{s.display_name}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="capitalize">
                          {s.source_type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {s.connection_status === 'CONNECTED' && s.enabled ? (
                          <Badge variant="success" className="gap-1">
                            <Wifi className="h-3 w-3" /> Connected
                          </Badge>
                        ) : (
                          <Badge variant="secondary" className="gap-1">
                            <WifiOff className="h-3 w-3" /> {s.connection_status}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>{s.channel_count}</TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openMapDialog(s.id, s.display_name)}
                          className="gap-1 text-blue-600 hover:text-blue-700"
                        >
                          <Link2 className="h-3.5 w-3.5" /> Map to My Account
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      <Dialog open={!!mapDialog} onOpenChange={() => setMapDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Map Channel — {mapDialog?.sourceName}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="text-sm font-medium mb-1.5 block">Channel</label>
              <Select value={selectedChannel} onValueChange={setSelectedChannel}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a channel" />
                </SelectTrigger>
                <SelectContent>
                  {channels.map((ch) => (
                    <SelectItem key={ch.id} value={ch.id}>
                      {ch.display_name} ({ch.channel_identifier})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {channels.length === 0 && (
                <p className="text-xs text-muted-foreground mt-1">
                  No channels found. The source owner needs to add channels first.
                </p>
              )}
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">Your Trading Account</label>
              <Select value={selectedAccount} onValueChange={setSelectedAccount}>
                <SelectTrigger>
                  <SelectValue placeholder="Select your account" />
                </SelectTrigger>
                <SelectContent>
                  {(myAccounts ?? []).map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.display_name} ({a.broker_type}
                      {a.paper_mode ? ' · Paper' : ' · Live'})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMapDialog(null)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                mapMut.mutate({
                  trading_account_id: selectedAccount,
                  channel_id: selectedChannel,
                })
              }
              disabled={!selectedChannel || !selectedAccount || mapMut.isPending}
            >
              {mapMut.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create Mapping
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
