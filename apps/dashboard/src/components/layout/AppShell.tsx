import { useState, useEffect, useCallback, useMemo } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import api from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import { useTheme } from '@/context/ThemeContext'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard, TrendingUp, BarChart3, Bot, Target, Plug, BookOpen,
  LineChart, Settings, Shield, Network, ListTodo, Moon, Sun, LogOut, Zap,
  Activity, Fish, MessageCircle, ShieldCheck, Bell, PanelLeftClose, PanelLeft,
  Bug, GripVertical, RotateCcw, Menu,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from '@/components/ui/sheet'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import ChatWidget from '@/components/ChatWidget'
import { TokenMonitor } from '@/components/TokenMonitor'

const SIDEBAR_COLLAPSED_KEY = 'phoenix-sidebar-collapsed'
const SIDEBAR_ORDER_KEY = 'phoenix-sidebar-order'

type NavItem = { to: string; icon: typeof LayoutDashboard; label: string; adminOnly?: boolean }
type NavSection = { label: string; items: NavItem[] }

const DEFAULT_NAV_SECTIONS: NavSection[] = [
  {
    label: 'Agents',
    items: [
      { to: '/agents', icon: Bot, label: 'Agents' },
      { to: '/strategies', icon: Target, label: 'Strategies' },
      { to: '/skills', icon: BookOpen, label: 'Skills' },
      { to: '/network', icon: Network, label: 'Network' },
      { to: '/performance', icon: BarChart3, label: 'Performance' },
    ],
  },
  {
    label: 'Trading',
    items: [
      { to: '/trades', icon: LayoutDashboard, label: 'Trades' },
      { to: '/daily-signals', icon: Zap, label: 'Daily Signals' },
      { to: '/zero-dte', icon: Activity, label: '0DTE SPX' },
      { to: '/positions', icon: TrendingUp, label: 'Positions' },
    ],
  },
  {
    label: 'Analytics',
    items: [
      { to: '/onchain-flow', icon: Fish, label: 'On-Chain' },
      { to: '/macro-pulse', icon: Activity, label: 'Macro-Pulse' },
      { to: '/narrative', icon: MessageCircle, label: 'Narrative' },
      { to: '/risk', icon: ShieldCheck, label: 'Risk' },
      { to: '/market', icon: LineChart, label: 'Market' },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/connectors', icon: Plug, label: 'Connectors' },
      { to: '/tasks', icon: ListTodo, label: 'Tasks' },
      { to: '/admin', icon: Shield, label: 'Admin' },
      { to: '/dev-sprint', icon: Bug, label: 'Dev Sprint Board', adminOnly: true },
      { to: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
]

const DEFAULT_ORDER = DEFAULT_NAV_SECTIONS.map((s) => s.label)

function loadSectionOrder(): string[] {
  try {
    const raw = localStorage.getItem(SIDEBAR_ORDER_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as string[]
      if (Array.isArray(parsed) && parsed.length === DEFAULT_ORDER.length) {
        const valid = DEFAULT_ORDER.every((l) => parsed.includes(l))
        if (valid) return parsed
      }
    }
  } catch { /* noop */ }
  return DEFAULT_ORDER
}

function saveSectionOrder(order: string[]) {
  try { localStorage.setItem(SIDEBAR_ORDER_KEY, JSON.stringify(order)) } catch { /* noop */ }
}

interface SortableSectionProps {
  section: NavSection
  collapsed: boolean
  userRole?: string
  onNavigate?: () => void
}

function SortableSection({ section, collapsed, userRole, onNavigate }: SortableSectionProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: section.label })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }

  return (
    <div ref={setNodeRef} style={style} className="mb-3">
      {!collapsed && (
        <div className="group flex items-center mb-1 px-3">
          <p className="flex-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">{section.label}</p>
          <button
            type="button"
            className="opacity-0 group-hover:opacity-60 hover:!opacity-100 cursor-grab active:cursor-grabbing p-0.5 rounded text-muted-foreground"
            aria-label={`Drag to reorder ${section.label}`}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-3 w-3" />
          </button>
        </div>
      )}
      <div className="space-y-0.5">
        {section.items
          .filter((item) => !item.adminOnly || userRole === 'admin')
          .map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex items-center rounded-md text-sm font-medium transition-colors',
                  collapsed ? 'justify-center h-9 w-9 mx-auto' : 'gap-3 px-3 py-2',
                  isActive
                    ? 'bg-primary/10 text-primary font-semibold'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
      </div>
    </div>
  )
}

function SidebarNav({ collapsed, userRole, orderedSections, sectionOrder, sensors, handleDragEnd, resetOrder, onNavigate }: {
  collapsed: boolean
  userRole?: string
  orderedSections: NavSection[]
  sectionOrder: string[]
  sensors: ReturnType<typeof useSensors>
  handleDragEnd: (event: DragEndEvent) => void
  resetOrder: () => void
  onNavigate?: () => void
}) {
  /* eslint-disable @typescript-eslint/no-explicit-any */
  const Dnd = DndContext as any
  const SortCtx = SortableContext as any

  return (
    <>
      <Dnd sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortCtx items={sectionOrder} strategy={verticalListSortingStrategy}>
          {orderedSections.map((section) => (
            <SortableSection key={section.label} section={section} collapsed={collapsed} userRole={userRole} onNavigate={onNavigate} />
          ))}
        </SortCtx>
      </Dnd>
      {!collapsed && (
        <button
          type="button"
          onClick={resetOrder}
          className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent mt-1"
          title="Reset sidebar order to default"
        >
          <RotateCcw className="h-3 w-3" />
          Reset order
        </button>
      )}
    </>
  )
}

export default function AppShell() {
  const { user, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const qc = useQueryClient()
  const location = useLocation()

  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true' } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const [sectionOrder, setSectionOrder] = useState<string[]>(loadSectionOrder)

  useEffect(() => {
    try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed)) } catch { /* noop */ }
  }, [collapsed])

  useEffect(() => { setMobileOpen(false) }, [location.pathname])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )

  const orderedSections = useMemo(() => {
    const map = new Map(DEFAULT_NAV_SECTIONS.map((s) => [s.label, s]))
    return sectionOrder.map((label) => map.get(label)).filter(Boolean) as NavSection[]
  }, [sectionOrder])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (over && active.id !== over.id) {
      setSectionOrder((prev) => {
        const oldIndex = prev.indexOf(active.id as string)
        const newIndex = prev.indexOf(over.id as string)
        const next = arrayMove(prev, oldIndex, newIndex)
        saveSectionOrder(next)
        return next
      })
    }
  }, [])

  const resetOrder = useCallback(() => { setSectionOrder(DEFAULT_ORDER); saveSectionOrder(DEFAULT_ORDER) }, [])

  const { data: unreadCount = { count: 0 } } = useQuery({
    queryKey: ['notifications-unread'],
    queryFn: async () => (await api.get('/api/v2/notifications/unread-count')).data,
  })
  const { data: notifications = [], refetch: refetchNotifications } = useQuery({
    queryKey: ['notifications'],
    queryFn: async () => (await api.get('/api/v2/notifications')).data,
    enabled: false,
  })
  const markReadMutation = useMutation({
    mutationFn: () => api.patch('/api/v2/notifications/mark-read'),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['notifications-unread'] }); refetchNotifications() },
  })

  const sidebarWidth = collapsed ? 'w-16' : 'w-60'
  const mainMl = collapsed ? 'md:ml-16' : 'md:ml-60'

  const sidebarFooter = (mobile = false) => (
    <div className="space-y-0.5 p-2">
      {!mobile && (
        <Button
          variant="ghost"
          size={collapsed ? 'icon' : 'sm'}
          className={cn('w-full', !collapsed && 'justify-start gap-2')}
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          {collapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          {!collapsed && 'Collapse'}
        </Button>
      )}
      <Button
        variant="ghost"
        size={collapsed && !mobile ? 'icon' : 'sm'}
        className={cn('w-full', (!collapsed || mobile) && 'justify-start gap-2')}
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        {(!collapsed || mobile) && (theme === 'dark' ? 'Light mode' : 'Dark mode')}
      </Button>
      <Button
        variant="ghost"
        size={collapsed && !mobile ? 'icon' : 'sm'}
        className={cn('w-full text-destructive', (!collapsed || mobile) && 'justify-start gap-2')}
        onClick={logout}
      >
        <LogOut className="h-4 w-4" />
        {(!collapsed || mobile) && 'Logout'}
      </Button>
      {user && (!collapsed || mobile) && (
        <p className="truncate px-2 py-1 text-[11px] text-muted-foreground">{user.email}</p>
      )}
    </div>
  )

  return (
    <div className="flex h-screen w-screen bg-background text-foreground">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          'hidden md:flex flex-col fixed inset-y-0 left-0 z-30 border-r bg-card transition-[width] duration-200 ease-in-out',
          sidebarWidth,
        )}
      >
        <div className={cn('flex h-14 shrink-0 items-center border-b px-3', collapsed ? 'justify-center' : 'gap-2 px-4')}>
          <img src="/phoenix-logo.png" alt="" className="h-7 w-7 shrink-0" />
          {!collapsed && <span className="font-semibold truncate">Phoenix Claw</span>}
          {!collapsed && (
            <Popover onOpenChange={(open: boolean) => { if (open) { refetchNotifications(); markReadMutation.mutate() } }}>
              <PopoverTrigger asChild>
                <Button variant="ghost" size="icon" className="ml-auto relative h-8 w-8">
                  <Bell className="h-4 w-4" />
                  {unreadCount?.count > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 h-4 min-w-4 rounded-full bg-primary text-[10px] font-medium text-primary-foreground flex items-center justify-center px-1">
                      {unreadCount.count > 9 ? '9+' : unreadCount.count}
                    </span>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-80 max-h-80 overflow-y-auto">
                <p className="font-medium text-sm mb-2">Notifications</p>
                {Array.isArray(notifications) && notifications.length === 0 && (
                  <p className="text-xs text-muted-foreground py-4 text-center">No notifications</p>
                )}
                {Array.isArray(notifications) && notifications.length > 0 && (
                  <ul className="space-y-2 text-sm">
                    {notifications.slice(0, 10).map((n: { id?: number; title?: string; body?: string }) => (
                      <li key={n.id ?? n.title} className="border-b pb-2 last:border-0">
                        <p className="font-medium">{n.title ?? 'Notification'}</p>
                        {n.body && <p className="text-xs text-muted-foreground">{n.body}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </PopoverContent>
            </Popover>
          )}
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2">
            <SidebarNav
              collapsed={collapsed}
              userRole={user?.role}
              orderedSections={orderedSections}
              sectionOrder={sectionOrder}
              sensors={sensors}
              handleDragEnd={handleDragEnd}
              resetOrder={resetOrder}
            />
          </div>
        </ScrollArea>
        {!collapsed && (
          <div className="px-2 pb-2">
            <TokenMonitor />
          </div>
        )}
        <Separator />
        {sidebarFooter(false)}
      </aside>

      {/* Mobile header + sheet sidebar */}
      <header className="md:hidden fixed top-0 left-0 right-0 z-30 flex h-14 items-center gap-2 border-b bg-card px-4">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="h-9 w-9">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0 flex flex-col">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <div className="flex h-14 items-center gap-2 border-b px-4">
              <img src="/phoenix-logo.png" alt="" className="h-7 w-7" />
              <span className="font-semibold">Phoenix Claw</span>
            </div>
            <ScrollArea className="flex-1">
              <div className="p-2">
                <SidebarNav
                  collapsed={false}
                  userRole={user?.role}
                  orderedSections={orderedSections}
                  sectionOrder={sectionOrder}
                  sensors={sensors}
                  handleDragEnd={handleDragEnd}
                  resetOrder={resetOrder}
                  onNavigate={() => setMobileOpen(false)}
                />
              </div>
            </ScrollArea>
            <Separator />
            {sidebarFooter(true)}
          </SheetContent>
        </Sheet>
        <img src="/phoenix-logo.png" alt="" className="h-7 w-7" />
        <span className="font-semibold flex-1 truncate">Phoenix Claw</span>
        <Popover onOpenChange={(open: boolean) => { if (open) { refetchNotifications(); markReadMutation.mutate() } }}>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon" className="relative h-9 w-9">
              <Bell className="h-4 w-4" />
              {unreadCount?.count > 0 && (
                <span className="absolute -top-0.5 -right-0.5 h-4 min-w-4 rounded-full bg-primary text-[10px] font-medium text-primary-foreground flex items-center justify-center px-1">
                  {unreadCount.count > 9 ? '9+' : unreadCount.count}
                </span>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-80 max-h-80 overflow-y-auto">
            <p className="font-medium text-sm mb-2">Notifications</p>
            {Array.isArray(notifications) && notifications.length === 0 && (
              <p className="text-xs text-muted-foreground py-4 text-center">No notifications</p>
            )}
          </PopoverContent>
        </Popover>
      </header>

      {/* Main content */}
      <main className={cn('flex flex-1 flex-col min-h-screen pt-14 md:pt-0', mainMl)}>
        <div className="flex-1 overflow-y-auto p-4 sm:p-6">
          <Outlet />
        </div>
      </main>

      <ChatWidget />
    </div>
  )
}
