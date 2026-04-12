/**
 * Emergency Kill Switch component.
 *
 * Renders a red button that opens a confirmation dialog.  On confirm it
 * calls POST /api/v2/emergency/kill-switch and shows a results toast.
 * The button pulses red when the kill switch is active.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

interface KillSwitchResult {
  agents_paused: number
  orders_cancelled: number
  positions_closing: number
}

interface KillSwitchStatus {
  active: boolean
  activated_at: string | null
  reason: string | null
}

export function KillSwitchButton({ variant = 'topbar' }: { variant?: 'topbar' | 'card' }) {
  const [open, setOpen] = useState(false)
  const [closePositions, setClosePositions] = useState(false)
  const [reason, setReason] = useState('')
  const queryClient = useQueryClient()

  const { data: status } = useQuery<KillSwitchStatus>({
    queryKey: ['kill-switch-status'],
    queryFn: async () => (await api.get('/api/v2/emergency/status')).data,
    refetchInterval: 15_000,
  })

  const mutation = useMutation<KillSwitchResult, Error, void>({
    mutationFn: async () => {
      const res = await api.post('/api/v2/emergency/kill-switch', {
        close_positions: closePositions,
        reason,
      })
      return res.data
    },
    onSuccess: (data) => {
      toast.success(
        `Kill switch activated: paused ${data.agents_paused} agents, cancelled ${data.orders_cancelled} orders` +
          (data.positions_closing > 0 ? `, closing ${data.positions_closing} positions` : ''),
      )
      queryClient.invalidateQueries({ queryKey: ['kill-switch-status'] })
      queryClient.invalidateQueries({ queryKey: ['kill-switch-history'] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setOpen(false)
      setReason('')
      setClosePositions(false)
    },
    onError: (err) => {
      toast.error(`Kill switch failed: ${err.message}`)
    },
  })

  const isActive = status?.active ?? false

  if (variant === 'topbar') {
    return (
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button
            variant="destructive"
            size="sm"
            className={cn(
              'gap-1.5 font-semibold text-xs',
              isActive && 'animate-pulse',
            )}
          >
            <ShieldAlert className="h-4 w-4" />
            <span className="hidden sm:inline">
              {isActive ? 'KILL SWITCH ACTIVE' : 'Kill Switch'}
            </span>
          </Button>
        </DialogTrigger>
        <KillSwitchDialogContent
          closePositions={closePositions}
          setClosePositions={setClosePositions}
          reason={reason}
          setReason={setReason}
          isPending={mutation.isPending}
          onActivate={() => mutation.mutate()}
        />
      </Dialog>
    )
  }

  // Card variant for Risk page
  return (
    <div
      className={cn(
        'rounded-lg border-2 p-4 sm:p-6',
        isActive
          ? 'border-red-500 bg-red-500/10'
          : 'border-red-500/40 bg-red-500/5',
      )}
    >
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'flex h-12 w-12 items-center justify-center rounded-full',
              isActive ? 'bg-red-500 text-white animate-pulse' : 'bg-red-500/20 text-red-500',
            )}
          >
            <ShieldAlert className="h-6 w-6" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-red-600 dark:text-red-400">
              Emergency Kill Switch
            </h3>
            <p className="text-sm text-muted-foreground">
              {isActive
                ? `Active since ${status?.activated_at ? new Date(status.activated_at).toLocaleString() : 'unknown'} -- ${status?.reason ?? ''}`
                : 'Immediately pause all agents and cancel pending orders'}
            </p>
          </div>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button
              variant="destructive"
              size="lg"
              className={cn('font-bold', isActive && 'animate-pulse')}
            >
              <ShieldAlert className="h-5 w-5 mr-2" />
              {isActive ? 'KILL SWITCH ACTIVE' : 'ACTIVATE KILL SWITCH'}
            </Button>
          </DialogTrigger>
          <KillSwitchDialogContent
            closePositions={closePositions}
            setClosePositions={setClosePositions}
            reason={reason}
            setReason={setReason}
            isPending={mutation.isPending}
            onActivate={() => mutation.mutate()}
          />
        </Dialog>
      </div>
    </div>
  )
}

function KillSwitchDialogContent({
  closePositions,
  setClosePositions,
  reason,
  setReason,
  isPending,
  onActivate,
}: {
  closePositions: boolean
  setClosePositions: (v: boolean) => void
  reason: string
  setReason: (v: string) => void
  isPending: boolean
  onActivate: () => void
}) {
  return (
    <DialogContent className="border-red-500/50">
      <DialogHeader>
        <DialogTitle className="text-red-600 dark:text-red-400 text-xl flex items-center gap-2">
          <ShieldAlert className="h-6 w-6" />
          EMERGENCY KILL SWITCH
        </DialogTitle>
        <DialogDescription className="text-base pt-2">
          This will immediately pause all running agents and cancel all pending
          orders. This action cannot be undone automatically.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4 py-2">
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={closePositions}
            onChange={(e) => setClosePositions(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-500"
          />
          <span className="text-sm font-medium">Also close all open positions</span>
        </label>

        <div>
          <label htmlFor="kill-reason" className="block text-sm font-medium mb-1">
            Reason (required)
          </label>
          <input
            id="kill-reason"
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Market crash, rogue agent, emergency stop"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
        </div>
      </div>

      <DialogFooter className="gap-2 sm:gap-0">
        <Button
          variant="outline"
          onClick={() => {
            const trigger = document.querySelector('[data-state="open"]')
            if (trigger) (trigger as HTMLElement).click()
          }}
          disabled={isPending}
        >
          Cancel
        </Button>
        <Button
          variant="destructive"
          onClick={onActivate}
          disabled={isPending || reason.trim().length === 0}
          className="font-bold"
        >
          {isPending ? 'Activating...' : 'ACTIVATE KILL SWITCH'}
        </Button>
      </DialogFooter>
    </DialogContent>
  )
}

export function KillSwitchHistory() {
  const { data: history = [] } = useQuery<
    Array<{
      id: string
      activated_at: string
      reason: string
      agents_paused: number
      orders_cancelled: number
      positions_closing: number
    }>
  >({
    queryKey: ['kill-switch-history'],
    queryFn: async () => (await api.get('/api/v2/emergency/history?limit=5')).data,
  })

  if (history.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        No kill switch activations recorded.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {history.map((item) => (
        <div
          key={item.id}
          className="flex flex-col sm:flex-row sm:items-center justify-between rounded-lg border p-3 text-sm gap-2"
        >
          <div className="space-y-0.5">
            <p className="font-medium">{item.reason}</p>
            <p className="text-xs text-muted-foreground">
              {new Date(item.activated_at).toLocaleString()}
            </p>
          </div>
          <div className="flex gap-3 text-xs text-muted-foreground">
            <span>{item.agents_paused} paused</span>
            <span>{item.orders_cancelled} cancelled</span>
            {item.positions_closing > 0 && (
              <span>{item.positions_closing} closing</span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
