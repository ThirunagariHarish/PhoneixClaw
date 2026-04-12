/**
 * Notifications page — full notification center with filtering, pagination, and bulk actions.
 */
import { useState, useEffect, useCallback } from 'react'
import { useNotifications, type Notification, type NotificationCategory } from '@/context/NotificationContext'
import { PageHeader } from '@/components/ui/PageHeader'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import {
  Bell, CheckCircle, AlertTriangle, Bot, Activity, FlaskConical,
  Monitor, ChevronLeft, ChevronRight, CheckCheck,
} from 'lucide-react'

// ---- Type config ----

type FilterCategory = 'all' | NotificationCategory

interface CategoryConfig {
  label: string
  icon: typeof Bell
  color: string
  bgColor: string
  borderColor: string
}

const CATEGORY_CONFIG: Record<string, CategoryConfig> = {
  trades: {
    label: 'Trades',
    icon: CheckCircle,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-l-emerald-500',
  },
  risk: {
    label: 'Risk',
    icon: AlertTriangle,
    color: 'text-orange-500',
    bgColor: 'bg-orange-500/10',
    borderColor: 'border-l-orange-500',
  },
  agents: {
    label: 'Agents',
    icon: Bot,
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-l-blue-500',
  },
  system: {
    label: 'System',
    icon: Monitor,
    color: 'text-yellow-500',
    bgColor: 'bg-yellow-500/10',
    borderColor: 'border-l-yellow-500',
  },
}

const EVENT_TYPE_CONFIG: Record<string, { color: string; bgColor: string; icon: typeof Bell }> = {
  TRADE_FILLED: { color: 'text-emerald-500', bgColor: 'bg-emerald-500/10', icon: CheckCircle },
  TRADE_REJECTED: { color: 'text-red-500', bgColor: 'bg-red-500/10', icon: AlertTriangle },
  RISK_BREACH: { color: 'text-orange-500', bgColor: 'bg-orange-500/10', icon: AlertTriangle },
  AGENT_ERROR: { color: 'text-red-500', bgColor: 'bg-red-500/10', icon: Bot },
  AGENT_STATUS: { color: 'text-blue-500', bgColor: 'bg-blue-500/10', icon: Bot },
  BACKTEST_COMPLETE: { color: 'text-emerald-500', bgColor: 'bg-emerald-500/10', icon: FlaskConical },
  SYSTEM: { color: 'text-yellow-500', bgColor: 'bg-yellow-500/10', icon: Monitor },
}

function getEventConfig(eventType: string) {
  return EVENT_TYPE_CONFIG[eventType] ?? { color: 'text-muted-foreground', bgColor: 'bg-muted', icon: Bell }
}

// ---- Time formatting ----

function timeAgo(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = Math.max(0, now - then)
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString()
}

// ---- Filter pills ----

const FILTER_CATEGORIES: { value: FilterCategory; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'trades', label: 'Trades' },
  { value: 'risk', label: 'Risk' },
  { value: 'agents', label: 'Agents' },
  { value: 'system', label: 'System' },
]

// ---- Components ----

function NotificationCard({
  notification,
  onMarkRead,
}: {
  notification: Notification
  onMarkRead: (id: string) => void
}) {
  const cfg = getEventConfig(notification.event_type)
  const catCfg = CATEGORY_CONFIG[notification.category]
  const Icon = cfg.icon
  const borderColor = catCfg?.borderColor ?? 'border-l-muted-foreground'

  return (
    <div
      className={cn(
        'group relative flex items-start gap-3 rounded-lg border bg-card p-4 transition-all duration-200 border-l-4 cursor-pointer',
        borderColor,
        notification.read
          ? 'opacity-60 hover:opacity-80'
          : 'hover:shadow-md hover:shadow-black/5 dark:hover:shadow-black/20',
      )}
      onClick={() => {
        if (!notification.read) onMarkRead(notification.id)
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !notification.read) onMarkRead(notification.id)
      }}
    >
      {/* Icon */}
      <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg', cfg.bgColor)}>
        <Icon className={cn('h-4 w-4', cfg.color)} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className={cn('text-sm font-medium leading-tight', notification.read && 'font-normal')}>
              {notification.title}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{notification.body}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[11px] text-muted-foreground whitespace-nowrap">
              {timeAgo(notification.created_at)}
            </span>
            {!notification.read && (
              <span className="h-2 w-2 rounded-full bg-primary animate-pulse" title="Unread" />
            )}
          </div>
        </div>

        {/* Metadata row */}
        <div className="flex items-center gap-2 mt-2">
          {notification.category && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              {CATEGORY_CONFIG[notification.category]?.label ?? notification.category}
            </Badge>
          )}
          {notification.event_type && notification.event_type !== 'info' && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              {notification.event_type.replace(/_/g, ' ')}
            </Badge>
          )}
          {notification.agent_id && (
            <span className="text-[10px] text-muted-foreground">
              Agent: {notification.agent_id.slice(0, 8)}...
            </span>
          )}
          {typeof notification.data?.ticker === 'string' && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0 font-mono">
              {notification.data.ticker}
            </Badge>
          )}
        </div>
      </div>
    </div>
  )
}

