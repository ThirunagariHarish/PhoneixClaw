/**
 * P6: Robinhood-style equity curve with drawdown shading.
 * Reads from /api/v2/agents/{id}/equity-curve or /api/v2/portfolio/equity-curve.
 */
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

/* eslint-disable @typescript-eslint/no-explicit-any */
const RChart = ComposedChart as any
const RLine = Line as any
const RArea = Area as any
const RXAxis = XAxis as any
const RYAxis = YAxis as any
const RGrid = CartesianGrid as any
const RTooltip = Tooltip as any
const RContainer = ResponsiveContainer as any
const RRefLine = ReferenceLine as any

interface CurvePoint {
  timestamp: string | null
  equity: number
  high_water_mark: number
  drawdown_pct: number
  pnl: number
  symbol?: string
}

interface Props {
  agentId?: string  // omit for global portfolio
  days?: number
  height?: number
  title?: string
}

export function EquityCurveChart({ agentId, days = 30, height = 280, title }: Props) {
  const url = agentId
    ? `/api/v2/agents/${agentId}/equity-curve?days=${days}`
    : `/api/v2/portfolio/equity-curve?days=${days}`

  const { data, isLoading } = useQuery<{ curve: CurvePoint[]; starting_capital: number }>({
    queryKey: ['equity-curve', agentId ?? 'global', days],
    queryFn: async () => (await api.get(url)).data,
    refetchInterval: 30000,
  })

  const curve = data?.curve ?? []
  const startCap = data?.starting_capital ?? 100_000
  const chartData = curve.map((p) => ({
    date: p.timestamp ? new Date(p.timestamp).toLocaleDateString() : '',
    equity: p.equity,
    drawdown: p.drawdown_pct * 100,
    dd_fill: p.drawdown_pct * startCap * -1,
    pnl: p.pnl,
  }))

  const latest = curve.length ? curve[curve.length - 1] : null
  const returnPct = latest ? ((latest.equity - startCap) / startCap) * 100 : 0

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">
            {title ?? (agentId ? 'Agent Portfolio' : 'Global Portfolio')}
          </CardTitle>
          {latest && (
            <div className="text-right">
              <div className="text-2xl font-semibold">
                ${latest.equity.toLocaleString()}
              </div>
              <div
                className={`text-sm ${returnPct >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}
              >
                {returnPct >= 0 ? '+' : ''}
                {returnPct.toFixed(2)}% · {days}d
              </div>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="h-[280px] flex items-center justify-center text-sm text-muted-foreground">
            Loading equity curve…
          </div>
        ) : chartData.length === 0 ? (
          <div className="h-[280px] flex items-center justify-center text-sm text-muted-foreground">
            No closed trades yet
          </div>
        ) : (
          <RContainer width="100%" height={height}>
            <RChart data={chartData}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <RGrid strokeDasharray="3 3" stroke="#2d3748" opacity={0.25} />
              <RXAxis dataKey="date" fontSize={11} tick={{ fill: '#94a3b8' }} />
              <RYAxis
                yAxisId="equity"
                fontSize={11}
                tick={{ fill: '#94a3b8' }}
                tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              />
              <RTooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  fontSize: '12px',
                }}
                formatter={(value: number, name: string) => {
                  if (name === 'equity') return [`$${value.toFixed(2)}`, 'Equity']
                  if (name === 'drawdown') return [`${value.toFixed(2)}%`, 'Drawdown']
                  return [value, name]
                }}
              />
              <RRefLine yAxisId="equity" y={startCap} stroke="#64748b" strokeDasharray="4 4" />
              <RArea
                yAxisId="equity"
                type="monotone"
                dataKey="equity"
                stroke="#10b981"
                strokeWidth={2}
                fill="url(#equityGradient)"
              />
              <RLine
                yAxisId="equity"
                type="monotone"
                dataKey="equity"
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
              />
            </RChart>
          </RContainer>
        )}
      </CardContent>
    </Card>
  )
}
