/**
 * EmptyState: placeholder when no data. M1.5 composite.
 */
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  title?: string
  description?: string
  action?: React.ReactNode
  className?: string
}

export function EmptyState({
  title = 'No data',
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-12 text-center', className)}>
      <p className="text-lg font-medium text-muted-foreground">{title}</p>
      {description && <p className="text-sm text-muted-foreground mt-1 max-w-sm">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