// ---- Page ----

const PAGE_SIZE = 20

export default function NotificationsPage() {
  const {
    notifications,
    total,
    isLoading,
    unreadCount,
    markAsRead,
    markAllRead,
    fetchPage,
  } = useNotifications()

  const [activeCategory, setActiveCategory] = useState<FilterCategory>('all')
  const [readFilter, setReadFilter] = useState<'all' | 'unread' | 'read'>('all')
  const [page, setPage] = useState(0)

  const buildParams = useCallback(
    (pageNum: number) => ({
      offset: pageNum * PAGE_SIZE,
      limit: PAGE_SIZE,
      category: activeCategory === 'all' ? null : activeCategory,
      read: readFilter === 'all' ? null : readFilter === 'read',
    }),
    [activeCategory, readFilter],
  )

  // Fetch on mount and when filters/page change
  useEffect(() => {
    fetchPage(buildParams(page))
  }, [fetchPage, buildParams, page])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  function handleCategoryChange(cat: FilterCategory) {
    setActiveCategory(cat)
    setPage(0)
  }

  function handleReadFilterChange(filter: 'all' | 'unread' | 'read') {
    setReadFilter(filter)
    setPage(0)
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          icon={Bell}
          title="Notifications"
          description={`${unreadCount} unread notification${unreadCount !== 1 ? 's' : ''}`}
        />
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={markAllRead}
            disabled={unreadCount === 0}
          >
            <CheckCheck className="h-4 w-4 mr-1.5" />
            Mark all read
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Category pills */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {FILTER_CATEGORIES.map((cat) => (
            <button
              key={cat.value}
              onClick={() => handleCategoryChange(cat.value)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
                activeCategory === cat.value
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'bg-muted text-muted-foreground hover:bg-accent hover:text-accent-foreground',
              )}
            >
              {cat.value !== 'all' && (() => {
                const CatIcon = CATEGORY_CONFIG[cat.value]?.icon ?? Bell
                return <CatIcon className="h-3 w-3" />
              })() as React.ReactNode}
              {cat.label}
            </button>
          ))}
        </div>

        {/* Read/Unread toggle */}
        <div className="flex items-center gap-1 rounded-lg border p-0.5">
          {(['all', 'unread', 'read'] as const).map((f) => (
            <button
              key={f}
              onClick={() => handleReadFilterChange(f)}
              className={cn(
                'rounded-md px-3 py-1 text-xs font-medium transition-colors capitalize',
                readFilter === f
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Notification list */}
      <div className="space-y-2">
        {isLoading && notifications.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <Activity className="h-8 w-8 text-muted-foreground/30 animate-spin mb-3" />
            <p className="text-sm text-muted-foreground">Loading notifications...</p>
          </div>
        )}

        {!isLoading && notifications.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 border-2 border-dashed border-border/50 rounded-lg">
            <Bell className="h-10 w-10 text-muted-foreground/20 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">No notifications</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              {activeCategory !== 'all' || readFilter !== 'all'
                ? 'Try adjusting your filters'
                : 'You are all caught up'}
            </p>
          </div>
        )}

        {notifications.map((n) => (
          <NotificationCard
            key={n.id}
            notification={n}
            onMarkRead={markAsRead}
          />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t pt-4">
          <p className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </p>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
              // Show pages around current page
              let pageNum = i
              if (totalPages > 5) {
                const start = Math.max(0, Math.min(page - 2, totalPages - 5))
                pageNum = start + i
              }
              return (
                <Button
                  key={pageNum}
                  variant={pageNum === page ? 'default' : 'outline'}
                  size="icon"
                  className="h-8 w-8 text-xs"
                  onClick={() => setPage(pageNum)}
                >
                  {pageNum + 1}
                </Button>
              )
            })}
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
