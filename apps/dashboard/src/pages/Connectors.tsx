/**
 * Connectors page — multi-platform connector management with guided wizard.
 * Supports: Discord, Reddit, Twitter/X, Unusual Whales, News API, Webhook,
 *           Alpaca, IBKR, Tradier.
 */
import { useState, useEffect, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Badge } from '@/components/ui/badge'
import {
  Plug, Plus, Loader2, Server, Hash, Trash2, MoreVertical,
  CheckSquare, Square as SquareIcon, ChevronRight, ChevronLeft, Wifi, X,
  MessageSquare, Newspaper, Globe, Webhook, TrendingUp, Landmark, BarChart3,
  Activity, Radio,
} from 'lucide-react'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

// ─── Types ──────────────────────────────────────────────────────────────────

interface Connector {
  id: string
  name: string
  type: string
  status: string
  config: Record<string, unknown>
  tags: string[]
  is_active: boolean
  last_connected_at: string | null
  error_message: string | null
  created_at: string
}

const SUGGESTED_TAGS = ['signals', 'news', 'trends', 'options-flow', 'market-data', 'social'] as const

interface GuildInfo {
  guild_id: string
  guild_name: string
  channel_count: number
}

interface ChannelInfo {
  channel_id: string
  channel_name: string
  guild_id: string
  guild_name: string
  category: string | null
}

type PlatformType =
  | 'discord' | 'discord_webhook' | 'reddit' | 'twitter' | 'unusual_whales' | 'news_api'
  | 'custom_webhook' | 'alpaca' | 'ibkr' | 'tradier' | 'robinhood'
  | 'yfinance' | 'polygon' | 'alphavantage'
  | 'whatsapp' | 'telegram'

// ─── Platform Metadata ──────────────────────────────────────────────────────

interface PlatformMeta {
  type: PlatformType
  label: string
  description: string
  category: 'data' | 'broker'
  icon: typeof Plug
  color: string
  bgColor: string
}

const PLATFORMS: PlatformMeta[] = [
  { type: 'discord',         label: 'Discord Bot',     description: 'Pull signals via official Discord Bot API', category: 'data',   icon: MessageSquare, color: 'text-indigo-500',  bgColor: 'bg-indigo-500/10' },
  { type: 'discord_webhook', label: 'Discord Webhook',  description: 'Receive signals via webhook relay (no bot needed)', category: 'data', icon: Webhook, color: 'text-indigo-400', bgColor: 'bg-indigo-400/10' },
  { type: 'reddit',          label: 'Reddit',          description: 'Monitor subreddit discussions',           category: 'data',   icon: Globe,         color: 'text-orange-500',  bgColor: 'bg-orange-500/10' },
  { type: 'twitter',         label: 'Twitter / X',     description: 'Follow trader accounts',                  category: 'data',   icon: Radio,         color: 'text-sky-500',     bgColor: 'bg-sky-500/10' },
  { type: 'unusual_whales',  label: 'Unusual Whales',  description: 'Options flow and dark pool data',         category: 'data',   icon: Activity,      color: 'text-purple-500',  bgColor: 'bg-purple-500/10' },
  { type: 'news_api',        label: 'News API',        description: 'Financial news headlines',                category: 'data',   icon: Newspaper,     color: 'text-emerald-500', bgColor: 'bg-emerald-500/10' },
  { type: 'custom_webhook',  label: 'Webhook',         description: 'Receive signals via HTTP',                category: 'data',   icon: Webhook,       color: 'text-zinc-400',    bgColor: 'bg-zinc-500/10' },
  { type: 'alpaca',          label: 'Alpaca',          description: 'Commission-free stock & options trading', category: 'broker', icon: TrendingUp,    color: 'text-yellow-500',  bgColor: 'bg-yellow-500/10' },
  { type: 'ibkr',            label: 'Interactive Brokers', description: 'Professional multi-asset broker',     category: 'broker', icon: Landmark,      color: 'text-red-500',     bgColor: 'bg-red-500/10' },
  { type: 'tradier',         label: 'Tradier',         description: 'Options-focused broker',                  category: 'broker', icon: BarChart3,     color: 'text-teal-500',    bgColor: 'bg-teal-500/10' },
  { type: 'robinhood',       label: 'Robinhood',       description: 'Commission-free stock & options via MCP',  category: 'broker', icon: TrendingUp,    color: 'text-green-500',   bgColor: 'bg-green-500/10' },
  { type: 'yfinance',        label: 'Yahoo Finance',   description: 'Free historical OHLCV and options data',  category: 'data',   icon: TrendingUp,    color: 'text-violet-500',  bgColor: 'bg-violet-500/10' },
  { type: 'polygon',         label: 'Polygon.io',      description: 'Real-time and historical market data',    category: 'data',   icon: BarChart3,     color: 'text-cyan-500',    bgColor: 'bg-cyan-500/10' },
  { type: 'alphavantage',    label: 'Alpha Vantage',   description: 'Free stock API with technical indicators', category: 'data',   icon: Activity,      color: 'text-lime-500',    bgColor: 'bg-lime-500/10' },
  { type: 'whatsapp',        label: 'WhatsApp',        description: 'Per-agent tagged threads via Meta Cloud API', category: 'data', icon: MessageSquare, color: 'text-green-400',   bgColor: 'bg-green-500/10' },
  { type: 'telegram',        label: 'Telegram Bot',    description: 'Per-agent groups via Telegram Bot API',      category: 'data', icon: MessageSquare, color: 'text-sky-400',     bgColor: 'bg-sky-500/10' },
]

function platformMeta(type: string): PlatformMeta {
  return PLATFORMS.find((p) => p.type === type) || PLATFORMS[0]
}

// ─── Shared helpers ─────────────────────────────────────────────────────────

function extractApiError(err: unknown): string {
  const resp = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
  if (resp?.detail) {
    if (typeof resp.detail === 'string') return resp.detail
    if (Array.isArray(resp.detail))
      return resp.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
  }
  return ''
}

// ─── Platform Selection Step ────────────────────────────────────────────────

