import { cn } from '@/lib/utils'

interface SubProgressBarProps {
  step: string
  message: string
  percent: number
}

/**
 * SubProgressBar — granular progress for long-running steps (enrich, preprocess, train, etc.).
 * Displays a linear progress bar with message overlay and percentage label.
 */
export default function SubProgressBar({ step, message, percent }: SubProgressBarProps) {
  const clampedPercent = Math.max(0, Math.min(100, percent))

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-muted-foreground">{step}</span>
        <span className="font-mono text-muted-foreground">{clampedPercent}%</span>
      </div>
      <div className="relative h-8 bg-slate-800 rounded-lg overflow-hidden border border-slate-700">
        {/* Progress fill */}
        <div
          className="absolute inset-y-0 left-0 bg-indigo-500 transition-all duration-300 ease-out"
          style={{ width: `${clampedPercent}%` }}
        />
        {/* Message overlay */}
        <div className="relative h-full flex items-center px-3">
          <span className={cn(
            'text-xs font-medium truncate transition-colors',
            clampedPercent > 50 ? 'text-white' : 'text-slate-300'
          )}>
            {message}
          </span>
        </div>
      </div>
    </div>
  )
}
