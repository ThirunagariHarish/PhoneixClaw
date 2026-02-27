import { useState, useRef, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { AxiosError } from 'axios'
import axios from 'axios'
import { useAuth } from '../hooks/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Loader2, ShieldCheck, Mail } from 'lucide-react'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [step, setStep] = useState<'credentials' | 'mfa' | 'email_not_verified'>('credentials')
  const [mfaSession, setMfaSession] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [resending, setResending] = useState(false)
  const mfaInputRef = useRef<HTMLInputElement>(null)
  const { login, verifyMfa } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (step === 'mfa' && mfaInputRef.current) {
      mfaInputRef.current.focus()
    }
  }, [step])

  const handleCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const result = await login(email, password)
      if (result.success) {
        navigate('/')
      } else if (result.requires_mfa && result.mfa_session) {
        setMfaSession(result.mfa_session)
        setStep('mfa')
      } else if (result.email_not_verified) {
        setStep('email_not_verified')
      }
    } catch (err) {
      if (err instanceof AxiosError) {
        if (err.response?.status === 401) {
          setError('Invalid credentials')
        } else if (!err.response) {
          setError('Service unavailable. Please try again later.')
        } else {
          const detail = err.response.data?.detail
          setError(typeof detail === 'string' ? detail : `Login failed (${err.response.status}).`)
        }
      } else {
        setError('Login failed. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (mfaCode.length !== 6) return
    setLoading(true)
    setError('')
    try {
      await verifyMfa(mfaSession, mfaCode)
      navigate('/')
    } catch (err) {
      if (err instanceof AxiosError) {
        setError(err.response?.data?.detail || 'Invalid code. Please try again.')
      } else {
        setError('Verification failed. Please try again.')
      }
      setMfaCode('')
    } finally {
      setLoading(false)
    }
  }

  const handleResendVerification = async () => {
    setResending(true)
    try {
      await axios.post('/auth/resend-verification', { email })
    } catch {
      // silently fail
    } finally {
      setResending(false)
    }
  }

  if (step === 'email_not_verified') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background via-background to-primary/5 p-4">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/10 via-transparent to-transparent" />
        <Card className="w-full max-w-md relative border-border/50 shadow-2xl">
          <CardContent className="pt-8 pb-8 text-center space-y-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-amber-500/10">
              <Mail className="h-7 w-7 text-amber-500" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">Email Not Verified</h2>
              <p className="text-sm text-muted-foreground mt-2">
                Please verify your email before logging in. Check your inbox for the verification link.
              </p>
            </div>
            <div className="space-y-2 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleResendVerification}
                disabled={resending}
                className="gap-1.5"
              >
                {resending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />}
                Resend verification email
              </Button>
              <div>
                <button
                  onClick={() => { setStep('credentials'); setError('') }}
                  className="text-sm text-primary hover:underline"
                >
                  Back to login
                </button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (step === 'mfa') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background via-background to-primary/5 p-4">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/10 via-transparent to-transparent" />
        <Card className="w-full max-w-md relative border-border/50 shadow-2xl">
          <CardHeader className="text-center space-y-4">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
              <ShieldCheck className="h-6 w-6 text-primary" />
            </div>
            <div>
              <CardTitle className="text-2xl">Two-Factor Authentication</CardTitle>
              <CardDescription>Enter the 6-digit code from your authenticator app</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {error && (
              <div className="mb-4 rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {error}
              </div>
            )}
            <form onSubmit={handleMfaSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="mfa-code">Authentication Code</Label>
                <Input
                  ref={mfaInputRef}
                  id="mfa-code"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000"
                  required
                  className="text-center text-2xl tracking-[0.5em] font-mono"
                  autoComplete="one-time-code"
                />
              </div>
              <Button type="submit" className="w-full" disabled={loading || mfaCode.length !== 6}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Verify
              </Button>
            </form>
            <div className="mt-4 text-center">
              <button
                onClick={() => { setStep('credentials'); setError(''); setMfaCode('') }}
                className="text-sm text-muted-foreground hover:text-primary hover:underline"
              >
                Back to login
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background via-background to-primary/5 p-4">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/10 via-transparent to-transparent" />

      <Card className="w-full max-w-md relative border-border/50 shadow-2xl">
        <CardHeader className="text-center space-y-4">
          <img src="/phoenix-logo.png" alt="PhoenixTrade" className="mx-auto h-12 w-12" />
          <div>
            <CardTitle className="text-2xl">Welcome back</CardTitle>
            <CardDescription>Sign in to your PhoenixTrade account</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {error && (
            <div className="mb-4 rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <form onSubmit={handleCredentials} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="trader@example.com"
                required
                autoComplete="email"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                required
                autoComplete="current-password"
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Sign In
            </Button>
          </form>
          <p className="mt-6 text-center text-sm text-muted-foreground">
            Don&apos;t have an account?{' '}
            <Link to="/register" className="font-medium text-primary hover:underline">
              Create one
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
