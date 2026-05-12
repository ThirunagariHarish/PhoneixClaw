import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, RotateCw, Trash2, Eye, EyeOff, KeyRound } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/lib/api'
import { Button } from '@/components/ui/button'

// One entry per external provider we support storing keys for.
// Adding a new provider here is the only change needed when a new integration
// lands — backend POST /api/v2/admin/api-keys accepts any (provider, name) pair.
const PROVIDERS: Array<{
  provider: string
  name: string
  label: string
  description: string
  signupUrl?: string
}> = [
  {
    provider: 'tiingo',
    name: 'tiingo_api_key',
    label: 'Tiingo',
    description:
      'Daily / IEX intraday OHLCV used by the backtest pipeline. Free tier: 1000 req/hr, 20y daily.',
    signupUrl: 'https://www.tiingo.com/account/api/token',
  },
  {
    provider: 'polygon',
    name: 'polygon_api_key',
    label: 'Polygon',
    description: 'Alternative market data provider. Optional fallback to Tiingo.',
    signupUrl: 'https://polygon.io/dashboard/api-keys',
  },
  {
    provider: 'anthropic',
    name: 'anthropic_api_key',
    label: 'Anthropic',
    description:
      'Claude API for agent reasoning, LLM pattern discovery, narrative analysis. Required for live agents.',
    signupUrl: 'https://console.anthropic.com/settings/keys',
  },
  {
    provider: 'openai',
    name: 'openai_api_key',
    label: 'OpenAI',
    description: 'GPT models for sentiment analysis and supplementary research.',
    signupUrl: 'https://platform.openai.com/api-keys',
  },
  {
    provider: 'finnhub',
    name: 'finnhub_api_key',
    label: 'Finnhub',
    description: 'Real-time quotes, earnings calendar, news sentiment.',
    signupUrl: 'https://finnhub.io/dashboard',
  },
  {
    provider: 'unusual_whales',
    name: 'unusual_whales_api_key',
    label: 'Unusual Whales',
    description: 'Options flow, dark pool prints, gamma exposure data.',
    signupUrl: 'https://unusualwhales.com/api',
  },
]

interface StoredKey {
  id: string
  name: string
  key_type: string
  provider: string
  masked_value: string
  is_active: boolean
  last_tested_at: string | null
}

export default function IntegrationsPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<string | null>(null) // provider currently being edited
  const [secretInput, setSecretInput] = useState('')
  const [reveal, setReveal] = useState(false)

  const { data: keys = [], isLoading } = useQuery({
    queryKey: ['admin-api-keys'],
    queryFn: () => api.get<StoredKey[]>('/api/v2/admin/api-keys').then((r) => r.data),
  })

  const upsertMutation = useMutation({
    mutationFn: (payload: { provider: string; name: string; secret: string }) =>
      api
        .post('/api/v2/admin/api-keys', {
          provider: payload.provider,
          name: payload.name,
          key_type: 'integration',
          secret: payload.secret,
        })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success('Key saved')
      setEditing(null)
      setSecretInput('')
      setReveal(false)
      queryClient.invalidateQueries({ queryKey: ['admin-api-keys'] })
    },
    onError: (e: unknown) => {
      const msg = e instanceof Error ? e.message : 'Failed to save key'
      toast.error(msg)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api.delete(`/api/v2/admin/api-keys/${id}`).then((r) => r.data),
    onSuccess: () => {
      toast.success('Key removed')
      queryClient.invalidateQueries({ queryKey: ['admin-api-keys'] })
    },
  })

  const byProvider: Record<string, StoredKey | undefined> = {}
  for (const k of keys) {
    if (k.provider) byProvider[k.provider] = k
  }

  return (
    <div className="container mx-auto px-4 py-6 space-y-6">
      <div className="flex items-center gap-3">
        <KeyRound className="h-6 w-6 text-indigo-400" />
        <div>
          <h1 className="text-2xl font-semibold">Integrations</h1>
          <p className="text-sm text-muted-foreground">
            API keys for external data and AI providers. Stored encrypted; never displayed in plaintext after save.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : (
        <div className="grid gap-3">
          {PROVIDERS.map((p) => {
            const stored = byProvider[p.provider]
            const isConfigured = !!stored
            const isEditing = editing === p.provider
            return (
              <div
                key={p.provider}
                className="border border-border rounded-xl bg-card p-4 flex flex-col gap-3"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium">{p.label}</h3>
                      <span
                        className={
                          'text-xs px-2 py-0.5 rounded-full ' +
                          (isConfigured
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-slate-500/10 text-slate-400 border border-slate-500/20')
                        }
                      >
                        {isConfigured ? 'Configured' : 'Not set'}
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">{p.description}</p>
                    {isConfigured && (
                      <div className="text-xs font-mono text-muted-foreground mt-2">
                        {stored!.masked_value}
                        {stored!.last_tested_at && (
                          <span className="ml-2">
                            · last tested {new Date(stored!.last_tested_at).toLocaleString()}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {p.signupUrl && (
                      <a
                        href={p.signupUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-indigo-400 hover:text-indigo-300 underline"
                      >
                        Get key →
                      </a>
                    )}
                    {!isEditing ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setEditing(p.provider)
                          setSecretInput('')
                          setReveal(false)
                        }}
                      >
                        {isConfigured ? (
                          <>
                            <RotateCw className="h-3.5 w-3.5 mr-1" /> Rotate
                          </>
                        ) : (
                          <>
                            <Plus className="h-3.5 w-3.5 mr-1" /> Add
                          </>
                        )}
                      </Button>
                    ) : null}
                    {isConfigured && !isEditing && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (confirm(`Remove ${p.label} key?`)) {
                            deleteMutation.mutate(stored!.id)
                          }
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
                {isEditing && (
                  <div className="flex items-center gap-2 pt-2 border-t border-border">
                    <div className="relative flex-1">
                      <input
                        type={reveal ? 'text' : 'password'}
                        value={secretInput}
                        onChange={(e) => setSecretInput(e.target.value)}
                        placeholder={`Paste ${p.label} API key`}
                        className="w-full px-3 py-2 pr-10 text-sm bg-slate-900/50 border border-border rounded-md font-mono"
                        autoFocus
                      />
                      <button
                        type="button"
                        onClick={() => setReveal((r) => !r)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      >
                        {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                    <Button
                      size="sm"
                      disabled={!secretInput.trim() || upsertMutation.isPending}
                      onClick={() =>
                        upsertMutation.mutate({
                          provider: p.provider,
                          name: p.name,
                          secret: secretInput.trim(),
                        })
                      }
                    >
                      {upsertMutation.isPending ? 'Saving…' : 'Save'}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setEditing(null)
                        setSecretInput('')
                        setReveal(false)
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="text-xs text-muted-foreground border-t border-border pt-4">
        <strong>Note:</strong> Keys are stored encrypted in the <code>api_keys</code> table and decrypted on-demand
        by services. Env-var keys (set via SealedSecret) take precedence; this UI is for runtime rotations without
        a redeploy. A new key takes effect within ~60 seconds (in-process cache TTL).
      </div>
    </div>
  )
}
