import { useState } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useTheme } from './ThemeProvider'
import { Button } from './ui/button'
import { Avatar, AvatarFallback } from './ui/avatar'
import { Separator } from './ui/separator'
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from './ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip'
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
} from 'lucide-react'
import { cn } from '@/lib/utils'

const baseNavItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/positions', icon: TrendingUp, label: 'Positions' },
  { to: '/sources', icon: Database, label: 'Data Sources' },
  { to: '/accounts', icon: Wallet, label: 'Trading Accounts' },
  { to: '/messages', icon: MessageSquare, label: 'Raw Messages' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/system', icon: Settings, label: 'System' },
]

const adminNavItems = [
  { to: '/access', icon: UserCog, label: 'Access Management' },
  { to: '/admin', icon: ShieldCheck, label: 'Admin Panel' },
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
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <TrendingUp className="h-5 w-5" />
        </div>
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
  '/sources': 'Data Sources',
  '/accounts': 'Trading Accounts',
  '/messages': 'Raw Messages',
  '/analytics': 'Analytics',
  '/system': 'System',
  '/access': 'Access Management',
  '/admin': 'Admin Panel',
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
  const { logout, isAdmin, user } = useAuth()
  const location = useLocation()
  const pageTitle = pageTitles[location.pathname] || 'PhoenixTrade'
  const navItems = isAdmin ? [...baseNavItems, ...adminNavItems] : baseNavItems
  const displayName = getDisplayName(user?.name, user?.email)
  const initials = getInitials(user?.name, user?.email)

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
