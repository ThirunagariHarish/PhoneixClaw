import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { X, Loader2 } from 'lucide-react'
import type { Node } from '@xyflow/react'

interface SourceOption {
  id: string
  display_name: string
  source_type: string
  server_id?: string | null
  server_name?: string | null
  data_purpose: string
  enabled: boolean
  connection_status: string
}

interface TradingAccountOption {
  id: string
  display_name: string
  broker_type: string
  paper_mode: boolean
  enabled: boolean
  health_status: string
}

interface Props {
  node: Node | null
  onUpdate: (id: string, data: Record<string, unknown>) => void
  onClose: () => void
}

export function NodeConfigPanel({ node, onUpdate, onClose }: Props) {
  const showSourcePicker = node?.type === 'dataSource'
  const showAccountPicker = node?.type === 'broker'

  const { data: sources, isLoading: sourcesLoading } = useQuery<SourceOption[]>({
    queryKey: ['sources'],
    queryFn: () => axios.get('/api/v1/sources').then(r => r.data),
    enabled: showSourcePicker,
  })

  const { data: accounts, isLoading: accountsLoading } = useQuery<TradingAccountOption[]>({
    queryKey: ['pipeline-accounts'],
    queryFn: () => axios.get('/api/v1/accounts').then(r => r.data),
    enabled: showAccountPicker,
  })

  if (!node) return null

  const data = node.data as Record<string, unknown>

  const update = (key: string, value: unknown) => {
    onUpdate(node.id, { ...data, [key]: value })
  }

  const subtype = String(data.subtype || '')

  const filteredSources = (sources || []).filter(s => {
    if (subtype === 'discord') return s.source_type === 'discord' && s.data_purpose === 'trades'
    if (subtype === 'sentiment') return s.source_type === 'discord' && s.data_purpose === 'sentiment'
    if (subtype === 'news') return true
    return true
  })

  const filteredAccounts = (accounts || []).filter(a => {
    if (subtype === 'alpaca') return a.broker_type === 'alpaca'
    if (subtype === 'ibkr') return a.broker_type === 'ibkr'
    return true
  })

  return (
    <div className="w-64 border-l bg-muted/30 flex flex-col">
      <div className="flex items-center justify-between p-3 border-b">
        <h3 className="text-sm font-semibold">Configure Node</h3>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="p-3 space-y-4 overflow-auto flex-1">
        <div className="space-y-2">
          <Label className="text-xs">Label</Label>
          <Input
            value={String(data.label || '')}
            onChange={e => update('label', e.target.value)}
            className="h-8 text-xs"
          />
        </div>

        {/* ── Data Source Nodes ─────────────────────────────── */}
        {node.type === 'dataSource' && (
          <>
            <div className="space-y-2">
              <Label className="text-xs">Source Type</Label>
              <Select value={String(data.subtype || 'discord')} onValueChange={v => update('subtype', v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="discord">Discord</SelectItem>
                  <SelectItem value="sentiment">Sentiment Feed</SelectItem>
                  <SelectItem value="news">News Feed</SelectItem>
                  <SelectItem value="chat">Chat Input</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {(subtype === 'discord' || subtype === 'sentiment') && (
              <div className="space-y-2">
                <Label className="text-xs">Data Source</Label>
                {sourcesLoading ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                    <Loader2 className="h-3 w-3 animate-spin" /> Loading sources...
                  </div>
                ) : filteredSources.length > 0 ? (
                  <Select
                    value={String(data.source_id || '')}
                    onValueChange={v => {
                      const src = filteredSources.find(s => s.id === v)
                      onUpdate(node.id, { ...data, source_id: v, source_name: src?.display_name || '' })
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Select a source..." /></SelectTrigger>
                    <SelectContent>
                      {filteredSources.map(s => (
                        <SelectItem key={s.id} value={s.id}>
                          <span className="truncate">{s.display_name}</span>
                          {s.server_name && (
                            <span className="text-muted-foreground ml-1">({s.server_name})</span>
                          )}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <p className="text-[11px] text-muted-foreground">
                    No {subtype === 'sentiment' ? 'sentiment' : 'trade'} sources configured.
                    Add one in Data Sources.
                  </p>
                )}
              </div>
            )}

            {subtype === 'news' && (
              <div className="space-y-2">
                <Label className="text-xs">News API</Label>
                <Select value={String(data.news_api || 'all')} onValueChange={v => update('news_api', v)}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Sources</SelectItem>
                    <SelectItem value="finnhub">Finnhub</SelectItem>
                    <SelectItem value="newsapi">NewsAPI</SelectItem>
                    <SelectItem value="alphavantage">Alpha Vantage</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </>
        )}

        {/* ── Processing Nodes ─────────────────────────────── */}
        {node.type === 'processing' && (
          <>
            {subtype === 'sentiment_analyzer' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Model</Label>
                  <Select value={String(data.model || 'finbert')} onValueChange={v => update('model', v)}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="finbert">FinBERT</SelectItem>
                      <SelectItem value="llm">LLM (Mistral)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Confidence Threshold</Label>
                  <Input
                    type="number"
                    step="0.05"
                    min="0"
                    max="1"
                    value={String(data.confidence_threshold ?? '0.6')}
                    onChange={e => update('confidence_threshold', parseFloat(e.target.value) || 0.6)}
                    className="h-8 text-xs"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Aggregation Window</Label>
                  <Select value={String(data.window || '30m')} onValueChange={v => update('window', v)}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="5m">5 minutes</SelectItem>
                      <SelectItem value="15m">15 minutes</SelectItem>
                      <SelectItem value="30m">30 minutes</SelectItem>
                      <SelectItem value="1h">1 hour</SelectItem>
                      <SelectItem value="4h">4 hours</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}

            {subtype === 'parser' && (
              <div className="space-y-2">
                <Label className="text-xs">Min Confidence</Label>
                <Input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={String(data.min_confidence ?? '0.7')}
                  onChange={e => update('min_confidence', parseFloat(e.target.value) || 0.7)}
                  className="h-8 text-xs"
                />
              </div>
            )}

            {subtype === 'ticker_extractor' && (
              <div className="space-y-2">
                <Label className="text-xs">Min Confidence</Label>
                <Input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={String(data.min_confidence ?? '0.8')}
                  onChange={e => update('min_confidence', parseFloat(e.target.value) || 0.8)}
                  className="h-8 text-xs"
                />
              </div>
            )}
          </>
        )}

        {/* ── AI Model Nodes ───────────────────────────────── */}
        {node.type === 'aiModel' && (
          <>
            <div className="space-y-2">
              <Label className="text-xs">Model</Label>
              <Select value={String(data.subtype || 'mistral')} onValueChange={v => update('subtype', v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="mistral">LLM (Mistral)</SelectItem>
                  <SelectItem value="llama">LLM (Llama 3.1)</SelectItem>
                  <SelectItem value="option_analyzer">Option Chain Analyzer</SelectItem>
                  <SelectItem value="trade_recommender">AI Trade Recommender</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {(subtype === 'mistral' || subtype === 'llama') && (
              <div className="space-y-2">
                <Label className="text-xs">Temperature</Label>
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={String(data.temperature ?? '0.7')}
                  onChange={e => update('temperature', parseFloat(e.target.value) || 0.7)}
                  className="h-8 text-xs"
                />
              </div>
            )}
          </>
        )}

        {/* ── Broker Nodes ─────────────────────────────────── */}
        {node.type === 'broker' && (
          <>
            <div className="space-y-2">
              <Label className="text-xs">Broker</Label>
              <Select value={String(data.subtype || 'alpaca')} onValueChange={v => update('subtype', v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="alpaca">Alpaca</SelectItem>
                  <SelectItem value="ibkr">Interactive Brokers</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-xs">Trading Account</Label>
              {accountsLoading ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                  <Loader2 className="h-3 w-3 animate-spin" /> Loading accounts...
                </div>
              ) : filteredAccounts.length > 0 ? (
                <Select
                  value={String(data.account_id || '')}
                    onValueChange={v => {
                      const acct = filteredAccounts.find(a => a.id === v)
                      onUpdate(node.id, {
                        ...data,
                        account_id: v,
                        account_name: acct?.display_name || '',
                        paper_mode: acct?.paper_mode ?? true,
                      })
                    }}
                >
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Select account..." /></SelectTrigger>
                  <SelectContent>
                    {filteredAccounts.map(a => (
                      <SelectItem key={a.id} value={a.id}>
                        {a.display_name} {a.paper_mode ? '(Paper)' : '(Live)'}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  No {subtype} accounts configured. Add one in Trading Accounts.
                </p>
              )}
            </div>
          </>
        )}

        {/* ── Control Nodes ────────────────────────────────── */}
        {node.type === 'control' && (
          <>
            {subtype === 'condition' && (
              <div className="space-y-2">
                <Label className="text-xs">Condition Expression</Label>
                <Input
                  value={String(data.expression || '')}
                  onChange={e => update('expression', e.target.value)}
                  className="h-8 text-xs font-mono"
                  placeholder="e.g. sentiment_score > 0.5"
                />
              </div>
            )}
            {subtype === 'delay' && (
              <div className="space-y-2">
                <Label className="text-xs">Delay (seconds)</Label>
                <Input
                  type="number"
                  min="1"
                  value={String(data.delay_seconds ?? '30')}
                  onChange={e => update('delay_seconds', parseInt(e.target.value) || 30)}
                  className="h-8 text-xs"
                />
              </div>
            )}
            {subtype === 'market_hours' && (
              <div className="space-y-2">
                <Label className="text-xs">Trading Hours</Label>
                <Select value={String(data.hours_mode || 'regular')} onValueChange={v => update('hours_mode', v)}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="regular">Regular Hours (9:30-16:00 ET)</SelectItem>
                    <SelectItem value="extended">Extended Hours (4:00-20:00 ET)</SelectItem>
                    <SelectItem value="all">All Hours (24/7)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </>
        )}

        <div className="pt-2 border-t">
          <p className="text-[10px] text-muted-foreground">
            Node ID: {node.id}
          </p>
          <p className="text-[10px] text-muted-foreground">
            Type: {node.type}
          </p>
        </div>
      </div>
    </div>
  )
}
