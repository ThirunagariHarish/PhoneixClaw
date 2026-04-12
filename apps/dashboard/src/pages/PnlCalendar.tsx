/**
 * P&L Calendar Heatmap — daily P&L as a calendar with color-coded cells.
 * Green for profit, red for loss, intensity proportional to magnitude.
 *
 * TODO: Replace mock data with real API call once GET /api/v2/performance/daily
 *       or similar endpoint is available. Currently uses GET /api/v2/trades
 *       with client-side aggregation, falling back to generated sample data.
 */
import { useState, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as ReTooltip,
  ResponsiveContainer,
  Cell,
  CartesianGrid,
} from 'recharts'
import { CalendarDays, ChevronLeft, ChevronRight, TrendingUp, TrendingDown, Trophy, Target } from 'lucide-react'
import api from '@/lib/api'
import { useTheme } from '@/context/ThemeContext'
import { cn } from '@/lib/utils'
import { PageHeader } from '@/components/ui/PageHeader'
import { MetricCard } from '@/components/ui/MetricCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

/* -------------------------------------------------------------------------- */
/*  Types                                                                     */
/* -------------------------------------------------------------------------- */

interface DayPnl {
  date: string          // YYYY-MM-DD
  pnl: number
  tradeCount: number
  trades: TradeSummary[]
}

interface TradeSummary {
  symbol: string
  side: string
  pnl: number
  qty: number
}

/* -------------------------------------------------------------------------- */
/*  Mock data generator (used when API returns no data)                       */
/* -------------------------------------------------------------------------- */

function generateMockData(year: number, month: number): DayPnl[] {
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const result: DayPnl[] = []
  const symbols = ['AAPL', 'TSLA', 'NVDA', 'SPY', 'AMZN', 'MSFT', 'META', 'GOOG']

  for (let d = 1; d <= daysInMonth; d++) {
    const date = new Date(year, month, d)
    const dow = date.getDay()
    // Skip weekends
    if (dow === 0 || dow === 6) continue
    // ~20% chance of no trades
    if (Math.random() < 0.2) continue

    const tradeCount = Math.floor(Math.random() * 5) + 1
    const trades: TradeSummary[] = []
    let dayPnl = 0
    for (let t = 0; t < tradeCount; t++) {
      const pnl = (Math.random() - 0.42) * 800 // slightly positive bias
      dayPnl += pnl
      trades.push({
        symbol: symbols[Math.floor(Math.random() * symbols.length)],
        side: Math.random() > 0.5 ? 'BUY' : 'SELL',
        pnl: Math.round(pnl * 100) / 100,
        qty: Math.floor(Math.random() * 50) + 1,
      })
    }
    const dd = String(d).padStart(2, '0')
    const mm = String(month + 1).padStart(2, '0')
    result.push({
      date: `${year}-${mm}-${dd}`,
      pnl: Math.round(dayPnl * 100) / 100,
      tradeCount,
      trades,
    })
  }
  return result
}

/* -------------------------------------------------------------------------- */
/*  Calendar grid helpers                                                     */
/* -------------------------------------------------------------------------- */

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

interface CalendarCell {
  day: number | null   // null = empty cell (padding)
  dateStr: string
  isWeekend: boolean
}

function buildCalendarGrid(year: number, month: number): CalendarCell[][] {
  const firstDow = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const weeks: CalendarCell[][] = []
  let currentWeek: CalendarCell[] = []

  // Leading empty cells
  for (let i = 0; i < firstDow; i++) {
    currentWeek.push({ day: null, dateStr: '', isWeekend: i === 0 || i === 6 })
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dow = (firstDow + d - 1) % 7
    const mm = String(month + 1).padStart(2, '0')
    const dd = String(d).padStart(2, '0')
    currentWeek.push({
      day: d,
      dateStr: `${year}-${mm}-${dd}`,
      isWeekend: dow === 0 || dow === 6,
    })
    if (currentWeek.length === 7) {
      weeks.push(currentWeek)
      currentWeek = []
    }
  }
  // Trailing empty cells
  if (currentWeek.length > 0) {
    while (currentWeek.length < 7) {
      const idx = currentWeek.length
      currentWeek.push({ day: null, dateStr: '', isWeekend: idx === 0 || idx === 6 })
    }
    weeks.push(currentWeek)
  }
  return weeks
}

