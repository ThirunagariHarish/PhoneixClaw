/**
 * Settings page — profile, theme, notifications, API config.
 * All Save buttons are wired: profile persists to backend, notifications
 * and API base URL persist to localStorage.
 */
import { useState, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTheme } from '@/context/ThemeContext'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Palette, Lock, ShieldCheck, Search } from 'lucide-react'

// S4: Full timezone list from Intl API with search
function getTimezones(): string[] {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (Intl as any).supportedValuesOf('timeZone')
  } catch {
    // Fallback for environments that don't support this API
    return [
      'UTC', 'America/New_York', 'America/Chicago', 'America/Denver',
      'America/Los_Angeles', 'America/Anchorage', 'Pacific/Honolulu',
      'Europe/London', 'Europe/Paris', 'Europe/Berlin',
      'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Kolkata',
      'Australia/Sydney', 'Pacific/Auckland',
    ]
  }
}

const ALL_TIMEZONES = getTimezones()

const NOTIF_STORAGE_KEY = 'phoenix-notification-prefs'
const API_BASE_STORAGE_KEY = 'phoenix-api-base-url'

interface NotificationPrefs {
  trade_alerts: boolean
  risk_alerts: boolean
  agent_status: boolean
}

function loadNotifPrefs(): NotificationPrefs {
  try {
    const raw = localStorage.getItem(NOTIF_STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return { trade_alerts: true, risk_alerts: true, agent_status: false }
}

// S4: Timezone selector with search
function TimezoneSelect({ value, onChange }: { value: string; onChange: (tz: string) => void }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search.trim()) return ALL_TIMEZONES
    const q = search.toLowerCase()
    return ALL_TIMEZONES.filter(tz => tz.toLowerCase().includes(q))
  }, [search])

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
      >
        <span>{value || 'Select timezone'}</span>
        <svg className="h-4 w-4 opacity-50" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-1 w-full rounded-md border border-border bg-popover shadow-lg">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
              <Search className="h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search timezones..."
                className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                autoFocus
              />
            </div>
            <div className="max-h-60 overflow-y-auto py-1">
              {filtered.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground">No timezones found</div>
              )}
              {filtered.map(tz => (
                <button
                  key={tz}
                  type="button"
                  onClick={() => { onChange(tz); setOpen(false); setSearch('') }}
                  className={`w-full px-3 py-1.5 text-left text-sm hover:bg-muted transition-colors ${
                    tz === value ? 'bg-muted font-medium' : ''
                  }`}
                >
                  {tz}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// S3: Change Password section
function ChangePasswordSection() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: async (payload: { current_password: string; new_password: string }) => {
      await api.put('/api/v2/user/password', payload)
    },
    onSuccess: () => {
      toast.success('Password changed successfully')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setError('')
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'response' in err
        && typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
        ? (err as { response: { data: { detail: string } } }).response.data.detail
        : 'Failed to change password'
      setError(msg)
    },
  })

  function handleSubmit() {
    setError('')

    if (!currentPassword) {
      setError('Current password is required')
      return
    }
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match')
      return
    }
    if (currentPassword === newPassword) {
      setError('New password must be different from current password')
      return
    }

    mutation.mutate({ current_password: currentPassword, new_password: newPassword })
  }

  return (
    <FlexCard title="Change Password">
      <div className="space-y-4 max-w-md">
        <div>
          <Label htmlFor="current-password">Current Password</Label>
          <Input
            id="current-password"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            placeholder="Enter current password"
          />
        </div>
        <div>
          <Label htmlFor="new-password">New Password</Label>
          <Input
            id="new-password"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="At least 8 characters"
          />
        </div>
        <div>
          <Label htmlFor="confirm-password">Confirm New Password</Label>
          <Input
            id="confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Re-enter new password"
          />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button onClick={handleSubmit} disabled={mutation.isPending}>
          <Lock className="h-4 w-4 mr-2" />
          {mutation.isPending ? 'Changing...' : 'Change Password'}
        </Button>
      </div>
    </FlexCard>
  )
}

// S5: 2FA Enrollment section (Coming Soon)
function TwoFactorSection() {
  return (
    <FlexCard title="Two-Factor Authentication">
      <div className="max-w-md space-y-3">
        <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 p-4">
          <ShieldCheck className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium">Coming Soon</p>
            <p className="text-xs text-muted-foreground mt-1">
              Two-factor authentication using TOTP (Time-based One-Time Password) will add an
              extra layer of security to your account. Once available, you will be able to scan a
              QR code with an authenticator app like Google Authenticator or Authy, and verify
              your setup with a 6-digit code.
            </p>
          </div>
        </div>
        <Button disabled variant="outline">
          <ShieldCheck className="h-4 w-4 mr-2" />
          Enable 2FA (Coming Soon)
        </Button>
      </div>
    </FlexCard>
  )
}

