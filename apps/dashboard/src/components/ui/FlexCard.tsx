/**
 * FlexCard: card with flexible content area. M1.5 composite.
 */
import * as React from 'react'
import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export interface FlexCardProps {
  title?: string
  children: React.ReactNode
  action?: React.ReactNode
  className?: string
}

export function FlexCard({ title, children, action, className }: FlexCardProps) {
  return (
    <Card className={cn(className)}>
      {(title || action) && (
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          {title && <CardTitle className="text-sm font-medium">{title}</CardTitle>}
          {action}
        </CardHeader>
      )}
      <CardContent>{children}</CardContent>
    </Card>
  )
}
