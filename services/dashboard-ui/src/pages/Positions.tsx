import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Loader2, TrendingUp, TrendingDown, DollarSign, XCircle } from 'lucide-react'

interface Position {
  id: number
  ticker: string
  strike: number
  option_type: string
  expiration: string | null
  quantity: number
  avg_entry_price: number
  total_cost: number
  profit_target: number
  stop_loss: number
  high_water_mark: number | null
  broker_symbol: string
  status: string
  opened_at: string | null
  closed_at: string | null
  close_reason: string | null
  realized_pnl: number | null
}

export default function Positions() {
  const qc = useQueryClient()

  const { data: openPositions, isLoading: openLoading, isError: openError, refetch: refetchOpen } = useQuery<Position[]>({
    queryKey: ['positions', 'open'],
    queryFn: () => axios.get('/api/v1/positions?status=OPEN').then(r => r.data),
    refetchInterval: 5000,
  })

  const { data: closedPositions, isLoading: closedLoading, isError: closedError } = useQuery<Position[]>({
    queryKey: ['positions', 'closed'],
    queryFn: () => axios.get('/api/v1/positions?status=CLOSED&limit=50').then(r => r.data),
  })

  const closeMut = useMutation({
    mutationFn: (id: number) => axios.post(`/api/v1/positions/${id}/close`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['positions'] }),
  })

  const handleClose = (id: number, ticker: string) => {
    if (window.confirm(`Close position for ${ticker}? This action cannot be undone.`)) {
      closeMut.mutate(id)
    }
  }

  const totalPnl = (closedPositions ?? []).reduce((s, p) => s + (p.realized_pnl ?? 0), 0)
  const winCount = (closedPositions ?? []).filter(p => (p.realized_pnl ?? 0) > 0).length
  const totalClosed = (closedPositions ?? []).length

  if (openError || closedError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <XCircle className="h-10 w-10 text-destructive mb-3" />
        <p className="text-lg font-medium">Failed to load positions</p>
        <Button variant="outline" className="mt-4" onClick={() => refetchOpen()}>Retry</Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <TrendingUp className="h-8 w-8 text-green-500" />
              <div>
                <p className="text-sm text-muted-foreground">Open Positions</p>
                <p className="text-2xl font-bold">{openPositions?.length ?? 0}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <DollarSign className="h-8 w-8 text-blue-500" />
              <div>
                <p className="text-sm text-muted-foreground">Realized P&L</p>
                <p className={`text-2xl font-bold ${totalPnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  ${totalPnl.toFixed(2)}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <TrendingDown className="h-8 w-8 text-yellow-500" />
              <div>
                <p className="text-sm text-muted-foreground">Win Rate</p>
                <p className="text-2xl font-bold">
                  {totalClosed > 0 ? `${((winCount / totalClosed) * 100).toFixed(1)}%` : '—'}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" /> Open Positions
          </CardTitle>
        </CardHeader>
        <CardContent>
          {openLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
          ) : !openPositions?.length ? (
            <p className="text-center text-muted-foreground py-8">No open positions</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Qty</TableHead>
                  <TableHead>Entry</TableHead>
                  <TableHead>PT / SL</TableHead>
                  <TableHead>Opened</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openPositions.map(p => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">
                      {p.ticker} ${p.strike}{p.option_type === 'CALL' ? 'C' : 'P'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.option_type === 'CALL' ? 'default' : 'secondary'}>
                        {p.option_type}
                      </Badge>
                    </TableCell>
                    <TableCell>{p.quantity}</TableCell>
                    <TableCell>${p.avg_entry_price.toFixed(2)}</TableCell>
                    <TableCell className="text-xs">
                      <span className="text-green-500">+{(p.profit_target * 100).toFixed(0)}%</span>
                      {' / '}
                      <span className="text-red-500">-{(p.stop_loss * 100).toFixed(0)}%</span>
                    </TableCell>
                    <TableCell className="text-xs">
                      {p.opened_at ? new Date(p.opened_at).toLocaleString() : '—'}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleClose(p.id, `${p.ticker} $${p.strike}`)}
                        disabled={closeMut.isPending}
                      >
                        <XCircle className="h-4 w-4 mr-1" /> Close
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingDown className="h-5 w-5" /> Closed Positions
          </CardTitle>
        </CardHeader>
        <CardContent>
          {closedLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
          ) : !closedPositions?.length ? (
            <p className="text-center text-muted-foreground py-8">No closed positions yet</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Qty</TableHead>
                  <TableHead>Entry</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>P&L</TableHead>
                  <TableHead>Closed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {closedPositions.map(p => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">
                      {p.ticker} ${p.strike}{p.option_type === 'CALL' ? 'C' : 'P'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.option_type === 'CALL' ? 'default' : 'secondary'}>
                        {p.option_type}
                      </Badge>
                    </TableCell>
                    <TableCell>{p.quantity}</TableCell>
                    <TableCell>${p.avg_entry_price.toFixed(2)}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{p.close_reason ?? '—'}</Badge>
                    </TableCell>
                    <TableCell>
                      {p.realized_pnl != null ? (
                        <span className={p.realized_pnl >= 0 ? 'text-green-500' : 'text-red-500'}>
                          ${p.realized_pnl.toFixed(2)}
                        </span>
                      ) : '—'}
                    </TableCell>
                    <TableCell className="text-xs">
                      {p.closed_at ? new Date(p.closed_at).toLocaleString() : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
