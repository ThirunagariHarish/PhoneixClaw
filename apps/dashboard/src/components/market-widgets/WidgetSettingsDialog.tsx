/**
 * Widget settings dialog: configure symbol + link group assignment (MCP-3).
 */
import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import TickerSearch from './TickerSearch'
import { type LinkGroup, LINK_GROUP_COLORS, LINK_GROUP_LABELS } from '@/context/SymbolLinkContext'

interface Props {
  widgetId: string
  widgetLabel: string
  currentSymbol: string
  currentLinkGroup?: LinkGroup | null
  onSave: (symbol: string) => void
  onLinkGroupChange?: (group: LinkGroup | null) => void
  onClose: () => void
}

const LINK_GROUPS: (LinkGroup | null)[] = [null, 'A', 'B', 'C']

export default function WidgetSettingsDialog({
  widgetId: _widgetId,
  widgetLabel,
  currentSymbol,
  currentLinkGroup,
  onSave,
  onLinkGroupChange,
  onClose,
}: Props) {
  const [symbol, setSymbol] = useState(currentSymbol)
  const [linkGroup, setLinkGroup] = useState<LinkGroup | null>(currentLinkGroup ?? null)

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-sm">Configure {widgetLabel}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <TickerSearch
            value={symbol}
            onChange={setSymbol}
            label="Symbol / Ticker"
            placeholder="Search or type a ticker..."
          />

          {/* MCP-3: Link Group assignment */}
          {onLinkGroupChange && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Link Group</label>
              <p className="text-[10px] text-muted-foreground">
                Widgets in the same group share a symbol.
              </p>
              <div className="flex items-center gap-2">
                {LINK_GROUPS.map((g) => {
                  const isActive = linkGroup === g
                  return (
                    <button
                      key={g ?? 'none'}
                      type="button"
                      onClick={() => setLinkGroup(g)}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-xs transition-all ${
                        isActive
                          ? 'border-primary bg-primary/10 font-medium'
                          : 'border-border hover:border-primary/40'
                      }`}
                    >
                      {g ? (
                        <>
                          <span
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: LINK_GROUP_COLORS[g] }}
                          />
                          {LINK_GROUP_LABELS[g]}
                        </>
                      ) : (
                        'None'
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs border rounded hover:bg-muted/50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                onSave(symbol)
                if (onLinkGroupChange) {
                  onLinkGroupChange(linkGroup)
                }
              }}
              className="px-3 py-1.5 text-xs bg-purple-500 text-white rounded hover:bg-purple-600 transition-colors"
            >
              Apply
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
