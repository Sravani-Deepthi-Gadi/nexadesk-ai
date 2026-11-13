import {
  Activity, AlertCircle, ArrowUp, Clock, Loader2, ShieldCheck, Sparkles,
} from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { ActionStatus, ChatResponse, ToolCallInfo } from '../lib/types'
import { Badge, Button, outcomeTone, riskTone } from '../components/ui'

const SESSION_KEY = 'nexadesk.session'

interface Turn {
  id: number
  role: 'user' | 'assistant'
  text: string
  tools?: ToolCallInfo[]
}

const SUGGESTIONS = [
  'What services do you offer?',
  'What is your cancellation policy?',
  'Do you have anything available tomorrow?',
]

export function CustomerChat() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [session, setSession] = useState<string | null>(
    () => localStorage.getItem(SESSION_KEY),
  )
  const [pending, setPending] = useState<ActionStatus[]>([])
  const [resolved, setResolved] = useState<ActionStatus[]>([])
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, busy])

  // Poll for approval outcomes. This is how a customer learns that a
  // withheld action was approved or rejected -- the backend has no push
  // channel, so the UI asks.
  useEffect(() => {
    if (!session) return
    let stop = false
    const tick = async () => {
      try {
        const s = await api.chatStatus(session)
        if (stop) return
        setPending(s.pending_actions)
        setResolved(s.resolved_actions)
      } catch { /* a missing session is not worth surfacing here */ }
    }
    void tick()
    const timer = setInterval(tick, 5000)
    return () => { stop = true; clearInterval(timer) }
  }, [session, turns.length])

  async function send(text: string) {
    if (!text.trim() || busy) return
    setError(null)
    setBusy(true)
    setTurns((t) => [...t, { id: Date.now(), role: 'user', text }])
    setInput('')
    try {
      const res: ChatResponse = await api.chat(text, session)
      if (!session) {
        localStorage.setItem(SESSION_KEY, res.session_token)
        setSession(res.session_token)
      }
      setTurns((t) => [...t, {
        id: Date.now() + 1, role: 'assistant',
        text: res.reply || '(no reply)', tools: res.tool_calls,
      }])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="grid size-7 place-items-center rounded-lg bg-accent text-white">
              <Activity className="size-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-semibold leading-tight">NexaCare Business Services</p>
              <p className="text-xs text-ink-subtle">AI concierge</p>
            </div>
          </div>
          <Link to="/admin"
                className="text-[13px] font-medium text-ink-muted hover:text-ink">
            Staff sign in
          </Link>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4">
        <div className="flex-1 space-y-5 py-6">
          {turns.length === 0 && (
            <div className="py-10 text-center">
              <span className="mx-auto mb-3 grid size-11 place-items-center rounded-xl bg-accent-soft text-accent">
                <Sparkles className="size-5" aria-hidden="true" />
              </span>
              <h1 className="text-lg font-semibold tracking-tight">How can I help?</h1>
              <p className="mx-auto mt-1.5 max-w-sm text-[13px] text-ink-subtle">
                Ask about our services, policies or availability — or book an
                appointment.
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => void send(s)}
                          className="rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-[13px] text-ink-muted transition-colors hover:border-accent/40 hover:text-ink">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn) => (
            <div key={turn.id}
                 className={turn.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
              <div className={`nd-enter max-w-[85%] ${turn.role === 'user' ? '' : 'w-full'}`}>
                <div className={
                  turn.role === 'user'
                    ? 'rounded-2xl rounded-br-sm bg-accent px-4 py-2.5 text-sm text-white'
                    : 'rounded-2xl rounded-bl-sm border border-line bg-surface px-4 py-3 text-sm leading-relaxed text-ink'
                }>
                  {turn.text}
                </div>
                {turn.tools && turn.tools.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {turn.tools.map((tc, i) => (
                      <Badge key={i} tone={outcomeTone(tc.outcome)}>
                        <ShieldCheck className="size-3" aria-hidden="true" />
                        {tc.tool}
                        <span className="opacity-70">· {tc.outcome.replace('_', ' ')}</span>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {busy && (
            <div className="flex items-center gap-2 text-[13px] text-ink-subtle" aria-live="polite">
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
              Thinking…
            </div>
          )}

          {(pending.length > 0 || resolved.length > 0) && (
            <ApprovalTracker pending={pending} resolved={resolved} />
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft px-3.5 py-2.5"
                 role="alert">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden="true" />
              <p className="text-[13px] text-ink">{error}</p>
            </div>
          )}
          <div ref={endRef} />
        </div>

        <form onSubmit={(e: FormEvent) => { e.preventDefault(); void send(input) }}
              className="sticky bottom-0 bg-canvas pb-5 pt-2">
          <div className="flex items-end gap-2 rounded-xl border border-line-strong bg-surface p-2 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20">
            <label htmlFor="chat-input" className="sr-only">Message</label>
            <textarea id="chat-input" rows={1} value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send(input)
                }
              }}
              placeholder="Ask a question or book an appointment…"
              className="max-h-32 min-h-[38px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-ink placeholder:text-ink-subtle focus:outline-none" />
            <Button type="submit" disabled={!input.trim() || busy}
                    aria-label="Send message" className="size-9 shrink-0 !px-0">
              <ArrowUp className="size-4" aria-hidden="true" />
            </Button>
          </div>
          <p className="mt-2 text-center text-xs text-ink-subtle">
            Sensitive actions are reviewed by a member of staff before they happen.
          </p>
        </form>
      </div>
    </div>
  )
}

function ApprovalTracker({ pending, resolved }: {
  pending: ActionStatus[]; resolved: ActionStatus[]
}) {
  const rows = [...pending, ...resolved].slice(0, 4)
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="mb-3 flex items-center gap-2">
        <ShieldCheck className="size-4 text-accent" aria-hidden="true" />
        <p className="text-[13px] font-semibold">Requests under review</p>
      </div>
      <ul className="space-y-2.5">
        {rows.map((a) => (
          <li key={a.action_request_id} className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-mono text-[12px] text-ink">{a.tool_name}</p>
              <p className="mt-0.5 text-[13px] text-ink-muted">{a.message}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Badge tone={riskTone(a.risk_level)}>{a.risk_level}</Badge>
              <Badge tone={outcomeTone(a.status)}>
                {a.status === 'pending' && <Clock className="size-3" aria-hidden="true" />}
                {a.status}
              </Badge>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
