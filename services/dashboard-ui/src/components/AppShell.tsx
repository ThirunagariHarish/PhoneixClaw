import { useState, useEffect } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useAuth } from '../hooks/useAuth'
import { useTheme } from './ThemeProvider'
import { Button } from './ui/button'
import { Avatar, AvatarFallback } from './ui/avatar'
import { Separator } from './ui/separator'
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from './ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'
import { ScrollArea } from './ui/scroll-area'
import {
  LayoutDashboard,
  Database,
  Wallet,
  BarChart3,
  MessageSquare,
  Settings,
  LogOut,
  Menu,
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeft,
  TrendingUp,
  ShieldCheck,
  UserCog,
  LineChart,
  Workflow,
  KanbanSquare,
  Bell,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface Notification {
  id: number
  type: string
  title: string
  body: string
  read: boolean
  created_at: string | null
}

const baseNavItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/positions', icon: TrendingUp, label: 'Positions' },
  { to: '/pipelines', icon: Workflow, label: 'Trade Pipelines' },
  { to: '/backtest', icon: LineChart, label: 'Backtesting' },
  { to: '/sources', icon: Database, label: 'Data Sources' },
  { to: '/accounts', icon: Wallet, label: 'Trading Accounts' },
  { to: '/messages', icon: MessageSquare, label: 'Raw Messages' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/system', icon: Settings, label: 'System' },
]

const adminNavItems = [
  { to: '/access', icon: UserCog, label: 'Access Management' },
  { to: '/admin', icon: ShieldCheck, label: 'Admin Panel' },
  { to: '/board', icon: KanbanSquare, label: 'Sprint Board' },
]

function NavItem({
  to,
  icon: Icon,
  label,
  collapsed,
}: {
  to: string
  icon: React.ElementType
  label: string
  collapsed: boolean
}) {
  const content = (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200',
          isActive
            ? 'bg-primary/10 text-primary shadow-sm'
            : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
          collapsed && 'justify-center px-2',
        )
      }
    >
      <Icon className="h-5 w-5 shrink-0" />
      {!collapsed && <span>{label}</span>}
    </NavLink>
  )

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{content}</TooltipTrigger>
        <TooltipContent side="right">{label}</TooltipContent>
      </Tooltip>
    )
  }
  return content
}

function SidebarContent({
  collapsed,
  onCollapse,
  onLogout,
  navItems,
  displayName = 'User',
  initials = 'U',
  role,
}: {
  collapsed: boolean
  onCollapse?: () => void
  onLogout: () => void
  navItems: typeof baseNavItems
  displayName?: string
  initials?: string
  role?: string
}) {
  const { theme, setTheme } = useTheme()

  return (
    <div className="flex h-full flex-col">
      <div className={cn('flex items-center gap-3 border-b border-border px-4 py-5', collapsed && 'justify-center px-2')}>
        <img src="/phoenix-logo.png" alt="PhoenixTrade" className="h-8 w-8" />
        {!collapsed && <span className="text-lg font-bold tracking-tight">PhoenixTrade</span>}
      </div>

      <ScrollArea className="flex-1 px-3 py-4">
        <nav className="space-y-1">
          {navItems.map((item) => (
            <NavItem key={item.to} {...item} collapsed={collapsed} />
          ))}
        </nav>
      </ScrollArea>

      <div className="mt-auto border-t border-border p-3 space-y-2">
        <div className={cn('flex items-center', collapsed ? 'justify-center' : 'justify-between')}>
          {!collapsed && <span className="text-xs text-muted-foreground">Theme</span>}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>

        {onCollapse && (
          <div className={cn('flex items-center', collapsed ? 'justify-center' : 'justify-between')}>
            {!collapsed && <span className="text-xs text-muted-foreground">Collapse</span>}
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onCollapse}>
              {collapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            </Button>
          </div>
        )}

        <Separator />

        <div className={cn('flex items-center gap-3', collapsed && 'justify-center')}>
          <Avatar className="h-8 w-8">
            <AvatarFallback className="bg-primary/10 text-primary text-xs">{initials}</AvatarFallback>
          </Avatar>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{displayName}</p>
              {role && <p className="text-[10px] text-muted-foreground leading-tight">{role}</p>}
            </div>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={onLogout}>
                <LogOut className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side={collapsed ? 'right' : 'top'}>Sign out</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </div>
  )
}

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/positions': 'Positions',
  '/pipelines': 'Trade Pipelines',
  '/backtest': 'Backtesting',
  '/sources': 'Data Sources',
  '/accounts': 'Trading Accounts',
  '/messages': 'Raw Messages',
  '/analytics': 'Analytics',
  '/system': 'System',
  '/access': 'Access Management',
  '/admin': 'Admin Panel',
  '/board': 'Sprint Board',
}

