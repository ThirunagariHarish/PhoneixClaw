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
  is_admin: boolean
}

interface AuthContextValue {
  token: string | null
  user: UserProfile | null
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string, invitationCode: string) => Promise<void>
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
    is_admin: data.is_admin === true || (data.role ?? '').toLowerCase() === 'admin',
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
    let res: Response
    try {
      res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
    } catch {
      const msg = 'Cannot reach the API server. Make sure the backend is running on port 8011.'
      setError(msg)
      throw new Error(msg)
    }
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      const msg = res.status === 401
        ? 'Invalid email or password.'
        : (data.detail ?? `Login failed (${res.status})`)
      setError(msg)
      throw new Error(msg)
    }
    if (data.requires_mfa) {
      setError('MFA required — use /mfa/verify with your code')
      throw new Error('MFA required')
    }
    const accessToken = data.access_token
    if (!accessToken) {
      setError('Invalid response from server')
      throw new Error('Invalid response')
    }
    localStorage.setItem(TOKEN_KEY, accessToken)
    setToken(accessToken)
    const profile = await fetchMe(accessToken)
    setUser(profile)
  }, [])

  const register = useCallback(async (email: string, password: string, name: string, invitationCode: string) => {
    setError(null)
    let res: Response
    try {
      res = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name, invitation_code: invitationCode }),
      })
    } catch {
      const msg = 'Cannot reach the API server. Make sure the backend is running on port 8011.'
      setError(msg)
      throw new Error(msg)
    }
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      const msg = data.detail ?? `Registration failed (${res.status})`
      setError(msg)
      throw new Error(msg)
    }
    if (res.status === 201) {
      await login(email, password)
    }
  }, [login])

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
    register,
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
