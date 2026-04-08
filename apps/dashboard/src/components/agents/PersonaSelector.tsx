/**
 * PersonaSelector — displays the 6 analyst personas as selectable cards.
 * Used in the agent creation wizard when type='analyst'.
 */

export interface PersonaOption {
  id: string
  name: string
  emoji: string
  description: string
  min_confidence_threshold: number
  preferred_timeframes: string[]
  stop_loss_style: string
  entry_style: string
  tool_weights: Record<string, number>
}

interface PersonaSelectorProps {
  personas: PersonaOption[]
  selected: string
  onChange: (personaId: string) => void
  loading?: boolean
}

export function PersonaSelector({ personas, selected, onChange, loading }: PersonaSelectorProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-20 rounded-lg bg-muted animate-pulse" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Choose a trading persona that defines how the analyst evaluates signals.
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {personas.map((persona) => (
          <button
            key={persona.id}
            type="button"
            onClick={() => onChange(persona.id)}
            className={`w-full text-left rounded-lg border px-3 py-2.5 transition-colors ${
              selected === persona.id
                ? 'border-primary bg-primary/10 ring-1 ring-primary/30'
                : 'border-border hover:border-primary/50 hover:bg-muted/50'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-base">{persona.emoji}</span>
              <span className="text-sm font-medium truncate">{persona.name}</span>
              <span className="ml-auto text-xs text-muted-foreground shrink-0">
                {persona.min_confidence_threshold}%+ conf
              </span>
            </div>
            <p className="text-xs text-muted-foreground line-clamp-2">{persona.description}</p>
            <div className="flex gap-1 mt-1.5 flex-wrap">
              {persona.preferred_timeframes.slice(0, 3).map((tf) => (
                <span
                  key={tf}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                >
                  {tf}
                </span>
              ))}
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground capitalize">
                {persona.stop_loss_style} SL
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
