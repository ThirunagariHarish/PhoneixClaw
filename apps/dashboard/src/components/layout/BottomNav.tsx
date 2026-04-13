/**
 * Bottom navigation bar for mobile — shows key tabs with swipe-friendly touch targets.
 * M1.13: Mobile responsive foundation.
 */
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard,
  TrendingUp,
  BarChart3,
  Bot,
  MoreHorizontal,
} from 'lucide-react'
import { useState } from 'react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Target,
  Plug,
  BookOpen,
  LineChart,
  Settings,
  Shield,
  ListTodo,
  Server,
} from 'lucide-react'

const PRIMARY_TABS = [
  { to: '/trades', icon: LayoutDashboard, label: 'Trades' },
  { to: '/positions', icon: TrendingUp, label: 'Positions' },
  { to: '/performance', icon: BarChart3, label: 'Performance' },
  { to: '/agents', icon: Bot, label: 'Agents' },
]

const MORE_TABS = [
  { to: '/strategies', icon: Target, label: 'Strategies' },
  { to: '/connectors', icon: Plug, label: 'Connectors' },
  { to: '/skills', icon: BookOpen, label: 'Skills' },
  { to: '/market', icon: LineChart, label: 'Market' },
  { to: '/admin', icon: Shield, label: 'Admin' },
  { to: '/tasks', icon: ListTodo, label: 'Tasks' },
  { to: '/settings', icon: Settings, label: 'Settings' },
  { to: '/platform-health', icon: Server, label: 'Platform Health' },
]

export function BottomNav() {
  const [moreOpen, setMoreOpen] = useState(false)

  return (
    <>
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card safe-area-pb">
        <div className="flex justify-around py-1">
          {PRIMARY_TABS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex flex-col items-center gap-0.5 px-3 py-2 min-w-[44px] min-h-[44px] text-xs touch-manipulation',
                  isActive ? 'text-primary' : 'text-muted-foreground'
                )
              }
            >
              <Icon className="h-5 w-5" />
              <span className="truncate">{label}</span>
            </NavLink>
          ))}
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            className="flex flex-col items-center gap-0.5 px-3 py-2 min-w-[44px] min-h-[44px] text-xs text-muted-foreground touch-manipulation"
          >
            <MoreHorizontal className="h-5 w-5" />
            <span>More</span>
          </button>
        </div>
      </nav>

      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent side="bottom" className="rounded-t-2xl">
          <SheetHeader>
            <SheetTitle>More</SheetTitle>
          </SheetHeader>
          <div className="grid grid-cols-4 gap-4 py-4">
            {MORE_TABS.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => setMoreOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'flex flex-col items-center gap-1.5 p-3 rounded-lg min-h-[64px] touch-manipulation',
                    isActive ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted'
                  )
                }
              >
                <Icon className="h-6 w-6" />
                <span className="text-xs text-center">{label}</span>
              </NavLink>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
