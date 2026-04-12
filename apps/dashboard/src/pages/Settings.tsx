/**
 * Settings page — profile, theme, notifications, API config.
 * All Save buttons are wired: profile persists to backend, notifications
 * and API base URL persist to localStorage.
 */
import { useState, useEffect } from 'react'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Palette } from 'lucide-react'

const TIMEZONES = ['UTC', 'America/New_York', 'America/Los_Angeles', 'Europe/London', 'Asia/Tokyo']

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

export default function SettingsPage() {
  const { theme, setTheme } = useTheme()
  const queryClient = useQueryClient()

  // ── Profile ──────────────────────────────────────────────
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

  // ── Notifications (localStorage) ────────────────────────
  const [notifPrefs, setNotifPrefs] = useState<NotificationPrefs>(loadNotifPrefs)

  const updateNotifPref = (key: keyof NotificationPrefs, value: boolean) => {
    const updated = { ...notifPrefs, [key]: value }
    setNotifPrefs(updated)
    localStorage.setItem(NOTIF_STORAGE_KEY, JSON.stringify(updated))
    toast.success('Notification preference saved')
  }

  // ── API Base URL (localStorage) ─────────────────────────
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

        <TabsContent value="profile" className="mt-4">
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
              <div>
                <Label>Timezone</Label>
                <Select value={profileTimezone} onValueChange={setProfileTimezone}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {TIMEZONES.map((tz) => (
                      <SelectItem key={tz} value={tz}>{tz}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={handleProfileSave} disabled={profileMutation.isPending}>
                {profileMutation.isPending ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </FlexCard>
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
