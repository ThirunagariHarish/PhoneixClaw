import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Users,
  ShieldCheck,
  ShieldOff,
  Loader2,
  CheckCircle2,
  XCircle,
  Search,
  UserCog,
  Lock,
  Eye,
  Pencil,
  Power,
  KeyRound,
} from 'lucide-react'

interface Permission {
  key: string
  label: string
  category: string
}

const PERMISSION_DEFS: Permission[] = [
  { key: 'trade_execute', label: 'Execute Trades', category: 'Trading' },
  { key: 'trade_approve', label: 'Approve / Reject Trades', category: 'Trading' },
  { key: 'trade_view', label: 'View Trades', category: 'Trading' },
  { key: 'positions_view', label: 'View Positions', category: 'Positions' },
  { key: 'positions_close', label: 'Close Positions', category: 'Positions' },
  { key: 'sources_manage', label: 'Manage Data Sources', category: 'Data Sources' },
  { key: 'sources_view', label: 'View Data Sources', category: 'Data Sources' },
  { key: 'accounts_manage', label: 'Manage Trading Accounts', category: 'Accounts' },
  { key: 'accounts_view', label: 'View Trading Accounts', category: 'Accounts' },
  { key: 'messages_view', label: 'View Raw Messages', category: 'Messages' },
  { key: 'analytics_view', label: 'View Analytics', category: 'Analytics' },
  { key: 'system_config', label: 'System Configuration', category: 'System' },
  { key: 'admin_users', label: 'Manage Users', category: 'Admin' },
  { key: 'admin_access', label: 'Access Management', category: 'Admin' },
  { key: 'kill_switch', label: 'Kill Switch Control', category: 'Admin' },
]

const PERMISSION_CATEGORIES = [...new Set(PERMISSION_DEFS.map((p) => p.category))]

interface AdminUser {
  id: string
  email: string
  name: string | null
  is_active: boolean
  is_admin: boolean
  role: string
  permissions: Record<string, boolean>
  created_at: string
  last_login: string | null
  trading_accounts_count?: number
  data_sources_count?: number
}

interface RolesResponse {
  roles: string[]
  presets: Record<string, Record<string, boolean>>
  all_permissions: string[]
}

const ROLE_COLORS: Record<string, string> = {
  admin: 'bg-red-500/15 text-red-600 border-red-500/30',
  manager: 'bg-purple-500/15 text-purple-600 border-purple-500/30',
  trader: 'bg-blue-500/15 text-blue-600 border-blue-500/30',
  viewer: 'bg-gray-500/15 text-gray-600 border-gray-500/30',
  custom: 'bg-amber-500/15 text-amber-600 border-amber-500/30',
}

const ROLE_ICONS: Record<string, React.ElementType> = {
  admin: ShieldCheck,
  manager: UserCog,
  trader: KeyRound,
  viewer: Eye,
  custom: Pencil,
}

