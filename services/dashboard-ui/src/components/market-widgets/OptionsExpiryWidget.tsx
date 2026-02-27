import { useState, useMemo } from 'react'

function getThirdFriday(year: number, month: number): Date {
  const d = new Date(year, month, 1)
  const dayOfWeek = d.getDay()
  const firstFriday = dayOfWeek <= 5 ? (5 - dayOfWeek + 1) : (5 + 7 - dayOfWeek + 1)
  return new Date(year, month, firstFriday + 14)
}

function getWeeklyFridays(startDate: Date, count: number): Date[] {
  const fridays: Date[] = []
  const d = new Date(startDate)
  d.setDate(d.getDate() + ((5 - d.getDay() + 7) % 7 || 7))
  for (let i = 0; i < count; i++) {
    fridays.push(new Date(d))
    d.setDate(d.getDate() + 7)
  }
  return fridays
}

interface ExpiryDate {
  date: Date
  type: 'monthly' | 'weekly'
  label: string
  daysUntil: number
}

export default function OptionsExpiryWidget() {
  const [filter, setFilter] = useState<'all' | 'monthly' | 'weekly'>('all')

  const expiryDates = useMemo(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const dates: ExpiryDate[] = []

    for (let m = 0; m < 4; m++) {
      const month = today.getMonth() + m
      const year = today.getFullYear() + Math.floor(month / 12)
      const opex = getThirdFriday(year, month % 12)
      if (opex >= today) {
        const diff = Math.ceil((opex.getTime() - today.getTime()) / 86400000)
        dates.push({
          date: opex,
          type: 'monthly',
          label: opex.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          daysUntil: diff,
        })
      }
    }

    const weeklies = getWeeklyFridays(today, 8)
    for (const w of weeklies) {
      const diff = Math.ceil((w.getTime() - today.getTime()) / 86400000)
      const alreadyMonthly = dates.some(d => d.date.toDateString() === w.toDateString())
      if (!alreadyMonthly) {
        dates.push({
          date: w,
          type: 'weekly',
          label: w.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          daysUntil: diff,
        })
      }
    }

    dates.sort((a, b) => a.date.getTime() - b.date.getTime())
    return dates
  }, [])

  const filtered = filter === 'all' ? expiryDates : expiryDates.filter(d => d.type === filter)

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-hidden">
      <div className="flex gap-1">
        {(['all', 'monthly', 'weekly'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
              filter === f ? 'bg-purple-500/20 border-purple-500/40 text-purple-400' : 'border-border hover:bg-muted/50'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-auto space-y-1">
        {filtered.map((d, i) => (
          <div key={i} className="flex items-center justify-between px-2 py-1.5 rounded hover:bg-muted/50">
            <div className="flex items-center gap-2">
              <div className={`h-2 w-2 rounded-full ${d.type === 'monthly' ? 'bg-orange-500' : 'bg-blue-500'}`} />
              <span className="text-xs font-medium">{d.label}</span>
              <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${
                d.type === 'monthly' ? 'bg-orange-500/10 text-orange-400' : 'bg-blue-500/10 text-blue-400'
              }`}>
                {d.type === 'monthly' ? 'OPEX' : 'Weekly'}
              </span>
            </div>
            <span className={`text-[10px] font-mono ${
              d.daysUntil <= 2 ? 'text-red-400 font-bold' : d.daysUntil <= 5 ? 'text-yellow-400' : 'text-muted-foreground'
            }`}>
              {d.daysUntil === 0 ? 'TODAY' : d.daysUntil === 1 ? '1 day' : `${d.daysUntil} days`}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
