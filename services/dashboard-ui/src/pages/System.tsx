import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Activity, Bell, CheckCircle2, XCircle, ShieldAlert, Power, Loader2 } from 'lucide-react'

export default function System() {
  const qc = useQueryClient()
  const [killMsg, setKillMsg] = useState<string | null>(null)

  const { data: health, isLoading: healthLoading, isError: healthError, refetch: refetchHealth } = useQuery({
    queryKey: ['system-health'],
    queryFn: () => axios.get('/api/v1/system/health').then((r) => r.data),
    refetchInterval: 10000,
  })
  const { data: notifications } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => axios.get('/api/v1/notifications?limit=10').then((r) => r.data),
  })
  const { data: systemConfig } = useQuery({
    queryKey: ['system-config'],
    queryFn: () => axios.get('/api/v1/system/config').then((r) => r.data),
  })

  const killMut = useMutation({
    mutationFn: () => axios.post('/api/v1/system/kill-switch'),
    onSuccess: (res) => {
      const active = res.data.kill_switch_active
      setKillMsg(active ? 'Kill switch ACTIVATED — trading disabled' : 'Trading RE-ENABLED')
      qc.invalidateQueries({ queryKey: ['system-config'] })
      setTimeout(() => setKillMsg(null), 3000)
    },
  })

  const tradingEnabled = systemConfig?.enable_trading?.value ?? true

  return (
    <div className="space-y-6">
      {killMsg && (
        <div className="rounded-lg border border-yellow-500/50 bg-yellow-500/10 p-3 text-yellow-600 text-sm">
          {killMsg}
        </div>
      )}

      <Card className={!tradingEnabled ? 'border-red-500/50' : ''}>
        <CardHeader className="flex flex-row items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-red-500" />
          <CardTitle className="text-base">Kill Switch</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Trading Status</p>
              <p className="text-xs text-muted-foreground mt-1">
                {tradingEnabled
                  ? 'Trading is active. Press to disable all trade execution.'
                  : 'Trading is DISABLED. Press to re-enable.'}
              </p>
            </div>
            <Button
              variant={tradingEnabled ? 'destructive' : 'default'}
              onClick={() => killMut.mutate()}
              disabled={killMut.isPending}
            >
              <Power className="h-4 w-4 mr-2" />
              {tradingEnabled ? 'Disable Trading' : 'Enable Trading'}
            </Button>
          </div>
          {!tradingEnabled && (
            <Badge variant="destructive" className="mt-3">KILL SWITCH ACTIVE</Badge>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center gap-2">
          <Activity className="h-5 w-5 text-primary" />
          <CardTitle className="text-base">Service Health</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {health?.services &&
              Object.entries(health.services).map(([name, status]) => {
                const healthy = (status as string) === 'healthy'
                return (
                  <div
                    key={name}
                    className="flex items-center gap-3 rounded-lg border border-border p-3"
                  >
                    {healthy ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{name}</p>
                      <Badge variant={healthy ? 'success' : 'destructive'} className="mt-1 text-[10px]">
                        {status as string}
                      </Badge>
                    </div>
                  </div>
                )
              })}
            {healthLoading && (
              <div className="flex justify-center py-4 col-span-full"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
            )}
            {healthError && (
              <div className="col-span-full text-center py-4">
                <p className="text-sm text-destructive">Failed to load health data</p>
                <Button variant="outline" size="sm" className="mt-2" onClick={() => refetchHealth()}>Retry</Button>
              </div>
            )}
            {!healthLoading && !healthError && !health?.services && (
              <p className="text-sm text-muted-foreground col-span-full">No service data available</p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center gap-2">
          <Bell className="h-5 w-5 text-primary" />
          <CardTitle className="text-base">Recent Notifications</CardTitle>
        </CardHeader>
        <CardContent>
          {(!notifications || notifications.length === 0) ? (
            <div className="flex flex-col items-center py-8 text-center">
              <Bell className="h-10 w-10 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">No notifications yet</p>
            </div>
          ) : (
            <ScrollArea className="max-h-[400px]">
              <div className="space-y-2">
                {(notifications || []).map(
                  (n: { id: number; title: string; body: string; created_at?: string }) => (
                    <div key={n.id} className="rounded-lg border border-border p-3">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-medium">{n.title}</p>
                        {n.created_at && (
                          <span className="text-[11px] text-muted-foreground">
                            {new Date(n.created_at).toLocaleString()}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{n.body}</p>
                    </div>
                  ),
                )}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