export default function AccessManagement() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [editUser, setEditUser] = useState<AdminUser | null>(null)
  const [editPerms, setEditPerms] = useState<Record<string, boolean>>({})
  const [editRole, setEditRole] = useState('')
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

  const { data: users, isLoading } = useQuery<AdminUser[]>({
    queryKey: ['admin-users'],
    queryFn: () => axios.get('/api/v1/admin/users').then((r) => r.data),
  })

  const { data: rolesData } = useQuery<RolesResponse>({
    queryKey: ['admin-roles'],
    queryFn: () => axios.get('/api/v1/admin/roles').then((r) => r.data),
  })

  const roleMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      axios.put(`/api/v1/admin/users/${userId}/role`, { role }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      setEditUser(res.data)
      setEditPerms(res.data.permissions)
      setEditRole(res.data.role)
      showToast('success', `Role updated to ${res.data.role}`)
    },
    onError: () => showToast('error', 'Failed to update role'),
  })

  const permMut = useMutation({
    mutationFn: ({ userId, permissions }: { userId: string; permissions: Record<string, boolean> }) =>
      axios.put(`/api/v1/admin/users/${userId}/permissions`, { permissions }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      setEditUser(res.data)
      setEditPerms(res.data.permissions)
      setEditRole(res.data.role)
      showToast('success', 'Permissions saved')
    },
    onError: () => showToast('error', 'Failed to save permissions'),
  })

  const toggleMut = useMutation({
    mutationFn: (userId: string) => axios.put(`/api/v1/admin/users/${userId}/toggle-active`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      showToast('success', 'User status updated')
    },
    onError: () => showToast('error', 'Failed to toggle user status'),
  })

  function showToast(type: 'success' | 'error', msg: string) {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  function openEditor(user: AdminUser) {
    setEditUser(user)
    setEditPerms(user.permissions || {})
    setEditRole(user.role || 'trader')
  }

  function handleRoleChange(role: string) {
    if (!editUser) return
    setEditRole(role)
    if (rolesData?.presets[role]) {
      setEditPerms({ ...rolesData.presets[role] })
    }
    roleMut.mutate({ userId: editUser.id, role })
  }

  function handlePermToggle(key: string, val: boolean) {
    setEditPerms((prev) => ({ ...prev, [key]: val }))
  }

  function savePermissions() {
    if (!editUser) return
    permMut.mutate({ userId: editUser.id, permissions: editPerms })
  }

  const filtered = (users || []).filter(
    (u) =>
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      (u.name && u.name.toLowerCase().includes(search.toLowerCase())) ||
      u.role?.toLowerCase().includes(search.toLowerCase()),
  )

  const permsByCategory = PERMISSION_CATEGORIES.map((cat) => ({
    category: cat,
    permissions: PERMISSION_DEFS.filter((p) => p.category === cat),
  }))

  const enabledCount = Object.values(editPerms).filter(Boolean).length
  const totalCount = PERMISSION_DEFS.length

  return (
    <div className="space-y-6">
      {toast && (
        <div
          className={`rounded-lg border p-3 text-sm flex items-center justify-between ${
            toast.type === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
              : 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-400'
          }`}
        >
          <span>{toast.msg}</span>
          <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setToast(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-blue-500/10 p-2">
                <Users className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{users?.length ?? 0}</p>
                <p className="text-xs text-muted-foreground">Total Users</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-red-500/10 p-2">
                <ShieldCheck className="h-5 w-5 text-red-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{users?.filter((u) => u.is_admin).length ?? 0}</p>
                <p className="text-xs text-muted-foreground">Admins</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-emerald-500/10 p-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{users?.filter((u) => u.is_active).length ?? 0}</p>
                <p className="text-xs text-muted-foreground">Active</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-amber-500/10 p-2">
                <Lock className="h-5 w-5 text-amber-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{rolesData?.roles?.length ?? 0}</p>
                <p className="text-xs text-muted-foreground">Role Types</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* User Table */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <UserCog className="h-5 w-5" />
                User Access Management
              </CardTitle>
              <CardDescription className="mt-1">
                Assign roles and configure granular permissions for each user
              </CardDescription>
            </div>
            <div className="relative w-64">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search users..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Permissions</TableHead>
                  <TableHead>Last Login</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((u) => {
                  const role = u.role || 'trader'
                  const RoleIcon = ROLE_ICONS[role] || Eye
                  const enabledPerms = Object.values(u.permissions || {}).filter(Boolean).length
                  return (
                    <TableRow key={u.id}>
                      <TableCell>
                        <div>
                          <p className="font-medium text-sm">{u.name || u.email.split('@')[0]}</p>
                          <p className="text-xs text-muted-foreground">{u.email}</p>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge className={`gap-1 ${ROLE_COLORS[role] || ROLE_COLORS.viewer}`}>
                          <RoleIcon className="h-3 w-3" />
                          {role.charAt(0).toUpperCase() + role.slice(1)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {u.is_active ? (
                          <Badge variant="outline" className="gap-1 border-emerald-500/30 text-emerald-600">
                            <CheckCircle2 className="h-3 w-3" /> Active
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="gap-1 border-red-500/30 text-red-600">
                            <XCircle className="h-3 w-3" /> Disabled
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="text-sm text-muted-foreground">
                          {enabledPerms}/{totalCount} enabled
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {u.last_login ? new Date(u.last_login).toLocaleString() : 'Never'}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEditor(u)}
                            className="gap-1"
                          >
                            <Pencil className="h-3.5 w-3.5" /> Edit Access
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => toggleMut.mutate(u.id)}
                            disabled={toggleMut.isPending}
                            className={u.is_active ? 'text-red-600 hover:text-red-700' : 'text-emerald-600 hover:text-emerald-700'}
                          >
                            <Power className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      No users found
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Permission Editor Dialog */}
      <Dialog open={!!editUser} onOpenChange={() => setEditUser(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserCog className="h-5 w-5" />
              Edit Access — {editUser?.name || editUser?.email}
            </DialogTitle>
            <DialogDescription>
              Assign a role preset or customize individual permissions
            </DialogDescription>
          </DialogHeader>

          {editUser && (
            <div className="space-y-6 py-2">
              {/* Role Assignment */}
              <div>
                <label className="text-sm font-medium mb-2 block">Role</label>
                <div className="flex items-center gap-3">
                  <Select value={editRole} onValueChange={handleRoleChange}>
                    <SelectTrigger className="w-48">
                      <SelectValue placeholder="Select role" />
                    </SelectTrigger>
                    <SelectContent>
                      {(rolesData?.roles || []).map((r) => (
                        <SelectItem key={r} value={r}>
                          {r.charAt(0).toUpperCase() + r.slice(1)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <span className="text-sm text-muted-foreground">
                    {enabledCount}/{totalCount} permissions enabled
                  </span>
                  {roleMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Selecting a role applies its default permissions. You can then customize individual toggles below.
                </p>
              </div>

              <Separator />

              {/* Granular Permissions */}
              <div>
                <label className="text-sm font-medium mb-3 block">Permissions</label>
                <div className="space-y-4">
                  {permsByCategory.map(({ category, permissions }) => (
                    <div key={category} className="rounded-lg border p-3">
                      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                        {category}
                      </h4>
                      <div className="space-y-2">
                        {permissions.map((p) => (
                          <div key={p.key} className="flex items-center justify-between">
                            <label htmlFor={p.key} className="text-sm cursor-pointer">
                              {p.label}
                            </label>
                            <Switch
                              id={p.key}
                              checked={!!editPerms[p.key]}
                              onCheckedChange={(v) => handlePermToggle(p.key, v)}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setEditUser(null)}>
              Cancel
            </Button>
            <Button onClick={savePermissions} disabled={permMut.isPending}>
              {permMut.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save Permissions
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
