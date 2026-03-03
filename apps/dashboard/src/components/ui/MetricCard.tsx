/**
 * MetricCard: single metric display. M1.5 composite.
 */
import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader } from '@/components/ui/card'

export interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  trend?: 'up' | 'down' | 'neutral'
  className?: string
}

export function MetricCard({ title, value, subtitle, trend, className }: MetricCardProps) {
  return (
    <Card className={cn(className)}>
      <CardHeader className="pb-1">
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
      </CardHeader>
      <CardContent>
        <p className={cn(
          'text-2xl font-semibold',
          trend === 'up' && 'text-emerald-600 dark:text-emerald-400',
          trend === 'down' && 'text-red-600 dark:text-red-400',
        )}>
          {value}
        </p>
        {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  )
}
