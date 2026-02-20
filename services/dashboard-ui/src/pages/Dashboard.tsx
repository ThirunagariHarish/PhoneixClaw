import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TrendingUp, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'

interface Trade {
  trade_id: string
  ticker: string
  action: string
  strike: number
  price: number
  status: string
  created_at: string
}

const statusBadge = (status: string) => {
  switch (status) {
    case 'EXECUTED':
      return <Badge variant="success">Executed</Badge>
    case 'ERROR':
      return <Badge variant="destructive">Error</Badge>
    case 'REJECTED':
      return <Badge variant="warning">Rejected</Badge>
    default:
      return <Badge variant="secondary">{status}</Badge>
  }
}

const kpiCards = [
  { key: 'total', label: 'Total Trades', icon: TrendingUp, color: 'text-primary' },
  { key: 'executed', label: 'Executed', icon: CheckCircle2, color: 'text-emerald-500' },
  { key: 'rejected', label: 'Rejected', icon: AlertTriangle, color: 'text-amber-500' },
  { key: 'errored', label: 'Errors', icon: XCircle, color: 'text-red-500' },
] as const

export default function Dashboard() {
  const { data: trades } = useQuery<Trade[]>({
    queryKey: ['trades'],
    queryFn: () => axios.get('/api/v1/trades?limit=20').then((r) => r.data),
  })
  const { data: metrics } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => axios.get('/api/v1/metrics/daily?days=7').then((r) => r.data),
  })

  const stats = {
    total: trades?.length || 0,
    executed: trades?.filter((t) => t.status === 'EXECUTED').length || 0,
    rejected: trades?.filter((t) => t.status === 'REJECTED').length || 0,
    errored: trades?.filter((t) => t.status === 'ERROR').length || 0,
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {kpiCards.map(({ key, label, icon: Icon, color }) => (
          <Card key={key}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">{label}</p>
                  <p className="text-3xl font-bold mt-1">{stats[key]}</p>
                </div>
                <div className={`${color} opacity-80`}>
                  <Icon className="h-8 w-8" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {metrics && metrics.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Daily P&L (7 days)</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={metrics}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" className="text-xs" tick={{ fill: 'hsl(var(--muted-foreground))' }} />
                <YAxis className="text-xs" tick={{ fill: 'hsl(var(--muted-foreground))' }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px',
                    color: 'hsl(var(--card-foreground))',
                  }}
                />
                <Bar dataKey="total_pnl" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Trades</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Strike</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(trades || []).map((t) => (
                <TableRow key={t.trade_id}>
                  <TableCell className="font-medium">{t.ticker}</TableCell>
                  <TableCell>
                    <span className={t.action === 'BUY' ? 'text-emerald-500' : 'text-red-500'}>
                      {t.action}
                    </span>
                  </TableCell>
                  <TableCell>{t.strike}</TableCell>
                  <TableCell>${t.price?.toFixed(2)}</TableCell>
                  <TableCell>{statusBadge(t.status)}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
                  </TableCell>
                </TableRow>
              ))}
              {(!trades || trades.length === 0) && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    No trades yet. Connect a data source to get started.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
