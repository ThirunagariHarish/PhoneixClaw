/**
 * App shell: sidebar (desktop) + bottom nav (mobile). M1.4.
 * Reference: Milestones.md M1.4, ImplementationPlan.md.
 */
import { Outlet, NavLink } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useTheme } from '@/context/ThemeContext'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard,
  TrendingUp,
  BarChart3,
  Bot,
  Target,
  Plug,
  BookOpen,
  LineChart,
  Settings,
  Shield,
  Network,
  ListTodo,
  Moon,
  Sun,
  LogOut,
} from 'lucide-react'

const NAV_ITEMS = [
  { to: '/trades', icon: LayoutDashboard, label: 'Trades' },
  { to: '/positions', icon: TrendingUp, label: 'Positions' },
  { to: '/performance', icon: BarChart3, label: 'Performance' },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/strategies', icon: Target, label: 'Strategies' },
  { to: '/connectors', icon: Plug, label: 'Connectors' },
  { to: '/skills', icon: BookOpen, label: 'Skills' },
  { to: '/market', icon: LineChart, label: 'Market' },
  { to: '/admin', icon: Shield, label: 'Admin' },
  { to: '/network', icon: Network, label: 'Network' },
  { to: '/tasks', icon: ListTodo, label: 'Tasks' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function AppShell() {
  const { user, logout } = useAuth()
  const { theme, setTheme } = useTheme()

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      {/* Sidebar — hidden on mobile */}
      <aside
        className={cn(
          'hidden md:flex flex-col w-56 border-r border-border bg-card',
          'fixed inset-y-0 left-0 z-40'
        )}
      >
        <div className="p-4 border-b border-border">
          <h1 className="text-lg font-semibold">Phoenix v2</h1>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )
              }
            >
              <Icon className="h-5 w-5 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t border-border space-y-1">
          <button
            type="button"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:bg-muted"
          >
            {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
          <button
            type="button"
            onClick={logout}
            className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:bg-muted"
          >
            <LogOut className="h-5 w-5" />
            Logout
          </button>
          {user && (
            <div className="px-3 py-2 text-xs text-muted-foreground truncate">
              {user.email}
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 md:pl-56 pb-16 md:pb-0">
        <div className="p-4">
          <Outlet />
        </div>
      </main>

      {/* Bottom nav — mobile only */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card flex justify-around py-2 safe-area-pb">
        {NAV_ITEMS.slice(0, 5).map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex flex-col items-center gap-1 px-2 py-1 text-xs',
                isActive ? 'text-primary' : 'text-muted-foreground'
              )
            }
          >
            <Icon className="h-5 w-5" />
            {label}
          </NavLink>
        ))}
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            cn(
              'flex flex-col items-center gap-1 px-2 py-1 text-xs',
              isActive ? 'text-primary' : 'text-muted-foreground'
            )
          }
        >
          <Settings className="h-5 w-5" />
          More
        </NavLink>
      </nav>
    </div>
  )
}
