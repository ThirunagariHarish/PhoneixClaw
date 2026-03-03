/**
 * StatusBadge: status indicator with semantic colors. M1.5 composite.
 */
import { cn } from '@/lib/utils'
import { Badge, type BadgeProps } from '@/components/ui/badge'

const statusVariant: Record<string, BadgeProps['variant']> = {
  active: 'default',
  online: 'default',
  running: 'default',
  success: 'success',
  idle: 'secondary',
  paused: 'secondary',
  offline: 'destructive',
  error: 'destructive',
  failed: 'destructive',
}

export interface StatusBadgeProps {
  status: string
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const variant = statusVariant[status.toLowerCase()] ?? 'outline'
  return (
    <Badge variant={variant} className={cn('capitalize', className)}>
      {status}
    </Badge>
  )
}
