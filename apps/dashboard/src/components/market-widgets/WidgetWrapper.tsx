/**
 * WidgetWrapper: widget chrome with drag handle, settings, remove, and link group indicator.
 */
import { Button } from '@/components/ui/button'
import { GripVertical, X, Settings } from 'lucide-react'

interface Props {
  title: string
  icon: React.ElementType
  children: React.ReactNode
  onRemove: () => void
  onSettings?: () => void
  hasSettings?: boolean
  /** MCP-3: colored dot for the link group */
  linkGroupColor?: string
}

export default function WidgetWrapper({ title, icon: Icon, children, onRemove, onSettings, hasSettings, linkGroupColor }: Props) {
  return (
    <div className="h-full flex flex-col rounded-lg border bg-card shadow-sm overflow-hidden">
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b bg-muted/30 shrink-0 drag-handle cursor-grab active:cursor-grabbing">
        <GripVertical className="h-3 w-3 text-muted-foreground" />
        <Icon className="h-3 w-3 text-purple-500" />
        <span className="text-[11px] font-medium truncate flex-1">{title}</span>
        {linkGroupColor && (
          <span
            className="h-2.5 w-2.5 rounded-full shrink-0 ring-1 ring-background"
            style={{ backgroundColor: linkGroupColor }}
            title="Linked group"
          />
        )}
        {hasSettings && (
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 text-muted-foreground hover:text-purple-400"
            onClick={onSettings}
            onMouseDown={e => e.stopPropagation()}
          >
            <Settings className="h-3 w-3" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
          onMouseDown={e => e.stopPropagation()}
        >
          <X className="h-3 w-3" />
        </Button>
      </div>
      <div className="flex-1 overflow-hidden p-0 min-h-0">
        {children}
      </div>
    </div>
  )
}
