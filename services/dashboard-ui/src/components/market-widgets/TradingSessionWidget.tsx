import { useState, useEffect } from 'react'

interface Session {
  name: string
  tz: string
  openHour: number
  closeHour: number
  color: string
}

const SESSIONS: Session[] = [
  { name: 'Sydney', tz: 'Australia/Sydney', openHour: 10, closeHour: 16, color: 'bg-blue-500' },
  { name: 'Tokyo', tz: 'Asia/Tokyo', openHour: 9, closeHour: 15, color: 'bg-rose-500' },
  { name: 'London', tz: 'Europe/London', openHour: 8, closeHour: 16.5, color: 'bg-emerald-500' },
  { name: 'New York', tz: 'America/New_York', openHour: 9.5, closeHour: 16, color: 'bg-purple-500' },
]

function getSessionStatus(session: Session, now: Date) {
  const local = new Date(now.toLocaleString('en-US', { timeZone: session.tz }))
  const hours = local.getHours() + local.getMinutes() / 60
  const day = local.getDay()
  const isWeekend = day === 0 || day === 6
  const isOpen = !isWeekend && hours >= session.openHour && hours < session.closeHour

  let minutesUntilChange: number
  if (isWeekend || hours >= session.closeHour) {
    const nextOpen = session.openHour
    const hoursUntil = hours >= session.closeHour ? (24 - hours + nextOpen) : nextOpen - hours
    minutesUntilChange = Math.round(hoursUntil * 60)
  } else if (hours < session.openHour) {
    minutesUntilChange = Math.round((session.openHour - hours) * 60)
  } else {
    minutesUntilChange = Math.round((session.closeHour - hours) * 60)
  }

  const localTime = local.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  return { isOpen, minutesUntilChange, localTime, isWeekend }
}

function formatDuration(minutes: number): string {
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60)
    const m = minutes % 60
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  return `${minutes}m`
}

export default function TradingSessionWidget() {
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 30000)
    return () => clearInterval(interval)
  }, [])

  const sessionData = SESSIONS.map(s => ({ ...s, status: getSessionStatus(s, now) }))
  const activeSessions = sessionData.filter(s => s.status.isOpen)

  return (
    <div className="p-2 h-full flex flex-col gap-2 overflow-auto">
      {activeSessions.length > 0 ? (
        <div className="text-center py-1">
          <p className="text-[9px] text-muted-foreground uppercase">Active Now</p>
          <p className="text-xs font-medium text-green-400">{activeSessions.map(s => s.name).join(' + ')}</p>
        </div>
      ) : (
        <div className="text-center py-1">
          <p className="text-[9px] text-muted-foreground uppercase">All Sessions Closed</p>
        </div>
      )}

      <div className="relative h-6 bg-muted/20 rounded-full overflow-hidden">
        {SESSIONS.map(session => {
          const startPct = (session.openHour / 24) * 100
          const widthPct = ((session.closeHour - session.openHour) / 24) * 100
          return (
            <div key={session.name} className={`absolute top-0 h-full ${session.color} opacity-30 rounded`}
              style={{ left: `${startPct}%`, width: `${widthPct}%` }}
              title={session.name} />
          )
        })}
        <div className="absolute top-0 h-full w-0.5 bg-white/80 z-10"
          style={{ left: `${((now.getUTCHours() + now.getUTCMinutes() / 60) / 24) * 100}%` }} />
      </div>
      <div className="flex justify-between text-[8px] text-muted-foreground px-1">
        <span>00:00 UTC</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>24:00</span>
      </div>

      <div className="flex-1 space-y-1">
        {sessionData.map(s => (
          <div key={s.name} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/50">
            <div className={`h-2 w-2 rounded-full ${s.color} ${s.status.isOpen ? 'animate-pulse' : 'opacity-40'}`} />
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-medium">{s.name}</p>
              <p className="text-[9px] text-muted-foreground font-mono">{s.status.localTime}</p>
            </div>
            <div className="text-right">
              <span className={`text-[9px] font-medium ${s.status.isOpen ? 'text-green-400' : 'text-muted-foreground'}`}>
                {s.status.isWeekend ? 'Weekend' : s.status.isOpen ? 'OPEN' : 'Closed'}
              </span>
              {!s.status.isWeekend && (
                <p className="text-[8px] text-muted-foreground">
                  {s.status.isOpen ? 'Closes' : 'Opens'} in {formatDuration(s.status.minutesUntilChange)}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2 justify-center flex-wrap">
        {SESSIONS.map(s => (
          <div key={s.name} className="flex items-center gap-1">
            <div className={`h-1.5 w-1.5 rounded-full ${s.color}`} />
            <span className="text-[8px] text-muted-foreground">{s.name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
