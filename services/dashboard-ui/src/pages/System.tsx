import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Activity, Bell, CheckCircle2, XCircle } from 'lucide-react'

export default function System() {
  const { data: health } = useQuery({
    queryKey: ['system-health'],
    queryFn: () => axios.get('/api/v1/system/health').then((r) => r.data),
  })
  const { data: notifications } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => axios.get('/api/v1/notifications?limit=10').then((r) => r.data),
  })

  return (
    <div className="space-y-6">
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
            {!health?.services && (
              <p className="text-sm text-muted-foreground col-span-full">Loading service health...</p>
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
