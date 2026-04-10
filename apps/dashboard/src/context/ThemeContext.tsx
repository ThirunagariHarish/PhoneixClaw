/**
 * Theme (dark/light) context. Persisted in localStorage.
 * Reference: Milestones.md M1.4, ImplementationPlan.md.
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type Theme = 'dark' | 'light' | 'system'

interface ThemeContextValue {
  theme: Theme
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

const STORAGE_KEY = 'phoenix-v2-theme'

function readStoredTheme(defaultTheme: Theme): Theme {
  if (typeof window === 'undefined') return defaultTheme
  try {
    const ls = window.localStorage
    if (ls && typeof ls.getItem === 'function') {
      const raw = ls.getItem(STORAGE_KEY)
      if (raw === 'dark' || raw === 'light' || raw === 'system') return raw
    }
  } catch {
    /* private mode / test env */
  }
  return defaultTheme
}

function persistTheme(t: Theme): void {
  try {
    const ls = window.localStorage
    if (ls && typeof ls.setItem === 'function') ls.setItem(STORAGE_KEY, t)
  } catch {
    /* ignore */
  }
}

export function ThemeProvider({
  children,
  defaultTheme = 'dark',
}: {
  children: ReactNode
  defaultTheme?: Theme
}) {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme(defaultTheme))

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('light', 'dark')
    if (theme === 'system') {
      const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
      root.classList.add(systemTheme)
      return
    }
    root.classList.add(theme)
  }, [theme])

  const value: ThemeContextValue = {
    theme,
    setTheme: (t) => {
      persistTheme(t)
      setTheme(t)
    },
  }

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