/* -------------------------------------------------------------------------- */
/*  Color helpers                                                             */
/* -------------------------------------------------------------------------- */

function getPnlCellClasses(pnl: number, maxAbsPnl: number, isDark: boolean): string {
  if (maxAbsPnl === 0) {
    return isDark ? 'bg-zinc-800/50 border-zinc-700' : 'bg-zinc-50 border-zinc-200'
  }
  const intensity = Math.min(Math.abs(pnl) / maxAbsPnl, 1)

  if (isDark) {
    // Dark mode: colored borders + subtle colored tint
    if (pnl > 0) {
      if (intensity > 0.8) return 'bg-emerald-950/80 border-emerald-500 text-emerald-300'
      if (intensity > 0.6) return 'bg-emerald-950/60 border-emerald-500/80 text-emerald-300'
      if (intensity > 0.4) return 'bg-emerald-950/40 border-emerald-600/60 text-emerald-400'
      if (intensity > 0.2) return 'bg-emerald-950/25 border-emerald-700/40 text-emerald-400'
      return 'bg-emerald-950/15 border-emerald-800/30 text-emerald-500'
    }
    if (intensity > 0.8) return 'bg-red-950/80 border-red-500 text-red-300'
    if (intensity > 0.6) return 'bg-red-950/60 border-red-500/80 text-red-300'
    if (intensity > 0.4) return 'bg-red-950/40 border-red-600/60 text-red-400'
    if (intensity > 0.2) return 'bg-red-950/25 border-red-700/40 text-red-400'
    return 'bg-red-950/15 border-red-800/30 text-red-500'
  }

  // Light mode: colored backgrounds
  if (pnl > 0) {
    if (intensity > 0.8) return 'bg-emerald-600 border-emerald-700 text-white'
    if (intensity > 0.6) return 'bg-emerald-500 border-emerald-600 text-white'
    if (intensity > 0.4) return 'bg-emerald-400 border-emerald-500 text-emerald-950'
    if (intensity > 0.2) return 'bg-emerald-300 border-emerald-400 text-emerald-900'
    return 'bg-emerald-200 border-emerald-300 text-emerald-800'
  }
  if (intensity > 0.8) return 'bg-red-600 border-red-700 text-white'
  if (intensity > 0.6) return 'bg-red-500 border-red-600 text-white'
  if (intensity > 0.4) return 'bg-red-400 border-red-500 text-red-950'
  if (intensity > 0.2) return 'bg-red-300 border-red-400 text-red-900'
  return 'bg-red-200 border-red-300 text-red-800'
}

function getBarColor(pnl: number, isDark: boolean): string {
  if (pnl >= 0) return isDark ? '#34d399' : '#059669'
  return isDark ? '#f87171' : '#dc2626'
}

/* -------------------------------------------------------------------------- */
/*  Formatting                                                                */
/* -------------------------------------------------------------------------- */

function formatPnl(pnl: number, compact = false): string {
  const abs = Math.abs(pnl)
  const sign = pnl >= 0 ? '+' : '-'
  if (compact && abs >= 1000) {
    return `${sign}$${(abs / 1000).toFixed(1)}k`
  }
  return `${sign}$${abs.toFixed(2)}`
}

/* -------------------------------------------------------------------------- */
/*  Day Detail Popover                                                        */
/* -------------------------------------------------------------------------- */

