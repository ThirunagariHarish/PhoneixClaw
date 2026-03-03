/**
 * SidePanel: slide-over panel (Sheet). M1.5 composite.
 */
import * as React from 'react'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'

export interface SidePanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title?: string
  description?: string
  side?: 'left' | 'right'
  children: React.ReactNode
}

export function SidePanel({
  open,
  onOpenChange,
  title,
  description,
  side = 'right',
  children,
}: SidePanelProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side={side}>
        {(title || description) && (
          <SheetHeader>
            {title && <SheetTitle>{title}</SheetTitle>}
            {description && <SheetDescription>{description}</SheetDescription>}
          </SheetHeader>
        )}
        <div className="mt-4">{children}</div>
      </SheetContent>
    </Sheet>
  )
}
