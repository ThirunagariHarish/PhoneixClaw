/**
 * SymbolLinkContext: MCP-3 — Symbol linking groups.
 * Widgets assigned to the same color group (A=red, B=blue, C=green)
 * share a symbol. Changing the symbol in one widget updates all others.
 */
import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react'

export type LinkGroup = 'A' | 'B' | 'C'

export const LINK_GROUP_COLORS: Record<LinkGroup, string> = {
  A: '#ef4444', // red
  B: '#3b82f6', // blue
  C: '#22c55e', // green
}

export const LINK_GROUP_LABELS: Record<LinkGroup, string> = {
  A: 'Red',
  B: 'Blue',
  C: 'Green',
}

interface SymbolLinkState {
  /** Map group -> current symbol */
  groupSymbols: Record<LinkGroup, string>
  /** Update the symbol for a link group */
  setGroupSymbol: (group: LinkGroup, symbol: string) => void
  /** Get the symbol for a group (defaults to SPY) */
  getGroupSymbol: (group: LinkGroup) => string
}

const SymbolLinkContext = createContext<SymbolLinkState | null>(null)

export function SymbolLinkProvider({ children }: { children: ReactNode }) {
  const [groupSymbols, setGroupSymbols] = useState<Record<LinkGroup, string>>({
    A: 'SPY',
    B: 'AAPL',
    C: 'QQQ',
  })

  const setGroupSymbol = useCallback((group: LinkGroup, symbol: string) => {
    setGroupSymbols((prev) => ({ ...prev, [group]: symbol }))
  }, [])

  const getGroupSymbol = useCallback(
    (group: LinkGroup) => groupSymbols[group] ?? 'SPY',
    [groupSymbols],
  )

  const value = useMemo(
    () => ({ groupSymbols, setGroupSymbol, getGroupSymbol }),
    [groupSymbols, setGroupSymbol, getGroupSymbol],
  )

  return <SymbolLinkContext.Provider value={value}>{children}</SymbolLinkContext.Provider>
}

export function useSymbolLink() {
  const ctx = useContext(SymbolLinkContext)
  if (!ctx) throw new Error('useSymbolLink must be used within SymbolLinkProvider')
  return ctx
}
