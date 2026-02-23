import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Loader2, XCircle } from 'lucide-react'

export default function Analytics() {
  const { data: metrics, isLoading, isError, refetch } = useQuery({
    queryKey: ['analytics-metrics'],
    queryFn: () => axios.get('/api/v1/metrics/daily?days=30').then((r) => r.data),
  })

  const cumulativePnl = (metrics || []).reduce(
    (acc: { date: string; cumulative: number; daily: number }[], m: { date: string; total_pnl?: number }) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].cumulative : 0
      acc.push({
        date: m.date,
        cumulative: prev + (m.total_pnl || 0),
        daily: m.total_pnl || 0,
      })
      return acc
    },
    [],
  )

  const winRateData = (metrics || []).map(
    (m: { date: string; winning_trades?: number; total_trades?: number }) => ({
      date: m.date,
      winRate: m.winning_trades && m.total_trades ? Math.round((m.winning_trades / m.total_trades) * 100) : 0,
    }),
  )

  const tooltipStyle = {
    backgroundColor: 'hsl(var(--card))',
    border: '1px solid hsl(var(--border))',
    borderRadius: '8px',
    color: 'hsl(var(--card-foreground))',
  }
  const tickFill = 'hsl(var(--muted-foreground))'

  if (isLoading) {
    return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <XCircle className="h-10 w-10 text-destructive mb-3" />
        <p className="text-lg font-medium">Failed to load analytics</p>
        <Button variant="outline" className="mt-4" onClick={() => refetch()}>Retry</Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cumulative P&L (30 days)</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={cumulativePnl}>
                <defs>
                  <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--chart-1))" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={{ fill: tickFill, fontSize: 12 }} />
                <YAxis tick={{ fill: tickFill, fontSize: 12 }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area
                  type="monotone"
                  dataKey="cumulative"
                  stroke="hsl(var(--chart-1))"
                  fill="url(#pnlGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Win Rate Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={winRateData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={{ fill: tickFill, fontSize: 12 }} />
                <YAxis tick={{ fill: tickFill, fontSize: 12 }} domain={[0, 100]} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [`${v}%`, 'Win Rate']} />
                <Line
                  type="monotone"
                  dataKey="winRate"
                  stroke="hsl(var(--chart-2))"
                  strokeWidth={2}
                  dot={{ r: 3, fill: 'hsl(var(--chart-2))' }}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Daily P&L Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={cumulativePnl}>
              <defs>
                <linearGradient id="dailyGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--chart-3))" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="hsl(var(--chart-3))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="date" tick={{ fill: tickFill, fontSize: 12 }} />
              <YAxis tick={{ fill: tickFill, fontSize: 12 }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Area
                type="monotone"
                dataKey="daily"
                stroke="hsl(var(--chart-3))"
                fill="url(#dailyGrad)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  )
}
