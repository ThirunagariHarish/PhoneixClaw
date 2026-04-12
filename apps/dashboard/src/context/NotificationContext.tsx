/**
 * NotificationContext — centralized notification state, polling, and actions.
 * Provides useNotifications() hook for bell popover and /notifications page.
 */
import { createContext, useContext, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

// ---- Types ----

export type NotificationType =
  | 'TRADE_FILLED'
  | 'TRADE_REJECTED'
  | 'RISK_BREACH'
  | 'AGENT_ERROR'
  | 'AGENT_STATUS'
  | 'BACKTEST_COMPLETE'
  | 'SYSTEM'

export type NotificationCategory = 'trades' | 'risk' | 'agents' | 'system'

export interface Notification {
  id: string
  user_id: string | null
  title: string
  body: string
  category: NotificationCategory
  severity: string
  source: string | null
  event_type: NotificationType | string
  agent_id: string | null
  read: boolean
  data: Record<string, unknown>
  created_at: string
  read_at: string | null
}

interface NotificationsResponse {
  items: Notification[]
  total: number
  offset: number
  limit: number
}

interface NotificationContextValue {
  /** Recent notifications for bell popover (last 10, all types) */
  recentNotifications: Notification[]
  /** Unread count for the badge */
  unreadCount: number
  /** Full page notifications (paginated, filterable) */
  notifications: Notification[]
  /** Total count for pagination */
  total: number
  /** Loading state */
  isLoading: boolean
  /** Mark a single notification as read */
  markAsRead: (id: string) => void
  /** Mark all notifications as read */
  markAllRead: () => void
  /** Fetch paginated/filtered notifications for the full page */
  fetchPage: (params: FetchPageParams) => void
  /** Refetch unread count and recent */
  refresh: () => void
}

interface FetchPageParams {
  offset?: number
  limit?: number
  category?: string | null
  read?: boolean | null
  type?: string | null
}

const NotificationContext = createContext<NotificationContextValue | null>(null)

// ---- Provider ----

export function NotificationProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const pageParamsRef = useRef<FetchPageParams>({ offset: 0, limit: 20 })

  // Unread count — polls every 30s
  const { data: unreadData } = useQuery({
    queryKey: ['notifications-unread'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/notifications/unread-count')
        return res.data as { count: number }
      } catch {
        return { count: 0 }
      }
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  })

  // Recent notifications for bell popover (last 10)
  const { data: recentData } = useQuery({
    queryKey: ['notifications-recent'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/notifications', { params: { limit: 10, offset: 0 } })
        return res.data as NotificationsResponse
      } catch {
        return { items: [], total: 0, offset: 0, limit: 10 }
      }
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  })

  // Full page query — only fetched when params change (on demand)
  const { data: pageData, isLoading } = useQuery({
    queryKey: ['notifications-page', pageParamsRef.current],
    queryFn: async () => {
      const p = pageParamsRef.current
      const params: Record<string, string | number | boolean> = {
        limit: p.limit ?? 20,
        offset: p.offset ?? 0,
      }
      if (p.category) params.category = p.category
      if (p.read !== null && p.read !== undefined) params.read = p.read
      if (p.type) params.type = p.type
      try {
        const res = await api.get('/api/v2/notifications', { params })
        return res.data as NotificationsResponse
      } catch {
        return { items: [], total: 0, offset: 0, limit: 20 }
      }
    },
    staleTime: 5_000,
  })

  // Mark single as read
  const markOneMut = useMutation({
    mutationFn: async (id: string) => {
      await api.put(`/api/v2/notifications/${id}/read`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications-unread'] })
      qc.invalidateQueries({ queryKey: ['notifications-recent'] })
      qc.invalidateQueries({ queryKey: ['notifications-page'] })
    },
  })

  // Mark all as read
  const markAllMut = useMutation({
    mutationFn: async () => {
      await api.put('/api/v2/notifications/read-all')
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications-unread'] })
      qc.invalidateQueries({ queryKey: ['notifications-recent'] })
      qc.invalidateQueries({ queryKey: ['notifications-page'] })
    },
  })

  const fetchPage = useCallback(
    (params: FetchPageParams) => {
      pageParamsRef.current = params
      qc.invalidateQueries({ queryKey: ['notifications-page'] })
    },
    [qc],
  )

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['notifications-unread'] })
    qc.invalidateQueries({ queryKey: ['notifications-recent'] })
  }, [qc])

  // Detect new notifications via unread count change and trigger a subtle animation hint
  const prevCountRef = useRef(0)
  useEffect(() => {
    const current = unreadData?.count ?? 0
    if (current > prevCountRef.current && prevCountRef.current >= 0) {
      // New notifications arrived — badge pulse is handled via CSS
    }
    prevCountRef.current = current
  }, [unreadData?.count])

  const value: NotificationContextValue = {
    recentNotifications: recentData?.items ?? [],
    unreadCount: unreadData?.count ?? 0,
    notifications: pageData?.items ?? [],
    total: pageData?.total ?? 0,
    isLoading,
    markAsRead: (id: string) => markOneMut.mutate(id),
    markAllRead: () => markAllMut.mutate(),
    fetchPage,
    refresh,
  }

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  )
}

// ---- Hook ----

export function useNotifications(): NotificationContextValue {
  const ctx = useContext(NotificationContext)
  if (!ctx) {
    throw new Error('useNotifications must be used within a NotificationProvider')
  }
  return ctx
}
