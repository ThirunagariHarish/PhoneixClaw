/**
 * Login page. M1.4 shell; real auth API in M1.3.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { cn } from '@/lib/utils'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState('')
  const { login, error: contextError } = useAuth()
  const navigate = useNavigate()
  const error = contextError ?? localError

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLocalError('')
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch {
      setLocalError('Login failed. Try again.')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-2xl font-semibold text-center">Phoenix v2</h1>
        <p className="text-muted-foreground text-center text-sm">
          Sign in to Phoenix v2
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={cn(
                'w-full px-3 py-2 rounded-lg border border-input bg-background',
                'focus:outline-none focus:ring-2 focus:ring-primary'
              )}
              required
              autoComplete="email"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={cn(
                'w-full px-3 py-2 rounded-lg border border-input bg-background',
                'focus:outline-none focus:ring-2 focus:ring-primary'
              )}
              required
              autoComplete="current-password"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <button
            type="submit"
            className="w-full py-2 rounded-lg bg-primary text-primary-foreground font-medium hover:opacity-90"
          >
            Sign in
          </button>
        </form>
      </div>
    </div>
  )
}
