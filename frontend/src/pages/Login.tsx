import { Activity, AlertCircle, Clock } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Button, Field, inputClass } from '../components/ui'

export function Login() {
  const { user, signIn, expired, clearExpired } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? '/admin'
    return <Navigate to={from} replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    clearExpired()
    try {
      await signIn(email, password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center gap-2.5 text-center">
          <span className="grid size-10 place-items-center rounded-xl bg-accent text-white">
            <Activity className="size-5" aria-hidden="true" />
          </span>
          <h1 className="text-lg font-semibold tracking-tight">NexaDesk AI</h1>
          <p className="text-[13px] text-ink-subtle">Agent governance console</p>
        </div>

        {expired && (
          <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-warn/30 bg-warn-soft px-3.5 py-2.5"
               role="status">
            <Clock className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden="true" />
            <p className="text-[13px] text-ink">
              Your session expired. Sign in again to continue.
            </p>
          </div>
        )}

        <form onSubmit={onSubmit}
              className="space-y-4 rounded-xl border border-line bg-surface p-6">
          <Field label="Email">
            {(id) => (
              <input id={id} type="email" required autoComplete="username"
                     className={inputClass} value={email}
                     onChange={(e) => setEmail(e.target.value)}
                     placeholder="you@company.com" />
            )}
          </Field>
          <Field label="Password">
            {(id) => (
              <input id={id} type="password" required autoComplete="current-password"
                     className={inputClass} value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            )}
          </Field>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2"
                 role="alert">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden="true" />
              <p className="text-[13px] text-ink">{error}</p>
            </div>
          )}

          <Button type="submit" loading={busy} className="w-full">Sign in</Button>
        </form>

        <p className="mt-5 text-center text-xs text-ink-subtle">
          No account? Create one with{' '}
          <code className="rounded bg-canvas px-1 py-0.5 font-mono">
            python -m scripts.create_admin
          </code>
        </p>
      </div>
    </div>
  )
}