function getInitials(name: string | null | undefined, email: string | null | undefined): string {
  if (name) {
    const parts = name.trim().split(/\s+/)
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    return name.slice(0, 2).toUpperCase()
  }
  if (email) return email.slice(0, 2).toUpperCase()
  return 'U'
}

function getDisplayName(name: string | null | undefined, email: string | null | undefined): string {
  if (name) return name
  if (email) return email.split('@')[0]
  return 'User'
}

export default function AppShell() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [bellOpen, setBellOpen] = useState(false)
  const { logout, isAdmin, user } = useAuth()
  const qc = useQueryClient()
  const location = useLocation()
  const pageTitle = pageTitles[location.pathname]
    || (location.pathname.startsWith('/board/') ? 'Task Detail' : 'PhoenixTrade')
  const navItems = isAdmin ? [...baseNavItems, ...adminNavItems] : baseNavItems
  const displayName = getDisplayName(user?.name, user?.email)
  const initials = getInitials(user?.name, user?.email)

  const { data: unreadData } = useQuery<{ unread_count: number }>({
    queryKey: ['notifications-unread'],
    queryFn: () => axios.get('/api/v1/notifications/unread-count').then(r => r.data),
    refetchInterval: 30_000,
  })

  const { data: notifications } = useQuery<Notification[]>({
    queryKey: ['notifications'],
    queryFn: () => axios.get('/api/v1/notifications?limit=20').then(r => r.data),
    enabled: bellOpen,
  })

  useEffect(() => {
    if (bellOpen && notifications?.some(n => !n.read)) {
      axios.patch('/api/v1/notifications/mark-read').then(() => {
        qc.invalidateQueries({ queryKey: ['notifications-unread'] })
        qc.invalidateQueries({ queryKey: ['notifications'] })
      }).catch(() => {})
    }
  }, [bellOpen, notifications, qc])

  const unreadCount = unreadData?.unread_count ?? 0

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          'hidden md:flex flex-col border-r border-border bg-card transition-all duration-300',
          collapsed ? 'w-[68px]' : 'w-64',
        )}
      >
        <SidebarContent
          collapsed={collapsed}
          onCollapse={() => setCollapsed((c) => !c)}
          onLogout={logout}
          navItems={navItems}
          displayName={displayName}
          initials={initials}
          role={isAdmin ? 'Admin' : 'User'}
        />
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-14 items-center gap-4 border-b border-border bg-card/50 backdrop-blur-sm px-4 md:px-6">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden">
                <Menu className="h-5 w-5" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <SidebarContent collapsed={false} onLogout={logout} navItems={navItems} displayName={displayName} initials={initials} role={isAdmin ? 'Admin' : 'User'} />
            </SheetContent>
          </Sheet>

          <h1 className="text-lg font-semibold">{pageTitle}</h1>

          <div className="ml-auto">
            <Popover open={bellOpen} onOpenChange={setBellOpen}>
              <PopoverTrigger asChild>
                <Button variant="ghost" size="icon" className="relative h-9 w-9">
                  <Bell className="h-5 w-5" />
                  {unreadCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                      {unreadCount > 99 ? '99+' : unreadCount}
                    </span>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-80 p-0">
                <div className="border-b px-4 py-3">
                  <p className="text-sm font-semibold">Notifications</p>
                </div>
                <ScrollArea className="max-h-80">
                  {notifications && notifications.length > 0 ? (
                    <div className="divide-y">
                      {notifications.map(n => (
                        <div key={n.id} className={cn('px-4 py-3 text-sm', !n.read && 'bg-primary/5')}>
                          <p className="font-medium text-xs">{n.title}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{n.body}</p>
                          {n.created_at && (
                            <p className="text-[10px] text-muted-foreground mt-1">
                              {new Date(n.created_at).toLocaleString()}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                      <Bell className="h-6 w-6 opacity-30 mb-2" />
                      <p className="text-xs">No notifications yet</p>
                    </div>
                  )}
                </ScrollArea>
              </PopoverContent>
            </Popover>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <div className="p-4 md:p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
