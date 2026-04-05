/**
 * Network / Infrastructure page.
 * - Grid of Claude Code instance cards with live health status.
 * - Click an instance to open a full detail dashboard: system health,
 *   agent list, chat, and activity feed panels.
 * - Connection guide for VPS and local deployments.
 * - All colors are theme-aware (light + dark).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Server, Plus, Pencil, Trash2, Wifi, Activity, Clock, Bot,
  RefreshCw, CheckCircle2, XCircle, AlertTriangle, Copy,
  Globe, Monitor, HardDrive, Network, BookOpen, Cpu, Terminal,
  Loader2, Check, ArrowLeft, Send, MessageSquare, ScrollText,
  Play, Pause, ChevronDown, ChevronUp, Timer,
} from 'lucide-react'

// ─── Types ─────────────────────────────────────────────────────────────────

interface Instance {
  id: string
  name: string
  host: string
  ssh_port: number
  ssh_username: string
  role: string
  status: string
  node_type: string
  capabilities: Record<string, unknown>
  claude_version: string | null
  last_heartbeat_at: string | null
  created_at: string
  agent_count: number
}

interface Agent {
  id: string
  name: string
  type: string
  status: string
  instance_id: string
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

interface AgentLog {
  id: string
  agent_id: string
  level: string
  message: string
  context: Record<string, unknown>
  created_at: string
}

interface AgentMessage {
  id: string
  from_agent_id: string
  to_agent_id: string | null
  intent: string
  body: string | null
  data: Record<string, unknown>
  status: string
  created_at: string
}

interface InstanceFormData {
  name: string
  host: string
  ssh_port: number
  ssh_username: string
  ssh_private_key: string
  role: string
  node_type: string
  auto_install_claude: boolean
  anthropic_api_key: string
}

interface VerifyResult {
  reachable: boolean
  claude_installed: boolean
  claude_version: string | null
  python_installed: boolean
  memory_free_mb: number
  disk_free: string
}

const ROLES = ['general', 'backtesting', 'trading'] as const
const EMPTY_FORM: InstanceFormData = {
  name: '',
  host: '',
  ssh_port: 22,
  ssh_username: 'root',
  ssh_private_key: '',
  role: 'general',
  node_type: 'vps',
  auto_install_claude: false,
  anthropic_api_key: '',
}

function instanceToEditForm(inst: Instance): InstanceFormData {
  return {
    name: inst.name,
    host: inst.host,
    ssh_port: inst.ssh_port,
    ssh_username: inst.ssh_username,
    ssh_private_key: '',
    role: inst.role,
    node_type: inst.node_type,
    auto_install_claude: false,
    anthropic_api_key: '',
  }
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return 'Never'
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60_000) return 'Just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function uptimeStr(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const d = Math.floor(diff / 86_400_000)
  const h = Math.floor((diff % 86_400_000) / 3_600_000)
  if (d > 0) return `${d}d ${h}h`
  const m = Math.floor((diff % 3_600_000) / 60_000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function statusConfig(status: string) {
  const s = status.toUpperCase()
  if (['RUNNING', 'ONLINE'].includes(s)) return {
    color: 'text-emerald-600 dark:text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    dot: 'bg-emerald-500',
    label: 'Online',
    icon: CheckCircle2,
  }
  if (['IDLE', 'DEGRADED'].includes(s)) return {
    color: 'text-amber-600 dark:text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    dot: 'bg-amber-500',
    label: 'Degraded',
    icon: AlertTriangle,
  }
  if (['ERROR', 'OFFLINE'].includes(s)) return {
    color: 'text-red-600 dark:text-red-400',
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
    dot: 'bg-red-500',
    label: 'Offline',
    icon: XCircle,
  }
  return {
    color: 'text-zinc-600 dark:text-zinc-400',
    bg: 'bg-zinc-500/10',
    border: 'border-zinc-500/30',
    dot: 'bg-zinc-500',
    label: 'Unknown',
    icon: AlertTriangle,
  }
}

function roleLabel(role: string) {
  const map: Record<string, string> = {
    general: 'General',
    backtesting: 'Backtesting',
    trading: 'Trading',
  }
  return map[role] ?? role.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function nodeTypeLabel(type: string) {
  return type === 'vps' ? 'Cloud VPS' : 'Local Machine'
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
    </button>
  )
}

// ─── Instance Card ─────────────────────────────────────────────────────────

function InstanceCard({
  instance,
  onEdit,
  onDelete,
  onHealthCheck,
  onClick,
  isChecking,
}: {
  instance: Instance
  onEdit: () => void
  onDelete: () => void
  onHealthCheck: () => void
  onClick: () => void
  isChecking: boolean
}) {
  const sc = statusConfig(instance.status)
  const agents = instance.agent_count ?? 0
  const caps = instance.capabilities || {}
  const memTotal = (caps.memory_total_mb as number) || 0
  const memUsed = (caps.memory_used_mb as number) || 0
  const cpuCores = (caps.cpu_cores as number) || 0
  const ramPct = memTotal > 0 ? (memUsed / memTotal) * 100 : 0
  const versionShort = instance.claude_version
    ? instance.claude_version.replace(/\s+/g, ' ').slice(0, 28) + (instance.claude_version.length > 28 ? '…' : '')
    : null
  const sshLine = `${instance.ssh_username}@${instance.host}:${instance.ssh_port}`

  return (
    <div
      onClick={onClick}
      className={`group relative rounded-xl border bg-card ${sc.border} p-5 transition-all hover:shadow-lg cursor-pointer hover:border-primary/40`}
    >
      <div className={`absolute top-0 left-0 right-0 h-1 rounded-t-xl ${sc.dot}`} />

      <div className="flex items-start justify-between mb-4 mt-1">
        <div className="flex items-center gap-3">
          <div className={`p-2.5 rounded-lg ${sc.bg} border ${sc.border}`}>
            <Server className={`h-5 w-5 ${sc.color}`} />
          </div>
          <div>
            <h3 className="font-semibold text-sm text-foreground">{instance.name}</h3>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-muted-foreground font-mono truncate max-w-[200px]" title={sshLine}>
                {sshLine}
              </span>
              <CopyButton text={sshLine} />
            </div>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${sc.bg} ${sc.color} border ${sc.border}`}>
          <span className={`w-2 h-2 rounded-full ${sc.dot} ${['RUNNING', 'ONLINE'].includes(instance.status.toUpperCase()) ? 'animate-pulse' : ''}`} />
          {sc.label}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
        <div className="rounded-lg bg-muted/50 border border-border p-2.5 text-center">
          <Terminal className="h-3.5 w-3.5 mx-auto mb-1 text-muted-foreground" />
          <p className="text-[11px] font-semibold text-foreground leading-tight line-clamp-2 min-h-[2rem]" title={instance.claude_version || undefined}>
            {versionShort || '—'}
          </p>
          <p className="text-[9px] text-muted-foreground mt-0.5">Claude Code</p>
        </div>
        <div className="rounded-lg bg-muted/50 border border-border p-2.5 text-center">
          <Bot className="h-3.5 w-3.5 mx-auto mb-1 text-muted-foreground" />
          <p className="text-lg font-bold text-foreground">{agents}</p>
          <p className="text-[9px] text-muted-foreground">Agents</p>
        </div>
        <div className="rounded-lg bg-muted/50 border border-border p-2.5 text-center">
          <Cpu className="h-3.5 w-3.5 mx-auto mb-1 text-muted-foreground" />
          <p className="text-sm font-bold text-foreground">{cpuCores > 0 ? cpuCores : '—'}</p>
          <p className="text-[9px] text-muted-foreground">CPU cores</p>
        </div>
        <div className="rounded-lg bg-muted/50 border border-border p-2.5 text-center">
          <HardDrive className="h-3.5 w-3.5 mx-auto mb-1 text-muted-foreground" />
          <p className="text-[11px] font-semibold text-foreground leading-tight">
            {memTotal > 0 ? `${memUsed} / ${memTotal} MB` : '—'}
          </p>
          <p className="text-[9px] text-muted-foreground">RAM</p>
        </div>
      </div>

      {(cpuCores > 0 || memTotal > 0) && (
        <div className="flex gap-3 mb-4">
          {cpuCores > 0 && (
            <div className="flex-1">
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-muted-foreground flex items-center gap-1"><Cpu className="h-3 w-3" /> CPU</span>
                <span className="font-medium text-foreground">{cpuCores} cores</span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div className="h-full rounded-full bg-emerald-500 transition-all w-full" />
              </div>
            </div>
          )}
          {memTotal > 0 && (
            <div className="flex-1">
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-muted-foreground flex items-center gap-1"><HardDrive className="h-3 w-3" /> RAM use</span>
                <span className="font-medium text-foreground">{ramPct.toFixed(0)}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${ramPct > 85 ? 'bg-red-500' : ramPct > 65 ? 'bg-amber-500' : 'bg-blue-500'}`}
                  style={{ width: `${Math.min(ramPct, 100)}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-3">
        <Clock className="h-3 w-3 shrink-0" />
        <span>Heartbeat {timeAgo(instance.last_heartbeat_at)}</span>
        <span className="text-border">·</span>
        {instance.node_type === 'vps' ? <Globe className="h-3 w-3 shrink-0" /> : <Monitor className="h-3 w-3 shrink-0" />}
        <span>{nodeTypeLabel(instance.node_type)}</span>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground capitalize">{roleLabel(instance.role)}</span>
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Check health" disabled={isChecking} onClick={onHealthCheck}>
            {isChecking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </Button>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Edit" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive" title="Delete" onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}

// ─── Add Instance Dialog ───────────────────────────────────────────────────

function AddInstanceDialog({
  open, onOpenChange, initial, onSubmit, title, mode = 'create',
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  initial: InstanceFormData
  onSubmit: (data: InstanceFormData) => Promise<void>
  title: string
  mode?: 'create' | 'edit'
}) {
  const [form, setForm] = useState<InstanceFormData>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [verifying, setVerifying] = useState(false)
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [installProgress, setInstallProgress] = useState<string | null>(null)

  useEffect(() => { if (open) { setForm(initial); setError(''); setVerifyResult(null); setInstallProgress(null) } }, [open, initial])

  const handleVerify = async () => {
    if (!form.host.trim()) { setError('Host is required to verify'); return }
    if (!form.ssh_private_key.trim() || form.ssh_private_key.length < 10) {
      setError('Paste a valid SSH private key (PEM) to verify.')
      return
    }
    setVerifying(true); setVerifyResult(null); setError('')
    try {
      const res = await api.post('/api/v2/instances/verify', {
        host: form.host.trim(),
        ssh_port: form.ssh_port,
        ssh_username: form.ssh_username.trim() || 'root',
        ssh_private_key: form.ssh_private_key,
      })
      setVerifyResult(res.data as VerifyResult)
    } catch {
      setVerifyResult({
        reachable: false,
        claude_installed: false,
        claude_version: null,
        python_installed: false,
        memory_free_mb: 0,
        disk_free: '',
      })
      setError('Verification request failed.')
    } finally { setVerifying(false) }
  }

  const handleSave = async () => {
    if (!form.name.trim() || !form.host.trim()) { setError('Name and host are required.'); return }
    if (mode === 'create') {
      if (!form.ssh_private_key.trim() || form.ssh_private_key.length < 10) {
        setError('SSH private key is required (min 10 characters).')
        return
      }
      if (form.auto_install_claude && !form.anthropic_api_key.trim()) {
        setError('Anthropic API key is required for auto-install.')
        return
      }
    }
    setSaving(true); setError('')
    try {
      await onSubmit(form)
      onOpenChange(false)
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Save failed') } finally { setSaving(false) }
  }

  const verifyDetail = verifyResult && [
    verifyResult.claude_version ? `Claude Code: ${verifyResult.claude_version}` : null,
    verifyResult.python_installed ? 'Python: OK' : null,
    verifyResult.memory_free_mb ? `Free RAM: ~${verifyResult.memory_free_mb} MB` : null,
    verifyResult.disk_free ? `Disk free: ${verifyResult.disk_free}` : null,
  ].filter(Boolean).join(' · ')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {mode === 'create'
              ? 'Register a host reachable by SSH. The API uses your key to run Claude Code and agent commands on the instance.'
              : 'Update the display name or role. SSH connection settings are unchanged; remove and re-add the instance to rotate keys.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="inst-name">Instance Name</Label>
            <Input id="inst-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g., prod-trading-1" />
          </div>

          <div className="space-y-1.5">
            <Label>SSH host</Label>
            <Input
              value={form.host}
              disabled={mode === 'edit'}
              onChange={(e) => { setForm((f) => ({ ...f, host: e.target.value })); setVerifyResult(null) }}
              placeholder="IP or hostname"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ssh-port">SSH port</Label>
              <Input
                id="ssh-port"
                type="number"
                disabled={mode === 'edit'}
                value={form.ssh_port}
                onChange={(e) => { setForm((f) => ({ ...f, ssh_port: Number(e.target.value) || 22 })); setVerifyResult(null) }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ssh-user">SSH username</Label>
              <Input
                id="ssh-user"
                disabled={mode === 'edit'}
                value={form.ssh_username}
                onChange={(e) => { setForm((f) => ({ ...f, ssh_username: e.target.value })); setVerifyResult(null) }}
                placeholder="root"
                className="font-mono"
              />
            </div>
          </div>

          {mode === 'create' && (
            <div className="space-y-1.5">
              <Label htmlFor="ssh-key">SSH private key</Label>
              <Textarea
                id="ssh-key"
                value={form.ssh_private_key}
                onChange={(e) => { setForm((f) => ({ ...f, ssh_private_key: e.target.value })); setVerifyResult(null) }}
                placeholder={'-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----'}
                className="font-mono text-xs min-h-[120px]"
                spellCheck={false}
              />
              <p className="text-xs text-muted-foreground">Stored encrypted server-side. Never committed to git.</p>
            </div>
          )}

          {mode === 'create' && (
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={handleVerify}
                disabled={verifying || !form.host.trim() || form.ssh_private_key.length < 10}
              >
                {verifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wifi className="h-4 w-4" />}
                <span className="ml-1.5">Verify SSH / Claude Code</span>
              </Button>
            </div>
          )}

          {verifyResult && mode === 'create' && (
            <div className={`rounded-lg border p-3 text-sm ${
              verifyResult.claude_installed
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                : verifyResult.reachable
                  ? 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400'
                  : 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-400'
            }`}>
              <div className="flex items-center gap-2">
                {verifyResult.claude_installed ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : verifyResult.reachable ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <XCircle className="h-4 w-4 shrink-0" />}
                <span className="font-medium">
                  {verifyResult.claude_installed
                    ? 'Claude Code detected on host'
                    : verifyResult.reachable
                      ? 'SSH OK — Claude Code not detected (install CLI on the host)'
                      : 'Cannot reach host over SSH'}
                </span>
              </div>
              {verifyDetail ? <p className="text-xs mt-1 opacity-80">{verifyDetail}</p> : null}
            </div>
          )}

          {mode === 'create' && verifyResult?.reachable && !verifyResult?.claude_installed && (
            <div className="space-y-3 rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.auto_install_claude}
                  onChange={(e) => setForm((f) => ({ ...f, auto_install_claude: e.target.checked }))}
                  className="mt-0.5 h-4 w-4 rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
                />
                <div>
                  <span className="text-sm font-medium text-foreground">Auto-install Claude Code &amp; authenticate</span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Installs Claude Code CLI on the VPS and authenticates with your Anthropic API key.
                    This runs after the instance is created.
                  </p>
                </div>
              </label>
              {form.auto_install_claude && (
                <div className="space-y-1.5 pl-7">
                  <Label htmlFor="anthropic-key">Anthropic API Key</Label>
                  <Input
                    id="anthropic-key"
                    type="password"
                    value={form.anthropic_api_key}
                    onChange={(e) => setForm((f) => ({ ...f, anthropic_api_key: e.target.value }))}
                    placeholder="sk-ant-api03-..."
                    className="font-mono text-xs"
                  />
                  <p className="text-xs text-muted-foreground">
                    Used once during setup to authenticate Claude Code. Stored encrypted on the VPS, not in our database.
                  </p>
                </div>
              )}
            </div>
          )}

          {installProgress && (
            <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 text-sm">
              <div className="flex items-center gap-2 text-blue-700 dark:text-blue-400">
                <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                <span className="font-medium">{installProgress}</span>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Role</Label>
              <Select value={form.role} onValueChange={(v) => setForm((f) => ({ ...f, role: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r} value={r}>{roleLabel(r)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Node Type</Label>
              <Select
                value={form.node_type}
                onValueChange={(v) => setForm((f) => ({ ...f, node_type: v }))}
                disabled={mode === 'edit'}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="vps">Cloud VPS</SelectItem>
                  <SelectItem value="local">Local Machine</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <><Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> Saving…</> : mode === 'edit' ? <><Pencil className="h-4 w-4 mr-1.5" /> Save</> : <><Plus className="h-4 w-4 mr-1.5" /> Add Instance</>}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Connection Guide ──────────────────────────────────────────────────────

function ConnectionGuide() {
  const [expandedTab, setExpandedTab] = useState<'vps' | 'local'>('vps')

  const CodeBlock = ({ code, title }: { code: string; title?: string }) => (
    <div className="rounded-lg border border-border bg-muted overflow-hidden">
      {title && (
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-muted/80">
          <span className="text-[11px] text-muted-foreground font-medium">{title}</span>
          <CopyButton text={code} />
        </div>
      )}
      <pre className="px-3 py-2 text-xs font-mono text-emerald-700 dark:text-emerald-400 overflow-x-auto whitespace-pre">{code}</pre>
    </div>
  )

  const StepCircle = ({ n }: { n: number }) => (
    <div className="w-8 h-8 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center text-sm font-bold text-primary shrink-0">{n}</div>
  )
  const StepLine = () => <div className="w-px flex-1 bg-border mt-2" />
  const DoneCircle = () => (
    <div className="w-8 h-8 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
      <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
    </div>
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 rounded-lg bg-primary/10 border border-primary/20"><BookOpen className="h-5 w-5 text-primary" /></div>
        <div>
          <h3 className="text-base font-semibold text-foreground">How to Connect Claude Code Instances</h3>
          <p className="text-xs text-muted-foreground">SSH access, Claude Code CLI, and registration in Phoenix</p>
        </div>
      </div>

      <Tabs value={expandedTab} onValueChange={(v) => setExpandedTab(v as 'vps' | 'local')}>
        <TabsList className="w-full">
          <TabsTrigger value="vps" className="flex-1 gap-2"><Globe className="h-4 w-4" /> Cloud VPS</TabsTrigger>
          <TabsTrigger value="local" className="flex-1 gap-2"><Monitor className="h-4 w-4" /> Local Machine</TabsTrigger>
        </TabsList>

        <TabsContent value="vps" className="space-y-4 mt-4">
          <div className="flex gap-4"><div className="flex flex-col items-center"><StepCircle n={1} /><StepLine /></div>
            <div className="flex-1 pb-6"><h4 className="font-medium text-sm text-foreground mb-1">SSH into your VPS</h4><p className="text-xs text-muted-foreground mb-3">Use a user with sufficient permissions (often <code className="px-1 py-0.5 bg-muted rounded text-[11px]">root</code> or a sudo-capable account). Generate a dedicated key pair for Phoenix and authorize the public key in <code className="px-1 py-0.5 bg-muted rounded text-[11px]">authorized_keys</code>.</p><CodeBlock code="ssh -i ~/.ssh/phoenix_deploy root@your-vps-ip" title="Terminal" /></div></div>
          <div className="flex gap-4"><div className="flex flex-col items-center"><StepCircle n={2} /><StepLine /></div>
            <div className="flex-1 pb-6"><h4 className="font-medium text-sm text-foreground mb-1">Install Claude Code on the host</h4><p className="text-xs text-muted-foreground mb-3">Install the official Claude Code CLI on the server so health checks can run <code className="px-1 py-0.5 bg-muted rounded text-[11px]">claude --version</code>. Follow the current install steps from Anthropic for Linux.</p><CodeBlock code={`# Example — use the installer from Anthropic’s docs for your OS\ncurl -fsSL https://claude.ai/install.sh | bash\n# Then confirm:\nclaude --version`} title="Terminal" /></div></div>
          <div className="flex gap-4"><div className="flex flex-col items-center"><StepCircle n={3} /><StepLine /></div>
            <div className="flex-1 pb-6"><h4 className="font-medium text-sm text-foreground mb-1">Ensure Python 3 is available</h4><p className="text-xs text-muted-foreground mb-3">Agents and tooling expect <code className="px-1 py-0.5 bg-muted rounded text-[11px]">python3</code> on the PATH.</p><CodeBlock code="python3 --version" title="Terminal" /></div></div>
          <div className="flex gap-4"><div className="flex flex-col items-center"><StepCircle n={4} /><StepLine /></div>
            <div className="flex-1 pb-6"><h4 className="font-medium text-sm text-foreground mb-1">Network: SSH from the API server</h4><p className="text-xs text-muted-foreground mb-3">The Phoenix API must reach your host on the SSH port (default 22). Allow that port in your cloud firewall / security group — no separate HTTP agent port is required.</p><CodeBlock code={`# UFW (Ubuntu) — example\nsudo ufw allow 22/tcp`} title="Terminal" /></div></div>
          <div className="flex gap-4"><div className="flex flex-col items-center"><DoneCircle /></div>
            <div className="flex-1"><h4 className="font-medium text-sm text-foreground mb-1">Register the instance</h4><p className="text-xs text-muted-foreground mb-3">Click &quot;Add Instance&quot;, enter host, SSH port, username, and paste the <strong>private</strong> key. Use &quot;Verify SSH / Claude Code&quot; before saving.</p>
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3 text-xs text-emerald-700 dark:text-emerald-400"><strong>Tip:</strong> Verification opens an SSH session, checks Claude Code and Python, and reports memory and disk — without persisting the instance.</div></div></div>
        </TabsContent>

        <TabsContent value="local" className="space-y-4 mt-4">
          <div className="flex gap-4"><div className="flex flex-col items-center"><StepCircle n={1} /><StepLine /></div>
            <div className="flex-1 pb-6"><h4 className="font-medium text-sm text-foreground mb-1">Enable SSH on your machine</h4><p className="text-xs text-muted-foreground mb-3">macOS: System Settings → General → Sharing → Remote Login. Linux: install and start <code className="px-1 py-0.5 bg-muted rounded text-[11px]">openssh-server</code>. Use a dedicated key for Phoenix.</p><CodeBlock code={`# macOS: enable Remote Login in GUI, then:\nssh $(whoami)@localhost`} title="Terminal" /></div></div>
          <div className="flex gap-4"><div className="flex flex-col items-center"><StepCircle n={2} /><StepLine /></div>
            <div className="flex-1 pb-6"><h4 className="font-medium text-sm text-foreground mb-1">Install Claude Code locally</h4><p className="text-xs text-muted-foreground mb-3">Install the Claude Code CLI for your OS and confirm it in a terminal.</p><CodeBlock code="claude --version" title="Terminal" /></div></div>
          <div className="flex gap-4"><div className="flex flex-col items-center"><StepCircle n={3} /><StepLine /></div>
            <div className="flex-1 pb-6"><h4 className="font-medium text-sm text-foreground mb-1">Reachable from the API</h4><p className="text-xs text-muted-foreground mb-3">If Phoenix API runs in Docker or another host, <code className="px-1 py-0.5 bg-muted rounded text-[11px]">localhost</code> inside that container is not your Mac. Use your LAN IP or host.docker.internal as appropriate.</p><CodeBlock code={`# Find LAN IP (macOS)\nipconfig getifaddr en0`} title="Terminal" /></div></div>
          <div className="flex gap-4"><div className="flex flex-col items-center"><DoneCircle /></div>
            <div className="flex-1"><h4 className="font-medium text-sm text-foreground mb-1">Add instance in Phoenix</h4><p className="text-xs text-muted-foreground mb-3">Use SSH host, port, username, and private key like a remote server. Choose &quot;Local Machine&quot; as node type for labeling.</p>
              <div className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-3 text-xs text-blue-700 dark:text-blue-400"><strong>Note:</strong> Registration always uses SSH from the API process — the same rules apply as a cloud VPS.</div></div></div>
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ─── Empty State ───────────────────────────────────────────────────────────

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="rounded-xl border border-dashed border-border p-10 text-center">
      <div className="mx-auto w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-4">
        <Server className="h-8 w-8 text-primary" />
      </div>
      <h3 className="text-lg font-semibold text-foreground mb-2">No instances connected</h3>
      <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
        Connect your first Claude Code instance over SSH to deploy and manage trading agents.
      </p>
      <Button onClick={onAdd}><Plus className="h-4 w-4 mr-2" /> Add Your First Instance</Button>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// INSTANCE DETAIL VIEW — full dashboard when clicking an instance card
// ════════════════════════════════════════════════════════════════════════════

function InstanceDetailView({ instance, onBack }: { instance: Instance; onBack: () => void }) {
  const qc = useQueryClient()
  const sc = statusConfig(instance.status)
  const caps = instance.capabilities || {}
  const memTotal = (caps.memory_total_mb as number) ?? 0
  const memUsed = (caps.memory_used_mb as number) ?? 0
  const cpuCores = (caps.cpu_cores as number) ?? 0
  const memPct = memTotal > 0 ? (memUsed / memTotal) * 100 : null
  const totalPnl = (caps.total_pnl as number) ?? 0

  // ── Fetch agents assigned to this instance ──
  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ['agents', 'instance', instance.id],
    queryFn: async () => {
      const res = await api.get('/api/v2/agents', { params: { instance_id: instance.id } })
      return res.data
    },
    refetchInterval: 15000,
  })

  const agentStatuses = useMemo(
    () => agents.map((a) => ({ name: a.name, status: a.status })),
    [agents],
  )

  // ── Health check ──
  const [checking, setChecking] = useState(false)
  const handleCheck = async () => {
    setChecking(true)
    try {
      await api.post(`/api/v2/instances/${instance.id}/check`)
      qc.invalidateQueries({ queryKey: ['instances'] })
    } catch {}
    setChecking(false)
  }

  // ── Agent logs (latest from all agents) ──
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const { data: agentLogs = [] } = useQuery<AgentLog[]>({
    queryKey: ['agent-logs', selectedAgentId ?? 'all'],
    queryFn: async () => {
      if (agents.length === 0) return []
      const target = selectedAgentId ?? agents[0]?.id
      if (!target) return []
      try {
        const res = await api.get(`/api/v2/agents/${target}/logs`, { params: { limit: 50 } })
        return res.data
      } catch { return [] }
    },
    refetchInterval: 10000,
    enabled: agents.length > 0,
  })

  // ── Chat ──
  const [chatMessages, setChatMessages] = useState<AgentMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatSending, setChatSending] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const loadChat = useCallback(async () => {
    if (agents.length === 0) return
    try {
      const res = await api.get('/api/v2/agent-messages', { params: { agent_id: agents[0]?.id, limit: 100 } })
      setChatMessages(res.data)
    } catch {}
  }, [agents])

  useEffect(() => { loadChat() }, [loadChat])
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chatMessages])

  const sendChat = async () => {
    if (!chatInput.trim() || agents.length === 0) return
    setChatSending(true)
    try {
      await api.post('/api/v2/agent-messages', {
        from_agent_id: 'user',
        to_agent_id: agents[0]?.id,
        pattern: 'request-response',
        intent: 'user-chat',
        body: chatInput,
        data: {},
      })
      setChatInput('')
      await loadChat()
    } catch {}
    setChatSending(false)
  }

  // ── Agent actions ──
  const pauseAgent = async (id: string) => {
    try { await api.post(`/api/v2/agents/${id}/pause`); qc.invalidateQueries({ queryKey: ['agents', 'instance', instance.id] }) } catch {}
  }
  const resumeAgent = async (id: string) => {
    try { await api.post(`/api/v2/agents/${id}/resume`); qc.invalidateQueries({ queryKey: ['agents', 'instance', instance.id] }) } catch {}
  }

  // ── Expanded log agent ──
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null)

  const ProgressBar = ({ value, max, color }: { value: number; max: number; color: string }) => (
    <div className="h-2 rounded-full bg-muted overflow-hidden">
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.min((value / max) * 100, 100)}%` }} />
    </div>
  )

  const logLevelColor = (level: string) => {
    switch (level.toUpperCase()) {
      case 'ERROR': return 'text-red-600 dark:text-red-400 bg-red-500/10'
      case 'WARN': case 'WARNING': return 'text-amber-600 dark:text-amber-400 bg-amber-500/10'
      case 'INFO': return 'text-blue-600 dark:text-blue-400 bg-blue-500/10'
      default: return 'text-muted-foreground bg-muted'
    }
  }

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center gap-4 flex-wrap">
        <Button variant="ghost" size="sm" onClick={onBack} className="gap-1.5">
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${sc.bg} border ${sc.border}`}>
              <Server className={`h-5 w-5 ${sc.color}`} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">{instance.name}</h2>
              <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                <span className="font-mono">{instance.ssh_username}@{instance.host}:{instance.ssh_port}</span>
                <CopyButton text={`${instance.ssh_username}@${instance.host}:${instance.ssh_port}`} />
                <span>|</span>
                <span className="capitalize">{roleLabel(instance.role)}</span>
                <span>|</span>
                <span>{nodeTypeLabel(instance.node_type)}</span>
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${sc.bg} ${sc.color} border ${sc.border}`}>
            <span className={`w-2 h-2 rounded-full ${sc.dot} ${['RUNNING', 'ONLINE'].includes(instance.status.toUpperCase()) ? 'animate-pulse' : ''}`} />
            {sc.label}
          </div>
          <Button variant="outline" size="sm" onClick={handleCheck} disabled={checking}>
            {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="ml-1.5">Health Check</span>
          </Button>
        </div>
      </div>

      {/* ── Top row: System Health + Agent List ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* System Health Panel */}
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-4">
            <Activity className="h-4 w-4 text-primary" /> System Health
          </h3>
          <div className="grid grid-cols-2 gap-4 mb-5">
            <div className="rounded-lg bg-muted/50 border border-border p-3">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1"><Timer className="h-3 w-3" /> Uptime</div>
              <p className="text-sm font-semibold text-foreground">{uptimeStr(instance.created_at)}</p>
            </div>
            <div className="rounded-lg bg-muted/50 border border-border p-3">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1"><Clock className="h-3 w-3" /> Last Heartbeat</div>
              <p className="text-sm font-semibold text-foreground">{timeAgo(instance.last_heartbeat_at)}</p>
            </div>
            <div className="rounded-lg bg-muted/50 border border-border p-3">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1"><Terminal className="h-3 w-3" /> Claude Code</div>
              <p className="text-sm font-semibold text-foreground truncate" title={instance.claude_version || undefined}>
                {instance.claude_version || '—'}
              </p>
            </div>
            <div className="rounded-lg bg-muted/50 border border-border p-3">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1"><Bot className="h-3 w-3" /> Agents</div>
              <p className="text-sm font-semibold text-foreground">{agents.length}</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between text-xs mb-1.5">
                <span className="text-muted-foreground flex items-center gap-1"><Cpu className="h-3 w-3" /> CPU</span>
                <span className="font-medium text-foreground">{cpuCores > 0 ? `${cpuCores} cores` : 'N/A'}</span>
              </div>
              <ProgressBar value={cpuCores > 0 ? 100 : 0} max={100} color="bg-emerald-500" />
            </div>
            <div>
              <div className="flex items-center justify-between text-xs mb-1.5">
                <span className="text-muted-foreground flex items-center gap-1"><HardDrive className="h-3 w-3" /> Memory</span>
                <span className="font-medium text-foreground">
                  {memTotal > 0 ? `${memUsed} / ${memTotal} MB` : 'N/A'}
                </span>
              </div>
              <ProgressBar value={memPct ?? 0} max={100} color={memPct != null && memPct > 85 ? 'bg-red-500' : memPct != null && memPct > 65 ? 'bg-amber-500' : 'bg-blue-500'} />
            </div>
          </div>

          {totalPnl !== 0 && (
            <div className="mt-4 pt-4 border-t border-border">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Total P&L</span>
                <span className={`font-semibold ${totalPnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                  {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Agent List Panel */}
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-4">
            <Bot className="h-4 w-4 text-primary" /> Agents ({agents.length})
          </h3>
          {agents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <Bot className="h-8 w-8 text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">No agents assigned to this instance.</p>
              <p className="text-xs text-muted-foreground mt-1">Create agents from the Agents tab and assign them here.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
              {agents.map((agent) => {
                const asc = statusConfig(agent.status)
                const isExpanded = expandedAgent === agent.id
                return (
                  <div key={agent.id} className="rounded-lg border border-border bg-muted/30 overflow-hidden">
                    <div className="flex items-center gap-3 p-3">
                      <div className={`w-2 h-2 rounded-full shrink-0 ${asc.dot}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground truncate">{agent.name}</p>
                        <p className="text-xs text-muted-foreground capitalize">{agent.type} agent</p>
                      </div>
                      <StatusBadge status={agent.status} />
                      <div className="flex items-center gap-1">
                        {['RUNNING', 'ONLINE'].includes(agent.status.toUpperCase()) ? (
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Pause" onClick={() => pauseAgent(agent.id)}>
                            <Pause className="h-3.5 w-3.5" />
                          </Button>
                        ) : (
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Resume" onClick={() => resumeAgent(agent.id)}>
                            <Play className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        <Button
                          variant="ghost" size="sm" className="h-7 w-7 p-0" title="Logs"
                          onClick={() => { setExpandedAgent(isExpanded ? null : agent.id); setSelectedAgentId(agent.id) }}
                        >
                          {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                        </Button>
                      </div>
                    </div>
                    {isExpanded && (
                      <div className="border-t border-border bg-muted/50 px-3 py-2 max-h-40 overflow-y-auto">
                        {agentLogs.length === 0 ? (
                          <p className="text-xs text-muted-foreground text-center py-2">No logs available</p>
                        ) : (
                          <div className="space-y-1">
                            {agentLogs.slice(0, 20).map((log) => (
                              <div key={log.id} className="flex items-start gap-2 text-xs">
                                <span className={`px-1 py-0.5 rounded text-[10px] font-medium shrink-0 ${logLevelColor(log.level)}`}>
                                  {log.level.toUpperCase().slice(0, 4)}
                                </span>
                                <span className="text-muted-foreground shrink-0">{timeAgo(log.created_at)}</span>
                                <span className="text-foreground truncate">{log.message}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── Bottom row: Chat + Activity Feed ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Chat Panel */}
        <div className="rounded-xl border border-border bg-card p-5 flex flex-col">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-4">
            <MessageSquare className="h-4 w-4 text-primary" /> Agent Chat
          </h3>
          <div className="flex-1 min-h-[250px] max-h-[350px] overflow-y-auto border border-border rounded-lg bg-muted/30 p-3 mb-3 space-y-3">
            {chatMessages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-8">
                <MessageSquare className="h-8 w-8 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">No messages yet.</p>
                <p className="text-xs text-muted-foreground mt-1">Send a message to communicate with agents on this instance.</p>
              </div>
            ) : (
              chatMessages.map((msg) => {
                const isUser = msg.from_agent_id === 'user'
                return (
                  <div key={msg.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                      isUser ? 'bg-primary text-primary-foreground' : 'bg-muted border border-border text-foreground'
                    }`}>
                      {!isUser && <p className="text-[10px] font-medium mb-0.5 opacity-70">{msg.from_agent_id}</p>}
                      <p>{msg.body || msg.intent}</p>
                      <p className="text-[10px] mt-1 opacity-50">{timeAgo(msg.created_at)}</p>
                    </div>
                  </div>
                )
              })
            )}
            <div ref={chatEndRef} />
          </div>
          <div className="flex gap-2">
            <Input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat() } }}
              placeholder={agents.length === 0 ? 'No agents to chat with...' : 'Type a message...'}
              disabled={agents.length === 0}
              className="flex-1"
            />
            <Button size="sm" onClick={sendChat} disabled={chatSending || !chatInput.trim() || agents.length === 0}>
              {chatSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        {/* Activity Feed Panel */}
        <div className="rounded-xl border border-border bg-card p-5 flex flex-col">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2 mb-4">
            <ScrollText className="h-4 w-4 text-primary" /> Activity Feed
          </h3>
          <div className="flex-1 min-h-[250px] max-h-[350px] overflow-y-auto space-y-2 pr-1">
            {/* Heartbeat events from agent statuses */}
            {agentStatuses.length > 0 && agentStatuses.map((as, i) => (
              <div key={`hb-${i}`} className="flex items-start gap-3 rounded-lg bg-muted/30 border border-border p-3">
                <div className="w-8 h-8 rounded-full bg-emerald-500/10 flex items-center justify-center shrink-0">
                  <Activity className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-foreground font-medium">{(as.name as string) || `Agent ${i + 1}`}</p>
                  <p className="text-xs text-muted-foreground">Status: {(as.status as string) || 'Unknown'} | Heartbeat snapshot</p>
                </div>
                <span className="text-xs text-muted-foreground shrink-0">{timeAgo(instance.last_heartbeat_at)}</span>
              </div>
            ))}

            {/* Agent logs as activity */}
            {agentLogs.map((log) => (
              <div key={log.id} className="flex items-start gap-3 rounded-lg bg-muted/30 border border-border p-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                  log.level.toUpperCase() === 'ERROR' ? 'bg-red-500/10' :
                    log.level.toUpperCase() === 'WARN' || log.level.toUpperCase() === 'WARNING' ? 'bg-amber-500/10' : 'bg-blue-500/10'
                }`}>
                  <ScrollText className={`h-4 w-4 ${
                    log.level.toUpperCase() === 'ERROR' ? 'text-red-600 dark:text-red-400' :
                      log.level.toUpperCase() === 'WARN' || log.level.toUpperCase() === 'WARNING' ? 'text-amber-600 dark:text-amber-400' : 'text-blue-600 dark:text-blue-400'
                  }`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${logLevelColor(log.level)}`}>{log.level.toUpperCase()}</span>
                    <span className="text-xs text-muted-foreground">{timeAgo(log.created_at)}</span>
                  </div>
                  <p className="text-sm text-foreground mt-1 break-words">{log.message}</p>
                </div>
              </div>
            ))}

            {agentStatuses.length === 0 && agentLogs.length === 0 && (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <ScrollText className="h-8 w-8 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">No recent activity.</p>
                <p className="text-xs text-muted-foreground mt-1">Agent logs and heartbeat events will appear here.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────

export default function NetworkPage() {
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [editInstance, setEditInstance] = useState<Instance | null>(null)
  const [deleteInstance, setDeleteInstance] = useState<Instance | null>(null)
  const [checkingIds, setCheckingIds] = useState<Set<string>>(new Set())
  const [checkingAll, setCheckingAll] = useState(false)
  const [selectedInstance, setSelectedInstance] = useState<Instance | null>(null)

  const { data: instances = [], isLoading } = useQuery<Instance[]>({
    queryKey: ['instances'],
    queryFn: async () => {
      const res = await api.get('/api/v2/instances')
      return res.data
    },
    refetchInterval: 30000,
  })

  // Keep selectedInstance in sync with fresh data
  useEffect(() => {
    if (selectedInstance) {
      const fresh = instances.find((i) => i.id === selectedInstance.id)
      if (fresh) setSelectedInstance(fresh)
    }
  }, [instances])

  const createMutation = useMutation({
    mutationFn: async (data: InstanceFormData) => {
      const res = await api.post('/api/v2/instances', {
        name: data.name.trim(),
        host: data.host.trim(),
        ssh_port: data.ssh_port,
        ssh_username: data.ssh_username.trim() || 'root',
        ssh_private_key: data.ssh_private_key,
        role: data.role,
        node_type: data.node_type,
        auto_setup: data.auto_install_claude,
        anthropic_api_key: data.auto_install_claude ? data.anthropic_api_key.trim() || null : null,
      })
      return res.data as Instance
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['instances'] }),
    onError: (err: unknown) => { throw err instanceof Error ? err : new Error('Create failed') },
  })

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: string; data: { name: string; role: string } }) => {
      const res = await api.patch(`/api/v2/instances/${id}`, { name: data.name.trim(), role: data.role })
      return res.data
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['instances'] }); setEditInstance(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => { await api.delete(`/api/v2/instances/${id}`) },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['instances'] }),
  })

  const handleHealthCheck = async (instId: string) => {
    setCheckingIds((prev) => new Set(prev).add(instId))
    try { await api.post(`/api/v2/instances/${instId}/check`); qc.invalidateQueries({ queryKey: ['instances'] }) } catch {}
    setCheckingIds((prev) => { const next = new Set(prev); next.delete(instId); return next })
  }

  const handleCheckAll = async () => {
    setCheckingAll(true)
    await Promise.allSettled(instances.map((inst) => handleHealthCheck(inst.id)))
    setCheckingAll(false)
  }

  // ── If an instance is selected, show the detail dashboard ──
  if (selectedInstance) {
    return <InstanceDetailView instance={selectedInstance} onBack={() => setSelectedInstance(null)} />
  }

  const online = instances.filter((i) => ['RUNNING', 'ONLINE'].includes(i.status.toUpperCase())).length
  const offline = instances.filter((i) => ['OFFLINE', 'ERROR'].includes(i.status.toUpperCase())).length
  const totalAgents = instances.reduce((a, i) => a + (i.agent_count ?? 0), 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <PageHeader icon={Network} title="Infrastructure" description="Manage Claude Code instances (SSH)" />
        <div className="flex items-center gap-2">
          {instances.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleCheckAll} disabled={checkingAll}>
              {checkingAll ? <><Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> Checking...</> : <><RefreshCw className="h-4 w-4 mr-1.5" /> Check All</>}
            </Button>
          )}
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1.5" /> Add Instance
          </Button>
        </div>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="flex items-center gap-2 mb-2"><Server className="h-4 w-4 text-muted-foreground" /><span className="text-xs text-muted-foreground">Total Instances</span></div>
          <p className="text-2xl font-bold text-foreground">{instances.length}</p>
        </div>
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
          <div className="flex items-center gap-2 mb-2"><CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /><span className="text-xs text-emerald-600 dark:text-emerald-400">Online</span></div>
          <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">{online}</p>
        </div>
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4">
          <div className="flex items-center gap-2 mb-2"><XCircle className="h-4 w-4 text-red-600 dark:text-red-400" /><span className="text-xs text-red-600 dark:text-red-400">Offline</span></div>
          <p className="text-2xl font-bold text-red-600 dark:text-red-400">{offline}</p>
        </div>
        <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-4">
          <div className="flex items-center gap-2 mb-2"><Bot className="h-4 w-4 text-blue-600 dark:text-blue-400" /><span className="text-xs text-blue-600 dark:text-blue-400">Total Agents</span></div>
          <p className="text-2xl font-bold text-blue-600 dark:text-blue-400">{totalAgents}</p>
        </div>
      </div>

      <Tabs defaultValue="instances">
        <TabsList>
          <TabsTrigger value="instances" className="gap-1.5"><Server className="h-4 w-4" /> Instances</TabsTrigger>
          <TabsTrigger value="guide" className="gap-1.5"><BookOpen className="h-4 w-4" /> Connection Guide</TabsTrigger>
        </TabsList>

        <TabsContent value="instances" className="mt-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
          ) : instances.length === 0 ? (
            <EmptyState onAdd={() => setCreateOpen(true)} />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {instances.map((inst) => (
                <InstanceCard
                  key={inst.id}
                  instance={inst}
                  isChecking={checkingIds.has(inst.id)}
                  onEdit={() => setEditInstance(inst)}
                  onDelete={() => setDeleteInstance(inst)}
                  onHealthCheck={() => handleHealthCheck(inst.id)}
                  onClick={() => setSelectedInstance(inst)}
                />
              ))}
              <button
                onClick={() => setCreateOpen(true)}
                className="rounded-xl border border-dashed border-border p-5 flex flex-col items-center justify-center gap-2 text-muted-foreground hover:text-foreground hover:border-primary/40 hover:bg-muted/50 transition-all min-h-[200px]"
              >
                <Plus className="h-8 w-8" />
                <span className="text-sm font-medium">Add Instance</span>
              </button>
            </div>
          )}
        </TabsContent>

        <TabsContent value="guide" className="mt-4">
          <div className="rounded-xl border border-border bg-card p-6">
            <ConnectionGuide />
          </div>
        </TabsContent>
      </Tabs>

      <AddInstanceDialog open={createOpen} onOpenChange={setCreateOpen} initial={EMPTY_FORM} title="Add Claude Code Instance" mode="create" onSubmit={async (data) => { await createMutation.mutateAsync(data) }} />
      {editInstance && (
        <AddInstanceDialog
          open={!!editInstance} onOpenChange={(v) => { if (!v) setEditInstance(null) }}
          initial={instanceToEditForm(editInstance)}
          mode="edit"
          title={`Edit: ${editInstance.name}`}
          onSubmit={async (data) => { await updateMutation.mutateAsync({ id: editInstance.id, data: { name: data.name, role: data.role } }) }}
        />
      )}
      <ConfirmDialog
        open={!!deleteInstance} onOpenChange={(v) => { if (!v) setDeleteInstance(null) }}
        title="Remove Instance" description={`Remove "${deleteInstance?.name}" from your infrastructure? This only unregisters it in Phoenix — the remote host is unchanged.`}
        confirmLabel="Remove" variant="destructive"
        onConfirm={async () => { if (deleteInstance) await deleteMutation.mutateAsync(deleteInstance.id); setDeleteInstance(null) }}
      />
    </div>
  )
}
