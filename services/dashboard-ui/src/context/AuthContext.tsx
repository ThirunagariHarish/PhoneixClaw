import { createContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react'
import axios, { AxiosError } from 'axios'

export interface UserProfile {
  id: string
  email: string
  name: string | null
  timezone: string
  is_active: boolean
  is_admin: boolean
  created_at: string
}

interface AuthContextType {
  token: string | null
  isAdmin: boolean
  user: UserProfile | null
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name?: string) => Promise<void>
  logout: () => void
}

function parseJwtPayload(token: string): Record<string, unknown> {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64))
  } catch {
    return {}
  }
}

export const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const [user, setUser] = useState<UserProfile | null>(null)
  const [isAdmin, setIsAdmin] = useState(() => {
    const t = localStorage.getItem('token')
    return t ? !!parseJwtPayload(t).admin : false
  })
  const logoutRef = useRef<() => void>(() => {})

  const fetchProfile = useCallback(async () => {
    try {
      const res = await axios.get('/auth/me')
      setUser(res.data)
      setIsAdmin(res.data.is_admin)
    } catch {
      // ignore — will be fetched on next login
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    setToken(null)
    setUser(null)
    delete axios.defaults.headers.common['Authorization']
    window.location.href = '/login'
  }, [])

  logoutRef.current = logout

  useEffect(() => {
    const interceptor = axios.interceptors.response.use(
      (response) => response,
      async (error: AxiosError) => {
        const originalRequest = error.config
        if (
          error.response?.status === 401 &&
          originalRequest &&
          !originalRequest.url?.includes('/auth/')
        ) {
          const refreshToken = localStorage.getItem('refresh_token')
          if (refreshToken) {
            try {
              const res = await axios.post('/auth/refresh', {
                refresh_token: refreshToken,
              })
              const newToken = res.data.access_token
              localStorage.setItem('token', newToken)
              localStorage.setItem('refresh_token', res.data.refresh_token)
              setToken(newToken)
              axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`
              originalRequest.headers['Authorization'] = `Bearer ${newToken}`
              return axios(originalRequest)
            } catch {
              logoutRef.current()
              return Promise.reject(error)
            }
          }
          logoutRef.current()
        }
        return Promise.reject(error)
      },
    )
    return () => axios.interceptors.response.eject(interceptor)
  }, [])

  useEffect(() => {
    if (token && !user) {
      fetchProfile()
    }
  }, [token, user, fetchProfile])

  const login = useCallback(async (email: string, password: string) => {
    const res = await axios.post('/auth/login', { email, password })
    const t = res.data.access_token
    localStorage.setItem('token', t)
    localStorage.setItem('refresh_token', res.data.refresh_token)
    setToken(t)
    setIsAdmin(!!parseJwtPayload(t).admin)
    axios.defaults.headers.common['Authorization'] = `Bearer ${t}`
    await fetchProfile()
  }, [fetchProfile])

  const register = useCallback(async (email: string, password: string, name?: string) => {
    const res = await axios.post('/auth/register', { email, password, name })
    const t = res.data.access_token
    localStorage.setItem('token', t)
    localStorage.setItem('refresh_token', res.data.refresh_token)
    setToken(t)
    axios.defaults.headers.common['Authorization'] = `Bearer ${t}`
    await fetchProfile()
  }, [fetchProfile])

  if (token) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
  }

  return <AuthContext.Provider value={{ token, isAdmin, user, login, register, logout }}>{children}</AuthContext.Provider>
}
