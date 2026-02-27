import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import axios from 'axios'
import { useAuth } from '../hooks/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ShieldCheck, Loader2, CheckCircle2, Copy, Check, ShieldOff } from 'lucide-react'

interface SetupData {
  secret: string
  provisioning_uri: string
  qr_code: string
}

export default function MFASetup() {
  const { user } = useAuth()
  const [setupData, setSetupData] = useState<SetupData | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [copied, setCopied] = useState(false)
  const [mfaEnabled, setMfaEnabled] = useState(user?.mfa_enabled ?? false)

  const setupMut = useMutation({
    mutationFn: () => axios.post('/auth/mfa/setup').then(r => r.data),
    onSuccess: (data: SetupData) => {
      setSetupData(data)
      setError('')
      setSuccess('')
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to initialize MFA setup')
    },
  })

  const confirmMut = useMutation({
    mutationFn: () => axios.post('/auth/mfa/confirm', { totp_code: code }),
    onSuccess: () => {
      setSuccess('Two-factor authentication has been enabled successfully!')
      setMfaEnabled(true)
      setSetupData(null)
      setError('')
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Invalid code. Please try again.')
      setCode('')
    },
  })

  const disableMut = useMutation({
    mutationFn: () => axios.post('/auth/mfa/disable'),
    onSuccess: () => {
      setMfaEnabled(false)
      setSuccess('Two-factor authentication has been disabled.')
      setSetupData(null)
      setError('')
    },
  })

  const handleCopySecret = () => {
    if (setupData?.secret) {
      navigator.clipboard.writeText(setupData.secret).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      })
    }
  }

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-primary" />
          Two-Factor Authentication
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Add an extra layer of security to your account using an authenticator app.
        </p>
      </div>

      {success && (
        <div className="rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-600 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {success}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {!setupData && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${mfaEnabled ? 'bg-emerald-500/10' : 'bg-muted'}`}>
                  <ShieldCheck className={`h-5 w-5 ${mfaEnabled ? 'text-emerald-500' : 'text-muted-foreground'}`} />
                </div>
                <div>
                  <p className="text-sm font-medium">Authenticator App</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Badge variant={mfaEnabled ? 'success' : 'secondary'} className="text-[10px]">
                      {mfaEnabled ? 'Enabled' : 'Not configured'}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      Google Authenticator, Authy, etc.
                    </span>
                  </div>
                </div>
              </div>
              {mfaEnabled ? (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => disableMut.mutate()}
                  disabled={disableMut.isPending}
                  className="gap-1.5"
                >
                  {disableMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldOff className="h-3.5 w-3.5" />}
                  Disable
                </Button>
              ) : (
                <Button
                  size="sm"
                  onClick={() => setupMut.mutate()}
                  disabled={setupMut.isPending}
                  className="gap-1.5"
                >
                  {setupMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                  Enable
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {setupData && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Set Up Authenticator</CardTitle>
            <CardDescription>
              Scan the QR code below with your authenticator app (Google Authenticator, Authy, etc.)
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex justify-center">
              <div className="rounded-xl border bg-white p-4">
                <img src={setupData.qr_code} alt="MFA QR Code" className="h-48 w-48" />
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">
                Can't scan? Enter this key manually:
              </Label>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-lg border bg-muted/50 px-3 py-2 text-sm font-mono break-all">
                  {setupData.secret}
                </code>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={handleCopySecret}
                >
                  {copied ? <Check className="h-4 w-4 text-emerald-500" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                confirmMut.mutate()
              }}
              className="space-y-3"
            >
              <div className="space-y-2">
                <Label htmlFor="verify-code">Enter the 6-digit code from your app</Label>
                <Input
                  id="verify-code"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000"
                  required
                  className="text-center text-2xl tracking-[0.5em] font-mono max-w-[200px] mx-auto"
                  autoComplete="one-time-code"
                />
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  type="button"
                  onClick={() => { setSetupData(null); setError(''); setCode('') }}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={confirmMut.isPending || code.length !== 6}
                  className="flex-1"
                >
                  {confirmMut.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Verify & Enable
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
