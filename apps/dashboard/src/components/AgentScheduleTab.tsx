/**
 * P5 + P11: Schedule tab — shows per-agent tasks, automations, and crons,
 * with an inline "add cron" form.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Plus, Trash2, Clock, ListChecks } from 'lucide-react'
import { toast } from 'sonner'

interface Cron {
  id: string
  name: string
  cron_expression: string
  action_type: string
  enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  run_count: number
}

interface Task {
  id: string
  title: string
  status: string
  priority?: string
  due_date?: string
}

interface Automation {
  id: string
  name: string
  cron_expression: string
  natural_language?: string
  is_active: boolean
  last_run_at: string | null
  next_run_at: string | null
  run_count: number
}

export function AgentScheduleTab({ agentId }: { agentId: string }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [cronExpr, setCronExpr] = useState('*/15 9-16 * * 1-5')

  const { data: cronsData } = useQuery<{ crons: Cron[] }>({
    queryKey: ['agent-crons', agentId],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}/crons`)).data,
    refetchInterval: 15000,
  })
  const { data: tasksData } = useQuery<{ tasks: Task[] }>({
    queryKey: ['agent-tasks', agentId],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}/tasks`)).data,
    refetchInterval: 15000,
  })
  const { data: autosData } = useQuery<{ automations: Automation[] }>({
    queryKey: ['agent-automations', agentId],
    queryFn: async () => (await api.get(`/api/v2/agents/${agentId}/automations`)).data,
    refetchInterval: 15000,
  })

  const createCron = useMutation({
    mutationFn: async () => {
      return (await api.post(`/api/v2/agents/${agentId}/crons`, {
        name,
        cron_expression: cronExpr,
        action_type: 'prompt',
        action_payload: { prompt: `Scheduled run: ${name}` },
        enabled: true,
      })).data
    },
    onSuccess: () => {
      toast.success('Cron created')
      setName('')
      qc.invalidateQueries({ queryKey: ['agent-crons', agentId] })
    },
    onError: (e) => toast.error(`Failed: ${String(e)}`),
  })

  const deleteCron = useMutation({
    mutationFn: async (cronId: string) => {
      return (await api.delete(`/api/v2/agents/${agentId}/crons/${cronId}`)).data
    },
    onSuccess: () => {
      toast.success('Cron deleted')
      qc.invalidateQueries({ queryKey: ['agent-crons', agentId] })
    },
  })

  return (
    <div className="space-y-4">
      {/* Crons */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Per-Agent Crons
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2 items-center">
            <Input
              placeholder="Name (e.g. Hourly sweep)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="flex-1"
            />
            <Input
              placeholder="cron expression"
              value={cronExpr}
              onChange={(e) => setCronExpr(e.target.value)}
              className="w-48 font-mono text-xs"
            />
            <Button
              size="sm"
              disabled={!name || createCron.isPending}
              onClick={() => createCron.mutate()}
            >
              <Plus className="w-4 h-4 mr-1" /> Add
            </Button>
          </div>

          {(cronsData?.crons ?? []).length === 0 ? (
            <div className="text-sm text-muted-foreground">No crons — add one above.</div>
          ) : (
            <div className="space-y-1">
              {cronsData!.crons.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between p-2 rounded border border-border/50"
                >
                  <div className="flex-1">
                    <div className="text-sm font-medium">{c.name}</div>
                    <div className="text-xs text-muted-foreground font-mono">
                      {c.cron_expression} · ran {c.run_count}x
                      {c.last_run_at
                        ? ` · last ${new Date(c.last_run_at).toLocaleString()}`
                        : ''}
                    </div>
                  </div>
                  <Badge variant={c.enabled ? 'default' : 'outline'} className="mr-2 text-xs">
                    {c.enabled ? 'on' : 'off'}
                  </Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => deleteCron.mutate(c.id)}
                  >
                    <Trash2 className="w-3 h-3" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Global automations scoped to this agent */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Automations
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(autosData?.automations ?? []).length === 0 ? (
            <div className="text-sm text-muted-foreground">No automations assigned.</div>
          ) : (
            <div className="space-y-2">
              {autosData!.automations.map((a) => (
                <div key={a.id} className="p-2 rounded border border-border/50">
                  <div className="text-sm font-medium">{a.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">
                    {a.cron_expression}
                  </div>
                  {a.natural_language && (
                    <div className="text-xs mt-1">{a.natural_language}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Tasks */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <ListChecks className="w-4 h-4" />
            Tasks
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(tasksData?.tasks ?? []).length === 0 ? (
            <div className="text-sm text-muted-foreground">No tasks.</div>
          ) : (
            <div className="space-y-1">
              {tasksData!.tasks.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between text-sm p-2 rounded border border-border/50"
                >
                  <span>{t.title}</span>
                  <Badge variant="outline" className="text-xs">
                    {t.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