function DayDetail({ day }: { day: DayPnl }) {
  return (
    <div className="space-y-2 min-w-[200px]">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{day.date}</span>
        <span className={cn(
          'text-sm font-semibold',
          day.pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400',
        )}>
          {formatPnl(day.pnl)}
        </span>
      </div>
      <div className="text-xs text-muted-foreground">{day.tradeCount} trade{day.tradeCount !== 1 ? 's' : ''}</div>
      {day.trades.length > 0 && (
        <div className="border-t pt-2 space-y-1">
          {day.trades.map((t, i) => (
            <div key={i} className="flex items-center justify-between text-xs">
              <span className="font-medium">{t.symbol} <span className="text-muted-foreground">{t.side}</span></span>
              <span className={t.pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>
                {formatPnl(t.pnl)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/*  Year View (GitHub contribution-graph style)                               */
/* -------------------------------------------------------------------------- */

function YearMiniMonth({
  year, month, pnlMap, maxAbsPnl, isDark,
}: {
  year: number
  month: number
  pnlMap: Map<string, DayPnl>
  maxAbsPnl: number
  isDark: boolean
}) {
  const grid = buildCalendarGrid(year, month)
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{MONTH_NAMES[month].slice(0, 3)}</p>
      <div className="grid grid-cols-7 gap-[2px]">
        {grid.flat().map((cell, i) => {
          if (!cell.day) return <div key={i} className="h-3 w-3" />
          const dayData = pnlMap.get(cell.dateStr)
          const pnl = dayData?.pnl ?? 0
          const hasData = !!dayData
          const classes = hasData
            ? getPnlCellClasses(pnl, maxAbsPnl, isDark)
            : cell.isWeekend
              ? (isDark ? 'bg-zinc-900 border-zinc-800' : 'bg-zinc-100 border-zinc-200')
              : (isDark ? 'bg-zinc-800/50 border-zinc-700' : 'bg-zinc-50 border-zinc-200')
          return (
            <div
              key={i}
              className={cn('h-3 w-3 rounded-[2px] border', classes)}
              title={hasData ? `${cell.dateStr}: ${formatPnl(pnl)}` : cell.dateStr}
            />
          )
        })}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/*  Main Component                                                            */
/* -------------------------------------------------------------------------- */

export default function PnlCalendarPage() {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const today = new Date()

  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const [selectedDay, setSelectedDay] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'month' | 'year'>('month')

  // Build date range for the query
  const startDate = `${year}-${String(month + 1).padStart(2, '0')}-01`
  const endDaysInMonth = new Date(year, month + 1, 0).getDate()
  const endDate = `${year}-${String(month + 1).padStart(2, '0')}-${String(endDaysInMonth).padStart(2, '0')}`

  // TODO: Replace with a dedicated daily P&L endpoint when available.
  // Currently attempts GET /api/v2/trades?start={}&end={} and aggregates client-side.
  const { data: rawDays } = useQuery({
    queryKey: ['pnl-calendar', year, month],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/trades?start=${startDate}&end=${endDate}&limit=1000`)
        const trades = res.data as Array<{
          symbol: string
          side: string
          qty: number
          fill_price: number | null
          limit_price: number | null
          status: string
          created_at: string
          pnl?: number
        }>
        if (!trades || trades.length === 0) return null

        // Aggregate by day
        const byDay = new Map<string, DayPnl>()
        for (const t of trades) {
          if (t.status !== 'filled' && t.status !== 'FILLED') continue
          const dateKey = t.created_at.slice(0, 10)
          if (!byDay.has(dateKey)) {
            byDay.set(dateKey, { date: dateKey, pnl: 0, tradeCount: 0, trades: [] })
          }
          const day = byDay.get(dateKey)!
          const tradePnl = t.pnl ?? 0
          day.pnl += tradePnl
          day.tradeCount += 1
          day.trades.push({
            symbol: t.symbol,
            side: t.side,
            pnl: tradePnl,
            qty: t.qty,
          })
        }
        return Array.from(byDay.values())
      } catch {
        return null
      }
    },
    staleTime: 60_000,
  })

  // Use mock data if API returned nothing
  const days = useMemo(() => {
    return rawDays ?? generateMockData(year, month)
  }, [rawDays, year, month])

  // Build lookup map
  const pnlMap = useMemo(() => {
    const m = new Map<string, DayPnl>()
    for (const d of days) m.set(d.date, d)
    return m
  }, [days])

  // Compute stats
  const stats = useMemo(() => {
    if (days.length === 0) {
      return { totalPnl: 0, bestDay: null as DayPnl | null, worstDay: null as DayPnl | null, winRate: 0, maxAbsPnl: 0, streak: { type: 'none' as 'win' | 'lose' | 'none', count: 0 } }
    }
    let totalPnl = 0
    let bestDay = days[0]
    let worstDay = days[0]
    let wins = 0

    for (const d of days) {
      totalPnl += d.pnl
      if (d.pnl > bestDay.pnl) bestDay = d
      if (d.pnl < worstDay.pnl) worstDay = d
      if (d.pnl >= 0) wins++
    }

    const maxAbsPnl = Math.max(Math.abs(bestDay.pnl), Math.abs(worstDay.pnl), 1)
    const winRate = days.length > 0 ? wins / days.length : 0

    // Compute current streak (from most recent day backward)
    const sorted = [...days].sort((a, b) => b.date.localeCompare(a.date))
    let streakType: 'win' | 'lose' | 'none' = 'none'
    let streakCount = 0
    if (sorted.length > 0) {
      streakType = sorted[0].pnl >= 0 ? 'win' : 'lose'
      for (const d of sorted) {
        const isWin = d.pnl >= 0
        if ((streakType === 'win' && isWin) || (streakType === 'lose' && !isWin)) {
          streakCount++
        } else {
          break
        }
      }
    }

    return { totalPnl, bestDay, worstDay, winRate, maxAbsPnl, streak: { type: streakType, count: streakCount } }
  }, [days])

  const calendarGrid = useMemo(() => buildCalendarGrid(year, month), [year, month])

  // Bar chart data for the month
  const barData = useMemo(() => {
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const result = []
    for (let d = 1; d <= daysInMonth; d++) {
      const dd = String(d).padStart(2, '0')
      const mm = String(month + 1).padStart(2, '0')
      const dateStr = `${year}-${mm}-${dd}`
      const dayData = pnlMap.get(dateStr)
      result.push({
        day: d,
        pnl: dayData?.pnl ?? 0,
        date: dateStr,
      })
    }
    return result
  }, [year, month, pnlMap])

  // Navigation
  const prevMonth = useCallback(() => {
    if (month === 0) { setYear(y => y - 1); setMonth(11) }
    else setMonth(m => m - 1)
    setSelectedDay(null)
  }, [month])

  const nextMonth = useCallback(() => {
    if (month === 11) { setYear(y => y + 1); setMonth(0) }
    else setMonth(m => m + 1)
    setSelectedDay(null)
  }, [month])

  const goToToday = useCallback(() => {
    setYear(today.getFullYear())
    setMonth(today.getMonth())
    setSelectedDay(null)
  }, [today])

  // Year view data
  const yearPnlMap = useMemo(() => {
    if (viewMode !== 'year') return new Map<string, DayPnl>()
    // Generate mock data for the entire year
    const allDays: DayPnl[] = []
    for (let m = 0; m < 12; m++) {
      allDays.push(...generateMockData(year, m))
    }
    const map = new Map<string, DayPnl>()
    for (const d of allDays) map.set(d.date, d)
    return map
  }, [viewMode, year])

  const yearMaxAbsPnl = useMemo(() => {
    if (viewMode !== 'year') return 1
    let max = 1
    for (const d of yearPnlMap.values()) {
      max = Math.max(max, Math.abs(d.pnl))
    }
    return max
  }, [viewMode, yearPnlMap])

  const selectedDayData = selectedDay ? pnlMap.get(selectedDay) : null

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          icon={CalendarDays}
          title="P&L Calendar"
          description="Daily profit and loss heatmap"
        />
        <div className="flex items-center gap-2">
          <Button
            variant={viewMode === 'month' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setViewMode('month')}
          >
            Month
          </Button>
          <Button
            variant={viewMode === 'year' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setViewMode('year')}
          >
            Year
          </Button>
        </div>
      </div>

      {/* Summary Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <MetricCard
          title="Total P&L"
          value={formatPnl(stats.totalPnl)}
          subtitle={`${MONTH_NAMES[month]} ${year}`}
          trend={stats.totalPnl >= 0 ? 'up' : 'down'}
          icon={stats.totalPnl >= 0 ? TrendingUp : TrendingDown}
          tooltip="Net profit/loss for the selected month"
        />
        <MetricCard
          title="Best Day"
          value={stats.bestDay ? formatPnl(stats.bestDay.pnl) : '--'}
          subtitle={stats.bestDay?.date ?? ''}
          trend="up"
          icon={Trophy}
          tooltip="Highest single-day profit this month"
        />
        <MetricCard
          title="Worst Day"
          value={stats.worstDay ? formatPnl(stats.worstDay.pnl) : '--'}
          subtitle={stats.worstDay?.date ?? ''}
          trend="down"
          icon={TrendingDown}
          tooltip="Largest single-day loss this month"
        />
        <MetricCard
          title="Win Rate"
          value={`${(stats.winRate * 100).toFixed(1)}%`}
          subtitle={`${days.filter(d => d.pnl >= 0).length}/${days.length} days`}
          icon={Target}
          tooltip="Percentage of profitable trading days"
        />
      </div>

      {/* Month View */}
      {viewMode === 'month' && (
        <>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
              <div className="flex items-center gap-2">
                <Button variant="outline" size="icon" className="h-8 w-8" onClick={prevMonth}>
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <CardTitle className="text-base sm:text-lg font-semibold min-w-[180px] text-center">
                  {MONTH_NAMES[month]} {year}
                </CardTitle>
                <Button variant="outline" size="icon" className="h-8 w-8" onClick={nextMonth}>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
              <Button variant="ghost" size="sm" onClick={goToToday}>
                Today
              </Button>
            </CardHeader>
            <CardContent>
              {/* Day-of-week headers */}
              <div className="grid grid-cols-7 gap-1 sm:gap-2 mb-1 sm:mb-2">
                {DAY_LABELS.map((label) => (
                  <div
                    key={label}
                    className="text-center text-[10px] sm:text-xs font-medium text-muted-foreground py-1"
                  >
                    {label}
                  </div>
                ))}
              </div>

              {/* Calendar grid */}
              <div className="grid grid-cols-7 gap-1 sm:gap-2">
                {calendarGrid.flat().map((cell, i) => {
                  if (!cell.day) {
                    return <div key={i} className="aspect-square" />
                  }

                  const dayData = pnlMap.get(cell.dateStr)
                  const hasTrades = !!dayData
                  const pnl = dayData?.pnl ?? 0
                  const isSelected = selectedDay === cell.dateStr

                  const cellClasses = hasTrades
                    ? getPnlCellClasses(pnl, stats.maxAbsPnl, isDark)
                    : cell.isWeekend
                      ? (isDark ? 'bg-zinc-900/50 border-zinc-800' : 'bg-zinc-100 border-zinc-200')
                      : (isDark ? 'bg-zinc-800/30 border-zinc-700/50' : 'bg-white border-zinc-200')

                  const isToday =
                    cell.dateStr ===
                    `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setSelectedDay(isSelected ? null : cell.dateStr)}
                      className={cn(
                        'relative aspect-square rounded-md border p-1 sm:p-1.5 flex flex-col items-center justify-center',
                        'transition-all duration-150 ease-in-out',
                        'hover:scale-105 hover:shadow-md hover:z-10',
                        cellClasses,
                        isSelected && 'ring-2 ring-primary ring-offset-1 ring-offset-background scale-105 shadow-lg z-10',
                        isToday && 'ring-1 ring-primary/50',
                        !hasTrades && 'cursor-default',
                      )}
                    >
                      <span className={cn(
                        'text-[10px] sm:text-xs font-medium leading-none',
                        isToday && 'underline underline-offset-2',
                        !hasTrades && 'text-muted-foreground',
                      )}>
                        {cell.day}
                      </span>
                      {hasTrades && (
                        <span className="text-[8px] sm:text-[10px] font-semibold leading-none mt-0.5 sm:mt-1 tabular-nums">
                          {formatPnl(pnl, true)}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* Selected Day Detail */}
          {selectedDayData && (
            <Card className="animate-in fade-in slide-in-from-top-2 duration-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Day Detail</CardTitle>
              </CardHeader>
              <CardContent>
                <DayDetail day={selectedDayData} />
              </CardContent>
            </Card>
          )}

          {/* Bottom Section: Bar Chart + Streak */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Daily P&L</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-48 sm:h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={barData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke={isDark ? '#333' : '#e5e7eb'}
                        vertical={false}
                      />
                      <XAxis
                        dataKey="day"
                        tick={{ fontSize: 10, fill: isDark ? '#9ca3af' : '#6b7280' }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: isDark ? '#9ca3af' : '#6b7280' }}
                        tickLine={false}
                        axisLine={false}
                        tickFormatter={(v: number) => `$${v}`}
                      />
                      <ReTooltip
                        contentStyle={{
                          backgroundColor: isDark ? '#1f2937' : '#fff',
                          border: `1px solid ${isDark ? '#374151' : '#e5e7eb'}`,
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                        formatter={(value: number) => [formatPnl(value), 'P&L']}
                        labelFormatter={(label: number) => `Day ${label}`}
                      />
                      <Bar dataKey="pnl" radius={[2, 2, 0, 0]} maxBarSize={20}>
                        {barData.map((entry, idx) => (
                          <Cell key={idx} fill={getBarColor(entry.pnl, isDark)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Streak</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col items-center justify-center h-48 sm:h-64">
                {stats.streak.count > 0 ? (
                  <>
                    <div className={cn(
                      'text-4xl sm:text-5xl font-bold tabular-nums',
                      stats.streak.type === 'win'
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-red-600 dark:text-red-400',
                    )}>
                      {stats.streak.count}
                    </div>
                    <p className="text-sm text-muted-foreground mt-2 text-center">
                      {stats.streak.type === 'win' ? 'Winning' : 'Losing'} day{stats.streak.count !== 1 ? 's' : ''} in a row
                    </p>
                    <div className="flex gap-1 mt-3">
                      {Array.from({ length: Math.min(stats.streak.count, 10) }).map((_, i) => (
                        <div
                          key={i}
                          className={cn(
                            'h-3 w-3 rounded-full',
                            stats.streak.type === 'win'
                              ? 'bg-emerald-500 dark:bg-emerald-400'
                              : 'bg-red-500 dark:bg-red-400',
                          )}
                        />
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">No trading data</p>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {/* Year View */}
      {viewMode === 'year' && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setYear(y => y - 1)}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <CardTitle className="text-base sm:text-lg font-semibold min-w-[80px] text-center">
                {year}
              </CardTitle>
              <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setYear(y => y + 1)}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4 sm:gap-6">
              {Array.from({ length: 12 }).map((_, m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => { setMonth(m); setViewMode('month') }}
                  className="text-left hover:bg-accent/50 rounded-lg p-2 transition-colors"
                >
                  <YearMiniMonth
                    year={year}
                    month={m}
                    pnlMap={yearPnlMap}
                    maxAbsPnl={yearMaxAbsPnl}
                    isDark={isDark}
                  />
                </button>
              ))}
            </div>
            {/* Legend */}
            <div className="flex items-center justify-center gap-2 mt-6 text-xs text-muted-foreground">
              <span>Less</span>
              <div className={cn('h-3 w-3 rounded-[2px]', isDark ? 'bg-red-950/80 border border-red-500' : 'bg-red-500')} />
              <div className={cn('h-3 w-3 rounded-[2px]', isDark ? 'bg-red-950/40 border border-red-700/60' : 'bg-red-300')} />
              <div className={cn('h-3 w-3 rounded-[2px]', isDark ? 'bg-zinc-800/50 border border-zinc-700' : 'bg-zinc-100 border border-zinc-200')} />
              <div className={cn('h-3 w-3 rounded-[2px]', isDark ? 'bg-emerald-950/40 border border-emerald-700/60' : 'bg-emerald-300')} />
              <div className={cn('h-3 w-3 rounded-[2px]', isDark ? 'bg-emerald-950/80 border border-emerald-500' : 'bg-emerald-500')} />
              <span>More</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