function PlatformSelectStep({
  selected,
  onSelect,
}: {
  selected: PlatformType | null
  onSelect: (t: PlatformType) => void
}) {
  const dataSources = PLATFORMS.filter((p) => p.category === 'data' && !['yfinance', 'polygon', 'alphavantage'].includes(p.type))
  const marketData = PLATFORMS.filter((p) => ['yfinance', 'polygon', 'alphavantage'].includes(p.type))
  const brokers = PLATFORMS.filter((p) => p.category === 'broker')

  const renderGroup = (title: string, items: PlatformMeta[]) => (
    <div>
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">{title}</p>
      <div className="grid grid-cols-2 gap-2">
        {items.map((p) => {
          const Icon = p.icon
          const isActive = selected === p.type
          return (
            <button
              key={p.type}
              type="button"
              onClick={() => onSelect(p.type)}
              className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-all ${
                isActive
                  ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
                  : 'border-border hover:border-primary/40 hover:bg-accent/50'
              }`}
            >
              <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${p.bgColor}`}>
                <Icon className={`h-4.5 w-4.5 ${p.color}`} />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{p.label}</p>
                <p className="text-[11px] text-muted-foreground leading-tight">{p.description}</p>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )

  return (
    <div className="space-y-4 py-1">
      {renderGroup('Data Sources', dataSources)}
      {renderGroup('Market Data', marketData)}
      {renderGroup('Brokers', brokers)}
    </div>
  )
}

// ─── Discord Steps ──────────────────────────────────────────────────────────

const AUTH_HELP: Record<string, string> = {
  bot: 'Create a bot at discord.com/developers, copy the bot token, and invite it to your server. This is the only Discord-approved method for automated message reading.',
}

function DiscordCredentialsStep({
  form,
  setForm,
}: {
  form: { display_name: string; auth_type: string; token: string }
  setForm: (fn: (prev: typeof form) => typeof form) => void
}) {
  return (
    <div className="space-y-4 py-2">
      <div className="space-y-1.5">
        <Label htmlFor="ds-name">Display Name</Label>
        <Input
          id="ds-name"
          value={form.display_name}
          onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
          placeholder="e.g. Trading Alerts Server"
        />
      </div>
      <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-2">
        <p className="text-sm font-medium text-primary">Discord Bot Token (Required)</p>
        <p className="text-xs text-muted-foreground">{AUTH_HELP.bot}</p>
        <ol className="text-xs text-muted-foreground list-decimal list-inside space-y-0.5">
          <li>Go to <a href="https://discord.com/developers/applications" target="_blank" rel="noreferrer" className="underline text-primary/80">discord.com/developers</a> and create a New Application</li>
          <li>Go to <strong>Bot</strong> tab, click &quot;Reset Token&quot;, copy the token</li>
          <li>Enable <strong>Message Content Intent</strong> under Privileged Gateway Intents</li>
          <li>Go to <strong>OAuth2 &gt; URL Generator</strong>, select <code className="text-[10px] bg-muted px-1 rounded">bot</code> scope + &quot;Read Messages&quot; + &quot;Read Message History&quot;</li>
          <li>Copy the invite URL and send it to the server admin</li>
        </ol>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="ds-token">Bot Token</Label>
        <Input
          id="ds-token"
          type="password"
          value={form.token}
          onChange={(e) => setForm((f) => ({ ...f, token: e.target.value }))}
          placeholder="Bot token from Developer Portal"
          className="font-mono"
        />
      </div>
    </div>
  )
}

function DiscordServerStep({
  servers,
  selectedId,
  onSelect,
}: {
  servers: GuildInfo[]
  selectedId: string
  onSelect: (id: string, name: string) => void
}) {
  if (servers.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center">
        <Server className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">No servers found for this account.</p>
      </div>
    )
  }
  return (
    <div className="space-y-2 max-h-72 overflow-y-auto pr-1 py-2">
      {servers.map((g) => (
        <button
          key={g.guild_id}
          type="button"
          onClick={() => onSelect(g.guild_id, g.guild_name)}
          className={`w-full flex items-center gap-3 rounded-lg border p-3.5 text-left transition-all ${
            selectedId === g.guild_id
              ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
              : 'border-border hover:border-primary/40 hover:bg-accent/50'
          }`}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500/10">
            <Server className="h-5 w-5 text-indigo-500" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{g.guild_name}</p>
            <p className="text-xs text-muted-foreground">
              {g.channel_count} channel{g.channel_count !== 1 ? 's' : ''}
            </p>
          </div>
          {selectedId === g.guild_id && (
            <Badge variant="default" className="text-[10px]">Selected</Badge>
          )}
        </button>
      ))}
    </div>
  )
}

function DiscordChannelStep({
  channels,
  selectedChannels,
  onToggle,
  onToggleAll,
}: {
  channels: ChannelInfo[]
  selectedChannels: Set<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
}) {
  const byCategory = useMemo(() => {
    const groups: Record<string, ChannelInfo[]> = {}
    for (const ch of channels) {
      const cat = ch.category || 'Uncategorized'
      ;(groups[cat] ??= []).push(ch)
    }
    return Object.entries(groups).sort(([a], [b]) => {
      if (a === 'Uncategorized') return 1
      if (b === 'Uncategorized') return -1
      return a.localeCompare(b)
    })
  }, [channels])

  return (
    <div className="space-y-3 py-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {selectedChannels.size} of {channels.length} channel{channels.length !== 1 ? 's' : ''} selected
        </p>
        <Button variant="ghost" size="sm" className="h-7 text-xs px-2" onClick={onToggleAll}>
          {selectedChannels.size === channels.length ? 'Deselect All' : 'Select All'}
        </Button>
      </div>
      {channels.length > 0 ? (
        <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
          {byCategory.map(([category, chs]) => (
            <div key={category}>
              <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5 px-1">
                {category}
              </p>
              <div className="space-y-1">
                {chs.map((ch) => {
                  const isSelected = selectedChannels.has(ch.channel_id)
                  return (
                    <button
                      key={ch.channel_id}
                      type="button"
                      onClick={() => onToggle(ch.channel_id)}
                      className={`w-full flex items-center gap-2.5 rounded-md border px-3 py-2 text-left text-sm transition-all ${
                        isSelected ? 'border-primary/40 bg-primary/5' : 'border-transparent hover:bg-accent/50'
                      }`}
                    >
                      {isSelected ? (
                        <CheckSquare className="h-4 w-4 text-primary shrink-0" />
                      ) : (
                        <SquareIcon className="h-4 w-4 text-muted-foreground/40 shrink-0" />
                      )}
                      <Hash className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <span className="truncate">{ch.channel_name}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center">
          <Hash className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No channels found in this server.</p>
        </div>
      )}
    </div>
  )
}

// ─── Add Connector Wizard ───────────────────────────────────────────────────

function AddConnectorWizard({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: () => void
}) {
  const [platform, setPlatform] = useState<PlatformType | null>(null)
  const [step, setStep] = useState(0) // 0 = platform select
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Discord state
  const [discordForm, setDiscordForm] = useState({
    display_name: '', auth_type: 'bot', token: '',
    server_id: '', server_name: '',
  })
  const [servers, setServers] = useState<GuildInfo[]>([])
  const [channels, setChannels] = useState<ChannelInfo[]>([])
  const [selectedChannels, setSelectedChannels] = useState<Set<string>>(new Set())

  // Reddit state
  const [redditForm, setRedditForm] = useState({
    display_name: '', client_id: '', client_secret: '', user_agent: 'PhoenixTrade/1.0', subreddits: '',
  })

  // Twitter state
  const [twitterForm, setTwitterForm] = useState({
    display_name: '', bearer_token: '', accounts: '',
  })

  // Unusual Whales
  const [uwForm, setUwForm] = useState({
    display_name: '', api_key: '', symbols: '', min_premium: '',
  })

  // News API
  const [newsForm, setNewsForm] = useState({
    display_name: '', api_key: '', sources: '', symbols: '',
  })

  // Webhook
  const [webhookForm, setWebhookForm] = useState({
    display_name: '', secret_header: '', allowed_origins: '',
  })

  // Discord Webhook relay
  const [discordWebhookForm, setDiscordWebhookForm] = useState({
    display_name: '', channel_name: '',
  })

  // Alpaca
  const [alpacaForm, setAlpacaForm] = useState({
    display_name: '', api_key: '', api_secret: '', mode: 'paper' as 'paper' | 'live',
  })

  // IBKR
  const [ibkrForm, setIbkrForm] = useState({
    display_name: '', host: '127.0.0.1', port: '7497', client_id: '1',
  })

  // Tradier
  const [tradierForm, setTradierForm] = useState({
    display_name: '', api_key: '', sandbox: true,
  })

  // Robinhood
  const [robinhoodForm, setRobinhoodForm] = useState({
    display_name: '', username: '', password: '', totp_secret: '', mode: 'paper' as 'paper' | 'live',
  })

  // Market data connectors
  const [yfinanceForm, setYfinanceForm] = useState({ display_name: '' })
  const [polygonForm, setPolygonForm] = useState({ display_name: '', api_key: '' })
  const [alphaVantageForm, setAlphaVantageForm] = useState({ display_name: '', api_key: '' })
  // P15: WhatsApp + Telegram
  const [whatsappForm, setWhatsappForm] = useState({
    display_name: '', access_token: '', phone_number_id: '', verify_token: '', default_thread_id: ''
  })
  const [telegramForm, setTelegramForm] = useState({
    display_name: '', bot_token: '', default_chat_id: '', base_group_chat_id: ''
  })

  // Tags (shared across all connectors)
  const [selectedTags, setSelectedTags] = useState<string[]>([])

  useEffect(() => {
    if (open) {
      setPlatform(null)
      setStep(0)
      setError(null)
      setBusy(false)
      setDiscordForm({ display_name: '', auth_type: 'bot', token: '', server_id: '', server_name: '' })
      setServers([])
      setChannels([])
      setSelectedChannels(new Set())
      setRedditForm({ display_name: '', client_id: '', client_secret: '', user_agent: 'PhoenixTrade/1.0', subreddits: '' })
      setTwitterForm({ display_name: '', bearer_token: '', accounts: '' })
      setUwForm({ display_name: '', api_key: '', symbols: '', min_premium: '' })
      setNewsForm({ display_name: '', api_key: '', sources: '', symbols: '' })
      setWhatsappForm({ display_name: '', access_token: '', phone_number_id: '', verify_token: '', default_thread_id: '' })
      setTelegramForm({ display_name: '', bot_token: '', default_chat_id: '', base_group_chat_id: '' })
      setWebhookForm({ display_name: '', secret_header: '', allowed_origins: '' })
      setDiscordWebhookForm({ display_name: '', channel_name: '' })
      setAlpacaForm({ display_name: '', api_key: '', api_secret: '', mode: 'paper' })
      setIbkrForm({ display_name: '', host: '127.0.0.1', port: '7497', client_id: '1' })
      setTradierForm({ display_name: '', api_key: '', sandbox: true })
      setRobinhoodForm({ display_name: '', username: '', password: '', totp_secret: '', mode: 'paper' })
      setYfinanceForm({ display_name: '' })
      setPolygonForm({ display_name: '', api_key: '' })
      setAlphaVantageForm({ display_name: '', api_key: '' })
      setSelectedTags([])
    }
  }, [open])

  // Step counts per platform
  const totalSteps = (): number => {
    if (!platform) return 1
    if (platform === 'discord') return 4
    if (platform === 'discord_webhook') return 2
    if (platform === 'reddit' || platform === 'twitter') return 3
    return 2
  }

  const stepLabels = (): string[] => {
    if (!platform) return ['Platform']
    if (platform === 'discord') return ['Platform', 'Credentials', 'Server', 'Channels']
    if (platform === 'discord_webhook') return ['Platform', 'Webhook Setup']
    if (platform === 'reddit') return ['Platform', 'Credentials', 'Subreddits']
    if (platform === 'twitter') return ['Platform', 'Credentials', 'Accounts']
    return ['Platform', 'Configuration']
  }

  const stepDescription = (): string => {
    if (step === 0) return 'Choose a connector platform'
    const meta = platform ? platformMeta(platform) : null
    if (!meta) return ''
    if (platform === 'discord') {
      if (step === 1) return 'Enter your Discord credentials'
      if (step === 2) return 'Select a Discord server'
      return 'Choose channels to monitor'
    }
    if (platform === 'reddit') {
      return step === 1 ? 'Enter your Reddit API credentials' : 'Choose subreddits to monitor'
    }
    if (platform === 'twitter') {
      return step === 1 ? 'Enter your Twitter Bearer Token' : 'Choose accounts to follow'
    }
    return `Configure ${meta.label}`
  }

  // ── Discord handlers ──
  const discoverServers = async () => {
    setBusy(true); setError(null)
    try {
      const res = await api.post('/api/v2/connectors/discover-servers', {
        token: discordForm.token, auth_type: discordForm.auth_type,
      })
      setServers(res.data.servers || [])
      setStep(2)
    } catch (err: unknown) {
      setError(extractApiError(err) || 'Failed to discover servers. Check your token.')
    }
    setBusy(false)
  }

  const discoverChannels = async () => {
    setBusy(true); setError(null)
    try {
      const res = await api.post('/api/v2/connectors/discover-channels', {
        token: discordForm.token, auth_type: discordForm.auth_type, server_id: discordForm.server_id,
      })
      const discovered: ChannelInfo[] = res.data.channels || []
      setChannels(discovered)
      setSelectedChannels(new Set(discovered.map((c) => c.channel_id)))
      setStep(3)
    } catch (err: unknown) {
      setError(extractApiError(err) || 'Failed to discover channels.')
    }
    setBusy(false)
  }

  const toggleChannel = (id: string) => {
    setSelectedChannels((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const toggleAllChannels = () => {
    setSelectedChannels(
      selectedChannels.size === channels.length ? new Set() : new Set(channels.map((c) => c.channel_id))
    )
  }

  // ── Generic submit ──
  const handleSubmit = async () => {
    setBusy(true); setError(null)
    try {
      let name = ''
      let type = platform!
      let config: Record<string, unknown> = {}
      let credentials: Record<string, string> = {}

      switch (platform) {
        case 'discord': {
          name = discordForm.display_name
          credentials.bot_token = discordForm.token
          const selected = channels
            .filter((c) => selectedChannels.has(c.channel_id))
            .map((c) => ({ channel_id: c.channel_id, channel_name: c.channel_name, guild_id: c.guild_id, guild_name: c.guild_name }))
          config = { server_id: discordForm.server_id, server_name: discordForm.server_name, auth_type: discordForm.auth_type, selected_channels: selected }
          break
        }
        case 'discord_webhook': {
          name = discordWebhookForm.display_name
          type = 'discord'
          const webhookSecret = crypto.randomUUID()
          config = { auth_type: 'webhook', channel_name: discordWebhookForm.channel_name || name, webhook_secret: webhookSecret }
          break
        }
        case 'reddit': {
          name = redditForm.display_name
          credentials = { client_id: redditForm.client_id, client_secret: redditForm.client_secret, user_agent: redditForm.user_agent }
          const subs = redditForm.subreddits.split(',').map((s) => s.trim()).filter(Boolean)
          config = { subreddits: subs }
          break
        }
        case 'twitter': {
          name = twitterForm.display_name
          credentials = { bearer_token: twitterForm.bearer_token }
          const accts = twitterForm.accounts.split(',').map((s) => s.trim()).filter(Boolean)
          config = { accounts: accts }
          break
        }
        case 'unusual_whales': {
          name = uwForm.display_name
          credentials = { api_key: uwForm.api_key }
          const syms = uwForm.symbols.split(',').map((s) => s.trim()).filter(Boolean)
          config = { symbols: syms, min_premium: uwForm.min_premium ? Number(uwForm.min_premium) : null }
          break
        }
        case 'news_api': {
          name = newsForm.display_name
          credentials = { api_key: newsForm.api_key }
          const sources = newsForm.sources.split(',').map((s) => s.trim()).filter(Boolean)
          const syms = newsForm.symbols.split(',').map((s) => s.trim()).filter(Boolean)
          config = { sources, symbols: syms }
          break
        }
        case 'custom_webhook': {
          name = webhookForm.display_name
          config = { secret_header: webhookForm.secret_header || null, allowed_origins: webhookForm.allowed_origins.split(',').map((s) => s.trim()).filter(Boolean) }
          break
        }
        case 'alpaca': {
          name = alpacaForm.display_name
          credentials = { api_key: alpacaForm.api_key, api_secret: alpacaForm.api_secret }
          config = { mode: alpacaForm.mode }
          break
        }
        case 'ibkr': {
          name = ibkrForm.display_name
          config = { host: ibkrForm.host, port: Number(ibkrForm.port), client_id: Number(ibkrForm.client_id) }
          break
        }
        case 'tradier': {
          name = tradierForm.display_name
          credentials = { api_key: tradierForm.api_key }
          config = { sandbox: tradierForm.sandbox }
          break
        }
        case 'robinhood': {
          name = robinhoodForm.display_name
          credentials = { username: robinhoodForm.username, password: robinhoodForm.password, totp_secret: robinhoodForm.totp_secret }
          config = { mode: robinhoodForm.mode }
          break
        }
      }

      switch (platform) {
        case 'yfinance': {
          name = yfinanceForm.display_name
          config = { provider: 'yahoo_finance' }
          break
        }
        case 'polygon': {
          name = polygonForm.display_name
          credentials = { api_key: polygonForm.api_key }
          config = { provider: 'polygon' }
          break
        }
        case 'alphavantage': {
          name = alphaVantageForm.display_name
          credentials = { api_key: alphaVantageForm.api_key }
          config = { provider: 'alpha_vantage' }
          break
        }
        case 'whatsapp': {
          name = whatsappForm.display_name
          credentials = {
            access_token: whatsappForm.access_token,
            phone_number_id: whatsappForm.phone_number_id,
            verify_token: whatsappForm.verify_token,
          }
          config = { default_thread_id: whatsappForm.default_thread_id }
          break
        }
        case 'telegram': {
          name = telegramForm.display_name
          credentials = { bot_token: telegramForm.bot_token }
          config = {
            default_chat_id: telegramForm.default_chat_id,
            base_group_chat_id: telegramForm.base_group_chat_id,
          }
          break
        }
        default: break
      }

      await api.post('/api/v2/connectors', { name, type, config, credentials, tags: selectedTags })
      onCreated()
      onOpenChange(false)
    } catch (err: unknown) {
      setError(extractApiError(err) || 'Failed to create connector.')
    }
    setBusy(false)
  }

  // ── Can advance? ──
  const canNext = (): boolean => {
    if (step === 0) return !!platform
    switch (platform) {
      case 'discord':
        if (step === 1) return !!(discordForm.display_name && discordForm.token)
        if (step === 2) return !!discordForm.server_id
        if (step === 3) return selectedChannels.size > 0
        return false
      case 'discord_webhook':
        return !!discordWebhookForm.display_name
      case 'reddit':
        if (step === 1) return !!(redditForm.display_name && redditForm.client_id && redditForm.client_secret)
        if (step === 2) return !!redditForm.subreddits.trim()
        return false
      case 'twitter':
        if (step === 1) return !!(twitterForm.display_name && twitterForm.bearer_token)
        if (step === 2) return !!twitterForm.accounts.trim()
        return false
      case 'unusual_whales':
        return !!(uwForm.display_name && uwForm.api_key)
      case 'news_api':
        return !!(newsForm.display_name && newsForm.api_key)
      case 'custom_webhook':
        return !!webhookForm.display_name
      case 'alpaca':
        return !!(alpacaForm.display_name && alpacaForm.api_key && alpacaForm.api_secret)
      case 'ibkr':
        return !!(ibkrForm.display_name && ibkrForm.host && ibkrForm.port)
      case 'tradier':
        return !!(tradierForm.display_name && tradierForm.api_key)
      case 'robinhood':
        return !!(robinhoodForm.display_name && robinhoodForm.username && robinhoodForm.password)
      case 'yfinance':
        return !!yfinanceForm.display_name
      case 'polygon':
        return !!(polygonForm.display_name && polygonForm.api_key)
      case 'alphavantage':
        return !!(alphaVantageForm.display_name && alphaVantageForm.api_key)
      case 'whatsapp':
        return !!(whatsappForm.display_name && whatsappForm.access_token && whatsappForm.phone_number_id)
      case 'telegram':
        return !!(telegramForm.display_name && telegramForm.bot_token)
      default:
        return false
    }
  }

  const isLastStep = step === totalSteps() - 1

  const handleNext = async () => {
    if (step === 0) {
      setStep(1)
      return
    }
    if (platform === 'discord' && step === 1) { await discoverServers(); return }
    if (platform === 'discord' && step === 2) { await discoverChannels(); return }
    if (isLastStep) { await handleSubmit(); return }
    setStep((s) => s + 1)
  }

  const labels = stepLabels()
  const total = totalSteps()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {step === 0 ? 'Add Connector' : `Add ${platformMeta(platform!).label} Connector`}
          </DialogTitle>
          <DialogDescription>{stepDescription()}</DialogDescription>
        </DialogHeader>

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="shrink-0"><X className="h-4 w-4" /></button>
          </div>
        )}

        {/* Step indicator */}
        {platform && (
          <div className="flex gap-1.5 mb-1">
            {labels.map((label, i) => (
              <div key={i} className="flex-1 flex flex-col items-center gap-1">
                <div className={`w-full h-1.5 rounded-full transition-colors ${i <= step ? 'bg-primary' : 'bg-muted'}`} />
                <span className={`text-[10px] ${i === step ? 'text-primary font-medium' : 'text-muted-foreground'}`}>
                  {label}
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="flex-1 overflow-y-auto min-h-0">
          {/* Step 0: Platform selection */}
          {step === 0 && <PlatformSelectStep selected={platform} onSelect={setPlatform} />}

          {/* Discord flow */}
          {platform === 'discord' && step === 1 && (
            <DiscordCredentialsStep
              form={discordForm}
              setForm={(fn) => setDiscordForm((prev) => fn(prev))}
            />
          )}
          {platform === 'discord' && step === 2 && (
            <DiscordServerStep
              servers={servers}
              selectedId={discordForm.server_id}
              onSelect={(id, name) => setDiscordForm((f) => ({ ...f, server_id: id, server_name: name }))}
            />
          )}
          {platform === 'discord' && step === 3 && (
            <DiscordChannelStep
              channels={channels}
              selectedChannels={selectedChannels}
              onToggle={toggleChannel}
              onToggleAll={toggleAllChannels}
            />
          )}

          {/* Reddit flow */}
          {platform === 'reddit' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={redditForm.display_name} onChange={(e) => setRedditForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. WSB Monitor" />
              </div>
              <div className="space-y-1.5">
                <Label>Client ID</Label>
                <Input value={redditForm.client_id} onChange={(e) => setRedditForm((f) => ({ ...f, client_id: e.target.value }))} placeholder="Reddit app client ID" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>Client Secret</Label>
                <Input type="password" value={redditForm.client_secret} onChange={(e) => setRedditForm((f) => ({ ...f, client_secret: e.target.value }))} placeholder="Reddit app client secret" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>User Agent</Label>
                <Input value={redditForm.user_agent} onChange={(e) => setRedditForm((f) => ({ ...f, user_agent: e.target.value }))} placeholder="PhoenixTrade/1.0" />
                <p className="text-xs text-muted-foreground">Custom User-Agent string for Reddit API calls</p>
              </div>
            </div>
          )}
          {platform === 'reddit' && step === 2 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Subreddits to Monitor</Label>
                <Input
                  value={redditForm.subreddits}
                  onChange={(e) => setRedditForm((f) => ({ ...f, subreddits: e.target.value }))}
                  placeholder="wallstreetbets, stocks, options"
                />
                <p className="text-xs text-muted-foreground">Comma-separated list of subreddits (without r/)</p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {['wallstreetbets', 'stocks', 'options', 'investing', 'thetagang', 'daytrading'].map((sub) => (
                  <button
                    key={sub}
                    type="button"
                    onClick={() => {
                      const current = redditForm.subreddits.split(',').map((s) => s.trim()).filter(Boolean)
                      if (!current.includes(sub)) {
                        setRedditForm((f) => ({ ...f, subreddits: [...current, sub].join(', ') }))
                      }
                    }}
                    className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/50 hover:text-primary transition-colors"
                  >
                    r/{sub}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Twitter flow */}
          {platform === 'twitter' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={twitterForm.display_name} onChange={(e) => setTwitterForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Trading Signal Accounts" />
              </div>
              <div className="space-y-1.5">
                <Label>Bearer Token</Label>
                <Input type="password" value={twitterForm.bearer_token} onChange={(e) => setTwitterForm((f) => ({ ...f, bearer_token: e.target.value }))} placeholder="Twitter API Bearer Token" className="font-mono" />
                <p className="text-xs text-muted-foreground">From the Twitter Developer Portal → App → Keys and Tokens</p>
              </div>
            </div>
          )}
          {platform === 'twitter' && step === 2 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Accounts to Follow</Label>
                <Input
                  value={twitterForm.accounts}
                  onChange={(e) => setTwitterForm((f) => ({ ...f, accounts: e.target.value }))}
                  placeholder="unusual_whales, DeItaone, zerohedge"
                />
                <p className="text-xs text-muted-foreground">Comma-separated Twitter handles (without @)</p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {['unusual_whales', 'DeItaone', 'zerohedge', 'WallStJesus', 'jimcramer', 'elikiareturns'].map((acct) => (
                  <button
                    key={acct}
                    type="button"
                    onClick={() => {
                      const current = twitterForm.accounts.split(',').map((s) => s.trim()).filter(Boolean)
                      if (!current.includes(acct)) {
                        setTwitterForm((f) => ({ ...f, accounts: [...current, acct].join(', ') }))
                      }
                    }}
                    className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/50 hover:text-primary transition-colors"
                  >
                    @{acct}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Unusual Whales */}
          {platform === 'unusual_whales' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={uwForm.display_name} onChange={(e) => setUwForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Options Flow Scanner" />
              </div>
              <div className="space-y-1.5">
                <Label>API Key</Label>
                <Input type="password" value={uwForm.api_key} onChange={(e) => setUwForm((f) => ({ ...f, api_key: e.target.value }))} placeholder="Your Unusual Whales API key" className="font-mono" />
                <p className="text-xs text-muted-foreground">Get your API key from unusualwhales.com/account</p>
              </div>
              <div className="space-y-1.5">
                <Label>Symbol Filter (optional)</Label>
                <Input value={uwForm.symbols} onChange={(e) => setUwForm((f) => ({ ...f, symbols: e.target.value }))} placeholder="SPY, AAPL, TSLA" />
                <p className="text-xs text-muted-foreground">Comma-separated ticker symbols. Leave empty to monitor all.</p>
              </div>
              <div className="space-y-1.5">
                <Label>Min Premium Filter (optional)</Label>
                <Input type="number" value={uwForm.min_premium} onChange={(e) => setUwForm((f) => ({ ...f, min_premium: e.target.value }))} placeholder="e.g. 100000" />
                <p className="text-xs text-muted-foreground">Only show options orders above this premium ($)</p>
              </div>
            </div>
          )}

          {/* News API */}
          {platform === 'news_api' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={newsForm.display_name} onChange={(e) => setNewsForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Financial Headlines" />
              </div>
              <div className="space-y-1.5">
                <Label>API Key</Label>
                <Input type="password" value={newsForm.api_key} onChange={(e) => setNewsForm((f) => ({ ...f, api_key: e.target.value }))} placeholder="Your newsapi.org API key" className="font-mono" />
                <p className="text-xs text-muted-foreground">Get a free key from newsapi.org</p>
              </div>
              <div className="space-y-1.5">
                <Label>News Sources (optional)</Label>
                <Input value={newsForm.sources} onChange={(e) => setNewsForm((f) => ({ ...f, sources: e.target.value }))} placeholder="bloomberg, reuters, cnbc" />
                <p className="text-xs text-muted-foreground">Comma-separated source IDs. Leave empty for all sources.</p>
              </div>
              <div className="space-y-1.5">
                <Label>Keyword Filter (optional)</Label>
                <Input value={newsForm.symbols} onChange={(e) => setNewsForm((f) => ({ ...f, symbols: e.target.value }))} placeholder="AAPL, earnings, Fed" />
                <p className="text-xs text-muted-foreground">Comma-separated keywords to filter articles</p>
              </div>
            </div>
          )}

          {/* P15: WhatsApp */}
          {platform === 'whatsapp' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={whatsappForm.display_name} onChange={(e) => setWhatsappForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Trade Alerts WhatsApp" />
              </div>
              <div className="space-y-1.5">
                <Label>Phone Number ID</Label>
                <Input value={whatsappForm.phone_number_id} onChange={(e) => setWhatsappForm((f) => ({ ...f, phone_number_id: e.target.value }))} placeholder="From Meta developer console" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>Access Token</Label>
                <Input type="password" value={whatsappForm.access_token} onChange={(e) => setWhatsappForm((f) => ({ ...f, access_token: e.target.value }))} placeholder="Meta Cloud API access token" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>Webhook Verify Token</Label>
                <Input value={whatsappForm.verify_token} onChange={(e) => setWhatsappForm((f) => ({ ...f, verify_token: e.target.value }))} placeholder="Shared secret for /webhook/whatsapp" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>Default Thread / Phone Number</Label>
                <Input value={whatsappForm.default_thread_id} onChange={(e) => setWhatsappForm((f) => ({ ...f, default_thread_id: e.target.value }))} placeholder="+14155551234 or group ID" />
              </div>
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-400">
                ⚠ Meta restricts programmatic group creation. Create WhatsApp groups manually, invite the bot, then tag each group to an agent. Outbound messages auto-prepend [agent:name].
              </div>
            </div>
          )}

          {/* P15: Telegram */}
          {platform === 'telegram' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={telegramForm.display_name} onChange={(e) => setTelegramForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Phoenix Telegram Bot" />
              </div>
              <div className="space-y-1.5">
                <Label>Bot Token</Label>
                <Input type="password" value={telegramForm.bot_token} onChange={(e) => setTelegramForm((f) => ({ ...f, bot_token: e.target.value }))} placeholder="From @BotFather" className="font-mono" />
                <p className="text-xs text-muted-foreground">Message @BotFather on Telegram to create a new bot.</p>
              </div>
              <div className="space-y-1.5">
                <Label>Default Chat ID</Label>
                <Input value={telegramForm.default_chat_id} onChange={(e) => setTelegramForm((f) => ({ ...f, default_chat_id: e.target.value }))} placeholder="-1001234567890 or @channelname" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>Base Group Chat ID (optional)</Label>
                <Input value={telegramForm.base_group_chat_id} onChange={(e) => setTelegramForm((f) => ({ ...f, base_group_chat_id: e.target.value }))} placeholder="Supergroup where bot generates per-agent invite links" className="font-mono" />
              </div>
              <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-xs text-sky-400">
                Telegram supports auto-generated per-agent invite links via `createChatInviteLink`. Set the base group above and Phoenix will mint one link per new agent.
              </div>
            </div>
          )}

          {/* Webhook */}
          {platform === 'custom_webhook' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={webhookForm.display_name} onChange={(e) => setWebhookForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. TradingView Alerts" />
              </div>
              <div className="space-y-1.5">
                <Label>Secret Header (optional)</Label>
                <Input type="password" value={webhookForm.secret_header} onChange={(e) => setWebhookForm((f) => ({ ...f, secret_header: e.target.value }))} placeholder="A secret to validate incoming requests" className="font-mono" />
                <p className="text-xs text-muted-foreground">If set, incoming requests must include this value in X-Webhook-Secret header</p>
              </div>
              <div className="space-y-1.5">
                <Label>Allowed Origins (optional)</Label>
                <Input value={webhookForm.allowed_origins} onChange={(e) => setWebhookForm((f) => ({ ...f, allowed_origins: e.target.value }))} placeholder="https://tradingview.com, https://alerts.example.com" />
                <p className="text-xs text-muted-foreground">Comma-separated origin URLs. Leave empty to allow all.</p>
              </div>
              <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-blue-400">
                A unique webhook URL will be generated after creation. No API keys required — this is a passive receiver.
              </div>
            </div>
          )}

          {/* Discord Webhook */}
          {platform === 'discord_webhook' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input
                  value={discordWebhookForm.display_name}
                  onChange={(e) => setDiscordWebhookForm((f) => ({ ...f, display_name: e.target.value }))}
                  placeholder="e.g. Trading Signals (Webhook)"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Channel Name (optional)</Label>
                <Input
                  value={discordWebhookForm.channel_name}
                  onChange={(e) => setDiscordWebhookForm((f) => ({ ...f, channel_name: e.target.value }))}
                  placeholder="e.g. #trading-alerts"
                />
              </div>
              <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-3 space-y-2">
                <p className="text-sm font-medium text-indigo-400">No bot or token needed</p>
                <p className="text-xs text-muted-foreground">
                  After creation, you&apos;ll get a unique webhook URL. Have the Discord server admin set up a relay (e.g. via <strong>Zapier</strong>, <strong>Make</strong>, or a simple forwarding bot) that POSTs messages to this URL.
                </p>
                <p className="text-xs text-muted-foreground">
                  Messages arrive the same way as the Bot connector — via the channel_messages table and Redis streams. Zero direct Discord API calls from Phoenix.
                </p>
              </div>
            </div>
          )}

          {/* Alpaca */}
          {platform === 'alpaca' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={alpacaForm.display_name} onChange={(e) => setAlpacaForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Alpaca Paper Trading" />
              </div>
              <div className="space-y-1.5">
                <Label>API Key</Label>
                <Input type="password" value={alpacaForm.api_key} onChange={(e) => setAlpacaForm((f) => ({ ...f, api_key: e.target.value }))} placeholder="APCA-API-KEY-ID" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>API Secret</Label>
                <Input type="password" value={alpacaForm.api_secret} onChange={(e) => setAlpacaForm((f) => ({ ...f, api_secret: e.target.value }))} placeholder="APCA-API-SECRET-KEY" className="font-mono" />
              </div>
              <div className="space-y-2">
                <Label>Trading Mode</Label>
                <div className="flex gap-3">
                  {(['paper', 'live'] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setAlpacaForm((f) => ({ ...f, mode: m }))}
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-colors ${
                        alpacaForm.mode === m
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border text-muted-foreground hover:border-primary/50'
                      }`}
                    >
                      {m === 'paper' ? '📝 Paper' : '💰 Live'}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {alpacaForm.mode === 'paper'
                    ? 'Paper trading uses simulated money — no risk.'
                    : '⚠️ Live trading uses real money. Ensure you understand the risks.'}
                </p>
              </div>
            </div>
          )}

          {/* IBKR */}
          {platform === 'ibkr' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={ibkrForm.display_name} onChange={(e) => setIbkrForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. IBKR Gateway" />
              </div>
              <div className="space-y-1.5">
                <Label>TWS/Gateway Host</Label>
                <Input value={ibkrForm.host} onChange={(e) => setIbkrForm((f) => ({ ...f, host: e.target.value }))} placeholder="127.0.0.1" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>Port</Label>
                <Input type="number" value={ibkrForm.port} onChange={(e) => setIbkrForm((f) => ({ ...f, port: e.target.value }))} placeholder="7497" className="font-mono" />
                <p className="text-xs text-muted-foreground">7497 for TWS paper, 7496 for TWS live, 4001/4002 for IB Gateway</p>
              </div>
              <div className="space-y-1.5">
                <Label>Client ID</Label>
                <Input type="number" value={ibkrForm.client_id} onChange={(e) => setIbkrForm((f) => ({ ...f, client_id: e.target.value }))} placeholder="1" className="font-mono" />
                <p className="text-xs text-muted-foreground">Must be unique per TWS connection</p>
              </div>
              <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-blue-400">
                IBKR connects via your local TWS or IB Gateway — no API keys are sent over the network.
              </div>
            </div>
          )}

          {/* Tradier */}
          {platform === 'tradier' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={tradierForm.display_name} onChange={(e) => setTradierForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Tradier Options" />
              </div>
              <div className="space-y-1.5">
                <Label>API Key</Label>
                <Input type="password" value={tradierForm.api_key} onChange={(e) => setTradierForm((f) => ({ ...f, api_key: e.target.value }))} placeholder="Tradier access token" className="font-mono" />
                <p className="text-xs text-muted-foreground">From Tradier Developer Portal → API Access</p>
              </div>
              <div className="space-y-2">
                <Label>Environment</Label>
                <div className="flex gap-3">
                  {[true, false].map((isSandbox) => (
                    <button
                      key={String(isSandbox)}
                      type="button"
                      onClick={() => setTradierForm((f) => ({ ...f, sandbox: isSandbox }))}
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-colors ${
                        tradierForm.sandbox === isSandbox
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border text-muted-foreground hover:border-primary/50'
                      }`}
                    >
                      {isSandbox ? '🧪 Sandbox' : '🚀 Production'}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {tradierForm.sandbox
                    ? 'Sandbox uses simulated market data and delayed quotes.'
                    : '⚠️ Production connects to real markets.'}
                </p>
              </div>
            </div>
          )}

          {/* Robinhood */}
          {platform === 'robinhood' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={robinhoodForm.display_name} onChange={(e) => setRobinhoodForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Robinhood Trading" />
              </div>
              <div className="space-y-1.5">
                <Label>Username / Email</Label>
                <Input value={robinhoodForm.username} onChange={(e) => setRobinhoodForm((f) => ({ ...f, username: e.target.value }))} placeholder="your@email.com" />
              </div>
              <div className="space-y-1.5">
                <Label>Password</Label>
                <Input type="password" value={robinhoodForm.password} onChange={(e) => setRobinhoodForm((f) => ({ ...f, password: e.target.value }))} placeholder="Robinhood password" className="font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label>TOTP Secret (optional)</Label>
                <Input type="password" value={robinhoodForm.totp_secret} onChange={(e) => setRobinhoodForm((f) => ({ ...f, totp_secret: e.target.value }))} placeholder="MFA TOTP secret (base32)" className="font-mono" />
                <p className="text-xs text-muted-foreground">Required if you have 2FA enabled. This is the secret key, not the 6-digit code.</p>
              </div>
              <div className="space-y-2">
                <Label>Mode</Label>
                <div className="flex gap-3">
                  {(['paper', 'live'] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setRobinhoodForm((f) => ({ ...f, mode }))}
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-colors ${
                        robinhoodForm.mode === mode
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border text-muted-foreground hover:border-primary/50'
                      }`}
                    >
                      {mode === 'paper' ? 'Paper Trading' : 'Live Trading'}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {robinhoodForm.mode === 'paper'
                    ? 'Paper mode simulates trades without real money.'
                    : 'Live mode executes real trades on Robinhood.'}
                </p>
              </div>
              <div className="rounded-lg border border-green-500/20 bg-green-500/5 p-3 text-xs text-green-400">
                Credentials are encrypted at rest with Fernet encryption. The agent uses the Robinhood MCP server for trade execution.
              </div>
            </div>
          )}

          {/* Yahoo Finance */}
          {platform === 'yfinance' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={yfinanceForm.display_name} onChange={(e) => setYfinanceForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Yahoo Finance OHLCV" />
              </div>
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs text-emerald-600 dark:text-emerald-400">
                Yahoo Finance requires no API key. Provides free historical OHLCV data, options chains, and fundamental data.
              </div>
            </div>
          )}

          {/* Polygon.io */}
          {platform === 'polygon' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={polygonForm.display_name} onChange={(e) => setPolygonForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Polygon Market Data" />
              </div>
              <div className="space-y-1.5">
                <Label>API Key</Label>
                <Input type="password" value={polygonForm.api_key} onChange={(e) => setPolygonForm((f) => ({ ...f, api_key: e.target.value }))} placeholder="Your Polygon.io API key" className="font-mono" />
                <p className="text-xs text-muted-foreground">Get a free key from polygon.io</p>
              </div>
            </div>
          )}

          {/* Alpha Vantage */}
          {platform === 'alphavantage' && step === 1 && (
            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label>Display Name</Label>
                <Input value={alphaVantageForm.display_name} onChange={(e) => setAlphaVantageForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="e.g. Alpha Vantage Indicators" />
              </div>
              <div className="space-y-1.5">
                <Label>API Key</Label>
                <Input type="password" value={alphaVantageForm.api_key} onChange={(e) => setAlphaVantageForm((f) => ({ ...f, api_key: e.target.value }))} placeholder="Your Alpha Vantage API key" className="font-mono" />
                <p className="text-xs text-muted-foreground">Get a free key from alphavantage.co</p>
              </div>
            </div>
          )}

          {/* Tags section — shown for all platforms at step 1+ */}
          {platform && step >= 1 && (
            <div className="space-y-2 pt-3 border-t mt-3">
              <Label>Tags</Label>
              <p className="text-xs text-muted-foreground">Categorize this connector so agents can filter by type</p>
              <div className="flex flex-wrap gap-1.5">
                {SUGGESTED_TAGS.map((tag) => {
                  const active = selectedTags.includes(tag)
                  return (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => setSelectedTags((prev) =>
                        active ? prev.filter((t) => t !== tag) : [...prev, tag]
                      )}
                      className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                        active
                          ? 'border-primary bg-primary/10 text-primary font-medium'
                          : 'border-border text-muted-foreground hover:border-primary/50'
                      }`}
                    >
                      {tag}
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          {step > 0 && (
            <Button variant="outline" onClick={() => setStep((s) => s - 1)}>
              <ChevronLeft className="mr-1 h-4 w-4" /> Back
            </Button>
          )}
          <div className="flex-1" />
          <Button onClick={handleNext} disabled={!canNext() || busy}>
            {busy && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
            {busy
              ? step === 0 ? 'Loading…' : 'Processing…'
              : isLastStep && step > 0
                ? 'Create Connector'
                : 'Next'}
            {!busy && !isLastStep && <ChevronRight className="ml-1 h-4 w-4" />}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Connector Card Helpers ─────────────────────────────────────────────────

function connectorSummary(c: Connector): string {
  const cfg = c.config || {}
  switch (c.type) {
    case 'discord': {
      if ((cfg.auth_type as string) === 'webhook') return 'Webhook relay'
      const chCount = Array.isArray(cfg.selected_channels) ? (cfg.selected_channels as unknown[]).length : 0
      return cfg.server_name ? `${cfg.server_name} · ${chCount} ch` : `${chCount} channels`
    }
    case 'reddit': {
      const subs = Array.isArray(cfg.subreddits) ? (cfg.subreddits as string[]) : []
      return subs.length ? subs.map((s) => `r/${s}`).slice(0, 3).join(', ') + (subs.length > 3 ? '…' : '') : 'Reddit'
    }
    case 'twitter': {
      const accts = Array.isArray(cfg.accounts) ? (cfg.accounts as string[]) : []
      return accts.length ? accts.map((a) => `@${a}`).slice(0, 3).join(', ') + (accts.length > 3 ? '…' : '') : 'Twitter'
    }
    case 'unusual_whales': {
      const syms = Array.isArray(cfg.symbols) ? (cfg.symbols as string[]) : []
      return syms.length ? syms.join(', ') : 'All symbols'
    }
    case 'news_api': {
      const src = Array.isArray(cfg.sources) ? (cfg.sources as string[]) : []
      return src.length ? src.join(', ') : 'All sources'
    }
    case 'custom_webhook':
      return 'Passive webhook receiver'
    case 'alpaca':
      return `${(cfg.mode as string) === 'live' ? 'Live' : 'Paper'} trading`
    case 'ibkr':
      return `${cfg.host || '127.0.0.1'}:${cfg.port || 7497}`
    case 'tradier':
      return cfg.sandbox ? 'Sandbox' : 'Production'
    case 'yfinance':
      return 'Free OHLCV + options data'
    case 'polygon':
      return 'Real-time market data'
    case 'alphavantage':
      return 'Technical indicators + OHLCV'
    default:
      return c.type
  }
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function ConnectorsPage() {
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Connector | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{
    id: string
    connection_status: string
    detail: string
  } | null>(null)

  const { data: connectors = [] } = useQuery<Connector[]>({
    queryKey: ['connectors'],
    queryFn: async () => {
      const res = await api.get('/api/v2/connectors')
      return res.data
    },
    refetchInterval: 15000,
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => { await api.delete(`/api/v2/connectors/${id}`) },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connectors'] })
      setDeleteTarget(null)
    },
  })

  const handleTest = async (id: string) => {
    setTestingId(id)
    setTestResult(null)
    try {
      const res = await api.post(`/api/v2/connectors/${id}/test`)
      setTestResult({ id, ...res.data })
      qc.invalidateQueries({ queryKey: ['connectors'] })
    } catch {
      setTestResult({ id, connection_status: 'ERROR', detail: 'Test request failed' })
    }
    setTestingId(null)
  }

  const statusDot = (s: string) => {
    const u = s.toUpperCase()
    if (['CONNECTED', 'ONLINE'].includes(u)) return 'bg-emerald-500'
    if (u === 'ERROR') return 'bg-red-500'
    return 'bg-zinc-400'
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={Plug} title="Connectors" description="Data source and broker connectors">
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="h-4 w-4 mr-2" /> Add Connector
        </Button>
      </PageHeader>

      {testResult && (
        <div
          className={`rounded-lg border p-3 text-sm flex items-center justify-between ${
            testResult.connection_status === 'connected'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
              : 'border-red-500/30 bg-red-500/10 text-red-400'
          }`}
        >
          <span>
            {testResult.connection_status === 'connected'
              ? `Connected successfully${testResult.detail ? ` — ${testResult.detail}` : ''}`
              : `Connection failed: ${testResult.detail}`}
          </span>
          <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setTestResult(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {connectors.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 p-12 text-center">
          <Plug className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
          <p className="text-muted-foreground mb-1">No connectors configured</p>
          <p className="text-sm text-muted-foreground/70 mb-4">
            Connect data sources and brokers to start trading.
          </p>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 mr-1.5" /> Add Connector
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {connectors.map((c) => {
            const meta = platformMeta(c.type)
            const Icon = meta.icon
            return (
              <div
                key={c.id}
                className="group relative rounded-xl border border-white/10 bg-card p-5 transition-colors hover:bg-white/[0.02]"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="relative">
                      <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${meta.bgColor}`}>
                        <Icon className={`h-5 w-5 ${meta.color}`} />
                      </div>
                      <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-card ${statusDot(c.status)}`} />
                    </div>
                    <div className="min-w-0">
                      <h3 className="font-semibold text-sm truncate">{c.name}</h3>
                      <p className="text-xs text-muted-foreground truncate">{connectorSummary(c)}</p>
                    </div>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity">
                        <MoreVertical className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => handleTest(c.id)} disabled={testingId === c.id}>
                        {testingId === c.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Wifi className="mr-2 h-4 w-4" />}
                        Test Connection
                      </DropdownMenuItem>
                      <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setDeleteTarget(c)}>
                        <Trash2 className="mr-2 h-4 w-4" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                <div className="mt-4 flex items-center gap-2 flex-wrap">
                  <StatusBadge status={c.status} />
                  <Badge variant="outline" className={`text-xs ${meta.color}`}>
                    {meta.label}
                  </Badge>
                  {(c.tags || []).map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
                      {tag}
                    </Badge>
                  ))}
                </div>

                {c.last_connected_at && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    Last connected: {new Date(c.last_connected_at).toLocaleString()}
                  </p>
                )}
                {c.error_message && (
                  <p className="mt-1 text-xs text-red-400 truncate" title={c.error_message}>
                    {c.error_message}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}

      <AddConnectorWizard
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={() => qc.invalidateQueries({ queryKey: ['connectors'] })}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null) }}
        title="Delete Connector"
        description={`Are you sure you want to delete "${deleteTarget?.name}"? This will remove the connector and all its configuration.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={async () => { if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id) }}
      />
    </div>
  )
}