export default function SettingsPage() {
  const { theme, setTheme } = useTheme()
  const queryClient = useQueryClient()

  // -- Profile --
  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/user/profile')
        return res.data as { name: string; email: string; timezone: string }
      } catch {
        return { name: 'User', email: 'user@phoenix.io', timezone: 'America/New_York' }
      }
    },
  })

  const [profileName, setProfileName] = useState('')
  const [profileEmail, setProfileEmail] = useState('')
  const [profileTimezone, setProfileTimezone] = useState('America/New_York')

  // Sync form fields when profile data loads
  useEffect(() => {
    if (profile) {
      setProfileName(profile.name ?? '')
      setProfileEmail(profile.email ?? '')
      setProfileTimezone(profile.timezone ?? 'America/New_York')
    }
  }, [profile])

  const profileMutation = useMutation({
    mutationFn: async (data: { name: string; email: string; timezone: string }) => {
      const res = await api.put('/api/v2/user/profile', data)
      return res.data
    },
    onSuccess: () => {
      toast.success('Profile saved successfully')
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    },
    onError: () => {
      toast.error('Failed to save profile')
    },
  })

  const handleProfileSave = () => {
    profileMutation.mutate({ name: profileName, email: profileEmail, timezone: profileTimezone })
  }

  // -- Notifications (localStorage) --
  const [notifPrefs, setNotifPrefs] = useState<NotificationPrefs>(loadNotifPrefs)

  const updateNotifPref = (key: keyof NotificationPrefs, value: boolean) => {
    const updated = { ...notifPrefs, [key]: value }
    setNotifPrefs(updated)
    localStorage.setItem(NOTIF_STORAGE_KEY, JSON.stringify(updated))
    toast.success('Notification preference saved')
  }

  // -- API Base URL (localStorage) --
  const [apiBaseUrl, setApiBaseUrl] = useState(() => {
    return localStorage.getItem(API_BASE_STORAGE_KEY) ?? import.meta.env.VITE_API_URL ?? ''
  })

  const handleApiSave = () => {
    localStorage.setItem(API_BASE_STORAGE_KEY, apiBaseUrl)
    toast.success('API base URL saved')
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Palette} title="Settings" description="Profile, theme, and preferences" />

      <Tabs defaultValue="profile">
        <TabsList className="flex flex-wrap">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="theme">Theme</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="api">API</TabsTrigger>
        </TabsList>

        <TabsContent value="profile" className="mt-4 space-y-6">
          <FlexCard title="Profile Settings">
            <div className="space-y-4 max-w-md">
              <div>
                <Label>Name</Label>
                <Input
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  placeholder="Your name"
                />
              </div>
              <div>
                <Label>Email</Label>
                <Input
                  type="email"
                  value={profileEmail}
                  onChange={(e) => setProfileEmail(e.target.value)}
                  placeholder="email@example.com"
                />
              </div>
              {/* S4: Full timezone list with search */}
              <div>
                <Label>Timezone</Label>
                <TimezoneSelect value={profileTimezone} onChange={setProfileTimezone} />
              </div>
              <Button onClick={handleProfileSave} disabled={profileMutation.isPending}>
                {profileMutation.isPending ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </FlexCard>

          {/* S3: Change Password */}
          <ChangePasswordSection />

          {/* S5: 2FA Enrollment */}
          <TwoFactorSection />
        </TabsContent>

        <TabsContent value="theme" className="mt-4">
          <FlexCard title="Theme">
            <div className="flex items-center justify-between max-w-md">
              <div className="flex items-center gap-2">
                <Palette className="h-4 w-4" />
                <span>Dark mode</span>
              </div>
              <Switch checked={theme === 'dark'} onCheckedChange={(c) => setTheme(c ? 'dark' : 'light')} />
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="notifications" className="mt-4">
          <FlexCard title="Notification Preferences">
            <div className="space-y-4 max-w-md">
              <div className="flex items-center justify-between">
                <Label>Trade alerts</Label>
                <Switch
                  checked={notifPrefs.trade_alerts}
                  onCheckedChange={(v) => updateNotifPref('trade_alerts', v)}
                />
              </div>
              <div className="flex items-center justify-between">
                <Label>Risk alerts</Label>
                <Switch
                  checked={notifPrefs.risk_alerts}
                  onCheckedChange={(v) => updateNotifPref('risk_alerts', v)}
                />
              </div>
              <div className="flex items-center justify-between">
                <Label>Agent status</Label>
                <Switch
                  checked={notifPrefs.agent_status}
                  onCheckedChange={(v) => updateNotifPref('agent_status', v)}
                />
              </div>
            </div>
          </FlexCard>
        </TabsContent>

        <TabsContent value="api" className="mt-4">
          <FlexCard title="API Configuration">
            <div className="space-y-4 max-w-md">
              <div>
                <Label>API Base URL</Label>
                <Input
                  value={apiBaseUrl}
                  onChange={(e) => setApiBaseUrl(e.target.value)}
                  placeholder="https://api.phoenix.io"
                />
              </div>
              <Button onClick={handleApiSave}>Save</Button>
            </div>
          </FlexCard>
        </TabsContent>
      </Tabs>
    </div>
  )
}
