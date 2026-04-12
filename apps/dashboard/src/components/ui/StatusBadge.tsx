/**
 * StatusBadge: status indicator with optional animated dot and semantic colors.
 */
import { cn } from '@/lib/utils'
import { Badge, type BadgeProps } from '@/components/ui/badge'

const statusVariant: Record<string, BadgeProps['variant']> = {
  active: 'default',
  online: 'success',
  running: 'success',
  success: 'success',
  completed: 'success',
  idle: 'secondary',
  paused: 'warning',
  backlog: 'secondary',
  in_progress: 'default',
  'setting up': 'warning',
  starting: 'warning',
  under_review: 'warning',
  offline: 'destructive',
  error: 'destructive',
  failed: 'destructive',
}

const statusDotAnimated = new Set(['active', 'online', 'running', 'setting up', 'starting'])

export interface StatusBadgeProps {
  status: string
  showDot?: boolean
  className?: string
}

export function StatusBadge({ status, showDot = true, className }: StatusBadgeProps) {
  const variant = statusVariant[status.toLowerCase()] ?? 'outline'
  const animate = showDot && statusDotAnimated.has(status.toLowerCase())

  return (
    <Badge variant={variant} className={cn('inline-flex items-center gap-1.5 capitalize', className)}>
      {showDot && (
        <span
          className={cn(
            'h-1.5 w-1.5 shrink-0 rounded-full',
            variant === 'success' && 'bg-emerald-500',
            variant === 'destructive' && 'bg-red-500',
            variant === 'warning' && 'bg-amber-500',
            variant === 'secondary' && 'bg-zinc-400 dark:bg-zinc-500',
            variant === 'default' && 'bg-primary',
            animate && 'animate-pulse',
          )}
          aria-hidden
        />
      )}
      {status}
    </Badge>
  )
}
