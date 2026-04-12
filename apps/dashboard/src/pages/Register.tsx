/**
 * Register page. Phoenix Claw branding, animated background, glass card.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Eye, EyeOff, ArrowRight } from 'lucide-react'

export default function Register() {
  const [invitationCode, setInvitationCode] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [localError, setLocalError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [focused, setFocused] = useState<string | null>(null)
  const { register, error: contextError } = useAuth()
  const navigate = useNavigate()
  const error = contextError ?? localError

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLocalError('')
    try {
      await register(email, password, name, invitationCode)
      navigate('/', { replace: true })
    } catch {
      setLocalError('Registration failed. Try again.')
    }
  }

  const inputClass = 'w-full h-11 rounded-xl border border-white/10 bg-white/5 px-4 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-blue-500/50 focus:bg-white/[0.07] transition-all'

  return (
    <div className="auth-bg dark min-h-screen flex items-center justify-center p-4 relative">
      <div className="auth-orb auth-orb-1" aria-hidden />
      <div className="auth-orb auth-orb-2" aria-hidden />

      <div className="w-full max-w-md mx-auto relative z-10" style={{ animation: 'login-card-enter 0.7s ease-out backwards' }}>
        <div className="relative rounded-2xl border border-white/[0.08] p-6 sm:p-8 shadow-2xl shadow-black/40 overflow-hidden"
          style={{ background: 'rgba(15, 23, 42, 0.8)', backdropFilter: 'blur(24px)' }}
        >
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-px bg-gradient-to-r from-transparent via-blue-500/50 to-transparent" />

          <div className="flex flex-col items-center gap-4 text-center mb-8">
            <div className="relative">
              <div className="absolute -inset-3 rounded-full bg-blue-500/10 animate-[login-pulse_3s_ease-in-out_infinite]" />
              <img src="/phoenix-logo.png" alt="" className="relative h-14 w-14" aria-hidden />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Phoenix Claw</h1>
              <p className="mt-1 text-sm text-white/40">Create your account</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="invitationCode" className="text-white/70 text-xs font-medium uppercase tracking-wider">Invitation Code</Label>
              <div className={`rounded-xl transition-all duration-300 ${focused === 'invitationCode' ? 'login-input-glow' : ''}`}>
                <input
                  id="invitationCode"
                  type="text"
                  value={invitationCode}
                  onChange={(e) => setInvitationCode(e.target.value)}
                  onFocus={() => setFocused('invitationCode')}
                  onBlur={() => setFocused(null)}
                  placeholder="Enter your invitation code"
                  required
                  autoComplete="off"
                  className={inputClass}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="name" className="text-white/70 text-xs font-medium uppercase tracking-wider">Name</Label>
              <div className={`rounded-xl transition-all duration-300 ${focused === 'name' ? 'login-input-glow' : ''}`}>
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onFocus={() => setFocused('name')}
                  onBlur={() => setFocused(null)}
                  placeholder="Your name"
                  autoComplete="name"
                  className={inputClass}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="email" className="text-white/70 text-xs font-medium uppercase tracking-wider">Email</Label>
              <div className={`rounded-xl transition-all duration-300 ${focused === 'email' ? 'login-input-glow' : ''}`}>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onFocus={() => setFocused('email')}
                  onBlur={() => setFocused(null)}
                  placeholder="you@example.com"
                  required
                  autoComplete="email"
                  className={inputClass}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password" className="text-white/70 text-xs font-medium uppercase tracking-wider">Password</Label>
              <div className={`relative rounded-xl transition-all duration-300 ${focused === 'password' ? 'login-input-glow' : ''}`}>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onFocus={() => setFocused('password')}
                  onBlur={() => setFocused(null)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                  className={`${inputClass} pr-10`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-xs text-white/30">At least 8 characters</p>
            </div>
            {error && (
              <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-400">
                {error}
              </div>
            )}
            <Button type="submit" className="w-full h-11 rounded-xl font-semibold text-sm relative overflow-hidden group">
              <span className="relative z-10 flex items-center justify-center gap-2">
                Create account
                <ArrowRight className="h-4 w-4 group-hover:translate-x-1 transition-transform" />
              </span>
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-700" />
            </Button>
          </form>

          <div className="mt-6 flex items-center gap-3">
            <div className="flex-1 h-px bg-white/10" />
            <span className="text-xs text-white/30">or</span>
            <div className="flex-1 h-px bg-white/10" />
          </div>

          <p className="mt-4 text-center text-sm text-white/40">
            Already have an account?{' '}
            <Link to="/login" className="font-medium text-blue-400 hover:text-blue-300 transition-colors hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
