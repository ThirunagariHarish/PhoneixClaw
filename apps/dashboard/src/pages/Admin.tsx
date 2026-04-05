/**
 * Admin page — user management, API keys, audit log, roles.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
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
import { Key, Shield, RotateCw, Eye, EyeOff, Plus, Pencil, Trash2 } from 'lucide-react'

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

const ROLES = ['admin', 'manager', 'trader', 'viewer']

function makeUserColumns(onEdit: (u: User) => void, onDelete: (u: User) => void): Column<User>[] {
  return [
    { id: 'name', header: 'Name', cell: (r) => r.name ?? '—' },
    { id: 'email', header: 'Email', accessor: 'email' },
    { id: 'role', header: 'Role', cell: (r) => <Badge variant="outline">{r.role}</Badge> },
    { id: 'last_login', header: 'Last Login', cell: (r) => r.last_login ? new Date(r.last_login).toLocaleString() : '—' },
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

export default function AdminPage() {
  const queryClient = useQueryClient()
  const [keyVisibility, setKeyVisibility] = useState<Record<string, boolean>>({})
  const [addUserOpen, setAddUserOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [userToDelete, setUserToDelete] = useState<User | null>(null)
  const [addForm, setAddForm] = useState({ email: '', password: '', name: '', role: 'trader' })
  const [editForm, setEditForm] = useState({ name: '', role: 'trader', is_active: true })
  const [formError, setFormError] = useState('')

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
          user: e.user_id ?? '—',
          action: e.action,
          resource: e.target_type,
          timestamp: e.created_at,
        }))
      } catch {
        return []
      }
    },
  })

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

        <TabsContent value="keys" className="mt-4">
          <div className="space-y-4">
            {apiKeys.map((k) => (
              <FlexCard
                key={k.id}
                title={k.name}
                action={
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setKeyVisibility((v) => ({ ...v, [k.id]: !v[k.id] }))}>
                      {keyVisibility[k.id] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                    <Button size="sm" variant="ghost"><RotateCw className="h-4 w-4" /></Button>
                  </div>
                }
              >
                <div className="flex items-center gap-2 font-mono text-sm">
                  <Key className="h-4 w-4 text-muted-foreground" />
                  {keyVisibility[k.id] ? k.masked.replace('••••', 'xxxx') : k.masked}
                </div>
                <p className="text-xs text-muted-foreground mt-1">Last used: {new Date(k.last_used).toLocaleString()}</p>
              </FlexCard>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="audit" className="mt-4">
          <div className="overflow-x-auto">
            <DataTable columns={auditColumns} data={audit as (AuditEntry & Record<string, unknown>)[]} emptyMessage="No audit entries" />
          </div>
        </TabsContent>

        <TabsContent value="roles" className="mt-4">
          <div className="flex flex-wrap gap-2">
            {ROLES.map((r) => (
              <FlexCard key={r} className="w-full sm:w-48">
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4 text-primary" />
                  <span className="font-medium capitalize">{r}</span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">Manage permissions</p>
              </FlexCard>
            ))}
          </div>
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
    </div>
  )
}
