/**
 * Auth context: login, logout, token. M1.3 wired to Phoenix v2 API.
 * Reference: Milestones.md M1.4, ImplementationPlan.md M1.3.
 */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'

const TOKEN_KEY = 'phoenix-v2-token'
const API_BASE = import.meta.env.VITE_API_URL ?? ''

export interface UserProfile {
  id: string
  email: string
  name: string | null
  role: string
}

interface AuthContextValue {
  token: string | null
  user: UserProfile | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  isAuthenticated: boolean
  error: string | null
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function fetchMe(token: string): Promise<UserProfile> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Session invalid')
  const data = await res.json()
  return {
    id: data.id,
    email: data.email,
    name: data.name,
    role: data.role ?? 'trader',
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(
    () => (typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null)
  )
  const [user, setUser] = useState<UserProfile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    fetchMe(token).then(setUser).catch(() => {
      localStorage.removeItem(TOKEN_KEY)
      setToken(null)
      setUser(null)
    })
  }, [token])

  const login = useCallback(async (email: string, password: string) => {
    setError(null)
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      setError(data.detail ?? 'Login failed')
      throw new Error(data.detail ?? 'Login failed')
    }
    if (data.requires_mfa) {
      setError('MFA required — use /mfa/verify with your code')
      throw new Error('MFA required')
    }
    const accessToken = data.access_token
    if (!accessToken) {
      setError('Invalid response')
      throw new Error('Invalid response')
    }
    localStorage.setItem(TOKEN_KEY, accessToken)
    setToken(accessToken)
    const profile = await fetchMe(accessToken)
    setUser(profile)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    window.location.href = '/login'
  }, [])

  const value: AuthContextValue = {
    token,
    user,
    login,
    logout,
    isAuthenticated: !!token,
    error,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
