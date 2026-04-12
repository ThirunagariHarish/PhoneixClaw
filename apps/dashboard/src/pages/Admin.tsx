/**
 * Admin page — user management, API keys, audit log, roles, invitations.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { toast } from 'sonner'
import { PageHeader } from '@/components/ui/PageHeader'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { FlexCard } from '@/components/ui/FlexCard'
import { MetricCard } from '@/components/ui/MetricCard'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Key, Shield, RotateCw, Eye, EyeOff, Plus, Pencil, Trash2, Copy, Ticket,
  Check, X, Calendar, AlertCircle,
} from 'lucide-react'

interface User {
  id: string
  email: string
  name: string | null
  role: string
  is_active?: boolean
  last_login?: string
}

interface ApiKey {
  id: string
  name: string
  masked: string
  last_used: string
}

interface AuditEntry {
  id: string
  user: string
  action: string
  resource: string
  timestamp: string
}

interface InvitationEntry {
  id: string
  code: string
  created_by: string | null
  used_by: string | null
  status: 'available' | 'used' | 'expired'
  created_at: string | null
  expires_at: string | null
  used_at: string | null
}

const ROLES = ['admin', 'manager', 'trader', 'viewer']

// A1: RBAC Permission definitions
const PERMISSIONS = [
  { id: 'manage_agents', label: 'Manage Agents' },
  { id: 'execute_trades', label: 'Execute Trades' },
  { id: 'view_trades', label: 'View Trades' },
  { id: 'manage_users', label: 'Manage Users' },
  { id: 'manage_settings', label: 'Manage Settings' },
]

const DEFAULT_ROLE_PERMISSIONS: Record<string, string[]> = {
  admin: ['manage_agents', 'execute_trades', 'view_trades', 'manage_users', 'manage_settings'],
  manager: ['manage_agents', 'execute_trades', 'view_trades', 'manage_settings'],
  trader: ['execute_trades', 'view_trades'],
  viewer: ['view_trades'],
}

// A4: Audit log action types for filter dropdown
const AUDIT_ACTION_TYPES = [
  'all',
  'create_user',
  'update_user',
  'delete_user',
  'login',
  'logout',
  'create_agent',
  'execute_trade',
  'update_settings',
  'generate_api_key',
  'rotate_api_key',
  'revoke_api_key',
]

function makeUserColumns(onEdit: (u: User) => void, onDelete: (u: User) => void): Column<User>[] {
  return [
    { id: 'name', header: 'Name', cell: (r) => r.name ?? '--' },
    { id: 'email', header: 'Email', accessor: 'email' },
    { id: 'role', header: 'Role', cell: (r) => <Badge variant="outline">{r.role}</Badge> },
    { id: 'last_login', header: 'Last Login', cell: (r) => r.last_login ? new Date(r.last_login).toLocaleString() : '--' },
    {
      id: 'actions',
      header: 'Actions',
      cell: (r) => (
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => onEdit(r)} aria-label="Edit user">
            <Pencil className="h-4 w-4" />
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onDelete(r)} aria-label="Delete user" className="text-destructive hover:text-destructive">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ]
}

const auditColumns: Column<AuditEntry>[] = [
  { id: 'timestamp', header: 'Time', cell: (r) => new Date(r.timestamp).toLocaleString() },
  { id: 'user', header: 'User', accessor: 'user' },
  { id: 'action', header: 'Action', accessor: 'action' },
  { id: 'resource', header: 'Resource', accessor: 'resource' },
]

// A1: RBAC Permission Editor component
function RBACPermissionEditor() {
  const queryClient = useQueryClient()

  const { data: rolePermissions, isLoading } = useQuery<Record<string, string[]>>({
    queryKey: ['admin-role-permissions'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/admin/roles/permissions')
        return res.data as Record<string, string[]>
      } catch {
        return { ...DEFAULT_ROLE_PERMISSIONS }
      }
    },
  })

  const [localPerms, setLocalPerms] = useState<Record<string, string[]> | null>(null)

  // Use local state if user has made changes, otherwise use fetched data
  const perms = localPerms ?? rolePermissions ?? DEFAULT_ROLE_PERMISSIONS

  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  function togglePermission(role: string, permId: string) {
    const current = perms[role] ?? []
    const updated = current.includes(permId)
      ? current.filter(p => p !== permId)
      : [...current, permId]
    const newPerms = { ...perms, [role]: updated }
    setLocalPerms(newPerms)
    setDirty(true)
  }

  async function handleSave() {
    setSaving(true)
    try {
      await api.put('/api/v2/admin/roles/permissions', perms)
      toast.success('Permissions saved')
      setDirty(false)
      queryClient.invalidateQueries({ queryKey: ['admin-role-permissions'] })
    } catch {
      toast.error('Failed to save permissions')
    } finally {
      setSaving(false)
    }
  }

  if (isLoading) {
    return <div className="text-sm text-muted-foreground py-8 text-center">Loading permissions...</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Permission Matrix</h3>
        <Button
          size="sm"
          onClick={handleSave}
          disabled={!dirty || saving}
        >
          {saving ? 'Saving...' : 'Save Changes'}
        </Button>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">Role</th>
              {PERMISSIONS.map(p => (
                <th key={p.id} className="px-4 py-3 text-center font-medium text-muted-foreground text-xs">
                  {p.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {ROLES.map(role => (
              <tr key={role} className="hover:bg-muted/30">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Shield className="h-4 w-4 text-primary" />
                    <span className="font-medium capitalize">{role}</span>
                  </div>
                </td>
                {PERMISSIONS.map(perm => {
                  const hasPermission = (perms[role] ?? []).includes(perm.id)
                  return (
                    <td key={perm.id} className="px-4 py-3 text-center">
                      <button
                        onClick={() => togglePermission(role, perm.id)}
                        className={`inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors ${
                          hasPermission
                            ? 'bg-emerald-500/20 text-emerald-500 hover:bg-emerald-500/30'
                            : 'bg-muted/50 text-muted-foreground/30 hover:bg-muted hover:text-muted-foreground'
                        }`}
                        aria-label={`${hasPermission ? 'Revoke' : 'Grant'} ${perm.label} for ${role}`}
                      >
                        {hasPermission ? <Check className="h-4 w-4" /> : <X className="h-3.5 w-3.5" />}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dirty && (
        <p className="text-xs text-amber-500 flex items-center gap-1">
          <AlertCircle className="h-3 w-3" />
          Unsaved changes
        </p>
      )}
    </div>
  )
}

// A3: API Key CRUD component
function ApiKeysTab() {
  const queryClient = useQueryClient()
  const [keyVisibility, setKeyVisibility] = useState<Record<string, boolean>>({})
  const [createOpen, setCreateOpen] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [rotateTarget, setRotateTarget] = useState<ApiKey | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null)

  const { data: apiKeys = [] } = useQuery<ApiKey[]>({
    queryKey: ['admin-api-keys'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/admin/api-keys')
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const createMutation = useMutation({
    mutationFn: async (name: string) => {
      const res = await api.post('/api/v2/admin/api-keys', { name })
      return res.data as { key: string }
    },
    onSuccess: (data) => {
      setCreatedKey(data.key)
      setNewKeyName('')
      queryClient.invalidateQueries({ queryKey: ['admin-api-keys'] })
      toast.success('API key created')
    },
    onError: () => toast.error('Failed to create API key'),
  })

  const rotateMutation = useMutation({
    mutationFn: async (id: string) => {
      const res = await api.post(`/api/v2/admin/api-keys/${id}/rotate`)
      return res.data as { key: string }
    },
    onSuccess: (data) => {
      setCreatedKey(data.key)
      setRotateTarget(null)
      queryClient.invalidateQueries({ queryKey: ['admin-api-keys'] })
      toast.success('API key rotated')
    },
    onError: () => toast.error('Failed to rotate API key'),
  })

  const revokeMutation = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/api/v2/admin/api-keys/${id}`)
    },
    onSuccess: () => {
      setRevokeTarget(null)
      queryClient.invalidateQueries({ queryKey: ['admin-api-keys'] })
      toast.success('API key revoked')
    },
    onError: () => toast.error('Failed to revoke API key'),
  })

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => { setCreateOpen(true); setCreatedKey(null); setNewKeyName('') }}>
          <Plus className="h-4 w-4 mr-2" />
          Create API Key
        </Button>
      </div>

      {apiKeys.map((k) => (
        <FlexCard
          key={k.id}
          title={k.name}
          action={
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => setKeyVisibility((v) => ({ ...v, [k.id]: !v[k.id] }))}>
                {keyVisibility[k.id] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRotateTarget(k)} title="Rotate key">
                <RotateCw className="h-4 w-4" />
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRevokeTarget(k)} title="Revoke key" className="text-destructive hover:text-destructive">
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          }
        >
          <div className="flex items-center gap-2 font-mono text-sm">
            <Key className="h-4 w-4 text-muted-foreground" />
            {keyVisibility[k.id] ? k.masked.replace('****', 'xxxx') : k.masked}
          </div>
          <p className="text-xs text-muted-foreground mt-1">Last used: {new Date(k.last_used).toLocaleString()}</p>
        </FlexCard>
      ))}

      {apiKeys.length === 0 && (
        <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
          No API keys. Create one to get started.
        </div>
      )}

      {/* Create API Key Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{createdKey ? 'API Key Created' : 'Create API Key'}</DialogTitle>
            <DialogDescription>
              {createdKey
                ? 'Copy this key now. It will not be shown again.'
                : 'Give your API key a descriptive name.'}
            </DialogDescription>
          </DialogHeader>
          {createdKey ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-3 rounded-lg border border-input bg-muted">
                <code className="flex-1 font-mono text-sm break-all">{createdKey}</code>
                <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(createdKey).then(() => toast.success('Copied'))}>
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <DialogFooter>
                <Button onClick={() => { setCreateOpen(false); setCreatedKey(null) }}>Done</Button>
              </DialogFooter>
            </div>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); if (newKeyName.trim()) createMutation.mutate(newKeyName.trim()) }} className="space-y-4">
              <div>
                <label htmlFor="key-name" className="block text-sm font-medium mb-1">Key Name</label>
                <input
                  id="key-name"
                  type="text"
                  required
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g. Production Backend"
                  className="w-full px-3 py-2 rounded-lg border border-input bg-background"
                />
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
                <Button type="submit" disabled={!newKeyName.trim() || createMutation.isPending}>
                  {createMutation.isPending ? 'Creating...' : 'Create'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* Rotate Confirm Dialog */}
      <Dialog open={!!rotateTarget} onOpenChange={(open) => { if (!open) setRotateTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rotate API Key</DialogTitle>
            <DialogDescription>
              Rotate &quot;{rotateTarget?.name}&quot;? The current key will be invalidated immediately.
            </DialogDescription>
          </DialogHeader>
          {createdKey ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">New key (copy now, shown once):</p>
              <div className="flex items-center gap-2 p-3 rounded-lg border border-input bg-muted">
                <code className="flex-1 font-mono text-sm break-all">{createdKey}</code>
                <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(createdKey).then(() => toast.success('Copied'))}>
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <DialogFooter>
                <Button onClick={() => { setRotateTarget(null); setCreatedKey(null) }}>Done</Button>
              </DialogFooter>
            </div>
          ) : (
            <DialogFooter>
              <Button variant="outline" onClick={() => setRotateTarget(null)}>Cancel</Button>
              <Button
                variant="destructive"
                onClick={() => rotateTarget && rotateMutation.mutate(rotateTarget.id)}
                disabled={rotateMutation.isPending}
              >
                {rotateMutation.isPending ? 'Rotating...' : 'Rotate'}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>

      {/* Revoke Confirm Dialog */}
      <Dialog open={!!revokeTarget} onOpenChange={(open) => { if (!open) setRevokeTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke API Key</DialogTitle>
            <DialogDescription>
              Revoke &quot;{revokeTarget?.name}&quot;? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevokeTarget(null)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={() => revokeTarget && revokeMutation.mutate(revokeTarget.id)}
              disabled={revokeMutation.isPending}
            >
              {revokeMutation.isPending ? 'Revoking...' : 'Revoke'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// A4: Audit Log with Filters
function AuditLogTab() {
  const [userFilter, setUserFilter] = useState('all')
  const [actionFilter, setActionFilter] = useState('all')
  const [auditDateFrom, setAuditDateFrom] = useState('')
  const [auditDateTo, setAuditDateTo] = useState('')

  const params = new URLSearchParams()
  if (userFilter !== 'all') params.set('user_id', userFilter)
  if (actionFilter !== 'all') params.set('action', actionFilter)
  if (auditDateFrom) params.set('date_from', auditDateFrom)
  if (auditDateTo) params.set('date_to', auditDateTo)

  const { data: audit = [] } = useQuery<AuditEntry[]>({
    queryKey: ['admin-audit', userFilter, actionFilter, auditDateFrom, auditDateTo],
    queryFn: async () => {
      try {
        const url = params.toString()
          ? `/api/v2/admin/audit-log?${params.toString()}`
          : '/api/v2/admin/audit-log'
        const res = await api.get(url)
        const list = Array.isArray(res.data) ? res.data : []
        return list.map((e: { id: string; user_id: string | null; action: string; target_type: string; created_at: string }) => ({
          id: e.id,
          user: e.user_id ?? '--',
          action: e.action,
          resource: e.target_type,
          timestamp: e.created_at,
        }))
      } catch {
        return []
      }
    },
  })

  const { data: users = [] } = useQuery<User[]>({
    queryKey: ['admin-users'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/admin/users')
        return Array.isArray(res.data) ? res.data : []
      } catch {
        return []
      }
    },
  })

  return (
    <div className="space-y-4">
      {/* A4: Filter controls */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-3">
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground font-medium">User</label>
          <select
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            className="bg-background border border-border rounded-lg px-2 py-1.5 text-sm"
          >
            <option value="all">All users</option>
            {users.map(u => (
              <option key={u.id} value={u.id}>{u.email}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground font-medium">Action</label>
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className="bg-background border border-border rounded-lg px-2 py-1.5 text-sm"
          >
            {AUDIT_ACTION_TYPES.map(a => (
              <option key={a} value={a}>{a === 'all' ? 'All actions' : a.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <Calendar className="h-4 w-4 text-muted-foreground" />
          <input
            type="date"
            value={auditDateFrom}
            onChange={(e) => setAuditDateFrom(e.target.value)}
            className="bg-background border border-border rounded-lg px-2 py-1.5 text-sm"
            placeholder="From"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <input
            type="date"
            value={auditDateTo}
            onChange={(e) => setAuditDateTo(e.target.value)}
            className="bg-background border border-border rounded-lg px-2 py-1.5 text-sm"
            placeholder="To"
          />
        </div>
        {(userFilter !== 'all' || actionFilter !== 'all' || auditDateFrom || auditDateTo) && (
          <button
            onClick={() => { setUserFilter('all'); setActionFilter('all'); setAuditDateFrom(''); setAuditDateTo('') }}
            className="text-xs text-muted-foreground hover:text-foreground underline"
          >
            Clear filters
          </button>
        )}
        <span className="ml-auto text-xs text-muted-foreground">{audit.length} entries</span>
      </div>

      <div className="overflow-x-auto">
        <DataTable columns={auditColumns} data={audit as (AuditEntry & Record<string, unknown>)[]} emptyMessage="No audit entries" />
      </div>
    </div>
  )
}

export default function AdminPage() {
  const queryClient = useQueryClient()
  const [addUserOpen, setAddUserOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [userToDelete, setUserToDelete] = useState<User | null>(null)
  const [addForm, setAddForm] = useState({ email: '', password: '', name: '', role: 'trader' })
  const [editForm, setEditForm] = useState({ name: '', role: 'trader', is_active: true })
  const [formError, setFormError] = useState('')
  const [generatedCode, setGeneratedCode] = useState<string | null>(null)
  const [generateDialogOpen, setGenerateDialogOpen] = useState(false)

  const { data: users = [] } = useQuery<User[]>({
    queryKey: ['admin-users'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/admin/users')
        return Array.isArray(res.data) ? res.data : []
      } catch {
        return []
      }
    },
  })

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault()
    setFormError('')
    try {
      await api.post('/api/v2/admin/users', {
        email: addForm.email,
        password: addForm.password,
        name: addForm.name || undefined,
        role: addForm.role,
      })
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      setAddUserOpen(false)
      setAddForm({ email: '', password: '', name: '', role: 'trader' })
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'response' in err && typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
        ? (err as { response: { data: { detail: string } } }).response.data.detail
        : 'Failed to create user'
      setFormError(msg)
    }
  }

  async function handleUpdateUser(e: React.FormEvent) {
    e.preventDefault()
    if (!editingUser) return
    setFormError('')
    try {
      await api.put(`/api/v2/admin/users/${editingUser.id}`, {
        name: editForm.name || undefined,
        role: editForm.role,
        is_active: editForm.is_active,
      })
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      setEditingUser(null)
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'response' in err && typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
        ? (err as { response: { data: { detail: string } } }).response.data.detail
        : 'Failed to update user'
      setFormError(msg)
    }
  }

  async function handleDeleteUser(user: User) {
    try {
      await api.delete(`/api/v2/admin/users/${user.id}`)
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      setUserToDelete(null)
    } catch {
      setFormError('Failed to delete user')
    }
  }

  function openEdit(user: User) {
    setEditingUser(user)
    setEditForm({
      name: user.name ?? '',
      role: user.role,
      is_active: user.is_active ?? true,
    })
    setFormError('')
  }

  const { data: apiKeys = [] } = useQuery<ApiKey[]>({
    queryKey: ['admin-api-keys'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/admin/api-keys')
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: audit = [] } = useQuery<AuditEntry[]>({
    queryKey: ['admin-audit'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/admin/audit-log')
        const list = Array.isArray(res.data) ? res.data : []
        return list.map((e: { id: string; user_id: string | null; action: string; target_type: string; created_at: string }) => ({
          id: e.id,
          user: e.user_id ?? '--',
          action: e.action,
          resource: e.target_type,
          timestamp: e.created_at,
        }))
      } catch {
        return []
      }
    },
  })

  const { data: invitations = [] } = useQuery<InvitationEntry[]>({
    queryKey: ['admin-invitations'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/admin/invitations')
        return Array.isArray(res.data) ? res.data : []
      } catch {
        return []
      }
    },
  })

  async function handleGenerateInvitation() {
    try {
      const res = await api.post('/api/v2/admin/invitations')
      setGeneratedCode(res.data.code)
      setGenerateDialogOpen(true)
      queryClient.invalidateQueries({ queryKey: ['admin-invitations'] })
    } catch {
      setFormError('Failed to generate invitation')
    }
  }

  async function handleDeleteInvitation(id: string) {
    try {
      await api.delete(`/api/v2/admin/invitations/${id}`)
      queryClient.invalidateQueries({ queryKey: ['admin-invitations'] })
    } catch {
      setFormError('Failed to delete invitation')
    }
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Shield} title="Admin" description="User management, API keys, and audit log" />

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <MetricCard title="Users" value={users.length} />
        <MetricCard title="API Keys" value={apiKeys.length} />
        <MetricCard title="Roles" value={ROLES.length} />
        <MetricCard title="Audit Events" value={audit.length} />
      </div>

      <Tabs defaultValue="users">
        <TabsList className="flex flex-wrap">
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="keys">API Key Vault</TabsTrigger>
          <TabsTrigger value="audit">Audit Log</TabsTrigger>
          <TabsTrigger value="invitations">Invitations</TabsTrigger>
          <TabsTrigger value="roles">Roles</TabsTrigger>
        </TabsList>

        <TabsContent value="users" className="mt-4 space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => { setAddUserOpen(true); setFormError(''); setAddForm({ email: '', password: '', name: '', role: 'trader' }) }}>
              <Plus className="h-4 w-4 mr-2" />
              Add user
            </Button>
          </div>
          <div className="overflow-x-auto">
            <DataTable columns={makeUserColumns(openEdit, (u) => setUserToDelete(u))} data={users as (User & Record<string, unknown>)[]} emptyMessage="No users" />
          </div>
        </TabsContent>

        {/* A3: API Keys tab with full CRUD */}
        <TabsContent value="keys" className="mt-4">
          <ApiKeysTab />
        </TabsContent>

        {/* A4: Audit Log with filters */}
        <TabsContent value="audit" className="mt-4">
          <AuditLogTab />
        </TabsContent>

        <TabsContent value="invitations" className="mt-4 space-y-4">
          <div className="flex justify-end">
            <Button onClick={handleGenerateInvitation}>
              <Ticket className="h-4 w-4 mr-2" />
              Generate Invitation
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="pb-2 font-medium">Code</th>
                  <th className="pb-2 font-medium">Created By</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium">Created At</th>
                  <th className="pb-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {invitations.length === 0 && (
                  <tr><td colSpan={5} className="py-8 text-center text-muted-foreground">No invitations</td></tr>
                )}
                {invitations.map((inv) => (
                  <tr key={inv.id} className="border-b border-border/50">
                    <td className="py-2 font-mono text-xs">{inv.code}</td>
                    <td className="py-2">{inv.created_by ?? '--'}</td>
                    <td className="py-2">
                      <Badge variant={inv.status === 'available' ? 'default' : inv.status === 'used' ? 'secondary' : 'destructive'}>
                        {inv.status}
                      </Badge>
                    </td>
                    <td className="py-2">{inv.created_at ? new Date(inv.created_at).toLocaleString() : '--'}</td>
                    <td className="py-2">
                      {inv.status === 'available' && (
                        <Button size="sm" variant="ghost" onClick={() => handleDeleteInvitation(inv.id)} className="text-destructive hover:text-destructive">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* A1: Roles tab with RBAC Permission Editor */}
        <TabsContent value="roles" className="mt-4">
          <RBACPermissionEditor />
        </TabsContent>
      </Tabs>

      <Dialog open={addUserOpen} onOpenChange={(open) => { setAddUserOpen(open); if (!open) setFormError('') }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add user</DialogTitle>
            <DialogDescription>Create a new user. Password must be at least 8 characters.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateUser} className="space-y-4">
            <div>
              <label htmlFor="add-email" className="block text-sm font-medium mb-1">Email</label>
              <input id="add-email" type="email" required value={addForm.email} onChange={(e) => setAddForm((f) => ({ ...f, email: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-input bg-background" />
            </div>
            <div>
              <label htmlFor="add-password" className="block text-sm font-medium mb-1">Password</label>
              <input id="add-password" type="password" required minLength={8} value={addForm.password} onChange={(e) => setAddForm((f) => ({ ...f, password: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-input bg-background" />
            </div>
            <div>
              <label htmlFor="add-name" className="block text-sm font-medium mb-1">Name (optional)</label>
              <input id="add-name" type="text" value={addForm.name} onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-input bg-background" />
            </div>
            <div>
              <label htmlFor="add-role" className="block text-sm font-medium mb-1">Role</label>
              <select id="add-role" value={addForm.role} onChange={(e) => setAddForm((f) => ({ ...f, role: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-input bg-background">
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAddUserOpen(false)}>Cancel</Button>
              <Button type="submit">Create</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!editingUser} onOpenChange={(open) => { if (!open) setEditingUser(null); setFormError('') }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit user</DialogTitle>
            <DialogDescription>{editingUser?.email}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleUpdateUser} className="space-y-4">
            <div>
              <label htmlFor="edit-name" className="block text-sm font-medium mb-1">Name</label>
              <input id="edit-name" type="text" value={editForm.name} onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-input bg-background" />
            </div>
            <div>
              <label htmlFor="edit-role" className="block text-sm font-medium mb-1">Role</label>
              <select id="edit-role" value={editForm.role} onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-input bg-background">
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <input id="edit-active" type="checkbox" checked={editForm.is_active} onChange={(e) => setEditForm((f) => ({ ...f, is_active: e.target.checked }))} className="rounded border-input" />
              <label htmlFor="edit-active" className="text-sm font-medium">Active</label>
            </div>
            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEditingUser(null)}>Cancel</Button>
              <Button type="submit">Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!userToDelete} onOpenChange={(open) => { if (!open) setUserToDelete(null); setFormError('') }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete user</DialogTitle>
            <DialogDescription>
              Delete user {userToDelete?.email}? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setUserToDelete(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => userToDelete && handleDeleteUser(userToDelete)}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={generateDialogOpen} onOpenChange={setGenerateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invitation Code Generated</DialogTitle>
            <DialogDescription>Share this code with the person you want to invite. It can only be used once.</DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-input bg-muted">
            <code className="flex-1 font-mono text-sm break-all">{generatedCode}</code>
            <Button size="sm" variant="ghost" onClick={() => { if (generatedCode) navigator.clipboard.writeText(generatedCode) }}>
              <Copy className="h-4 w-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setGenerateDialogOpen(false)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
