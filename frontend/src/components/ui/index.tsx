/** Shared primitives. Small, accessible, and consistent in spacing and
 *  typography so every screen reads as one product. */
import {
  AlertCircle, AlertTriangle, CheckCircle2, Info, Loader2, X,
} from 'lucide-react'
import {
  createContext, useContext, useEffect, useId, useRef, useState,
  type ReactNode,
} from 'react'

/* ------------------------------------------------------------------ */
export function Spinner({ className = 'size-4' }: { className?: string }) {
  return <Loader2 className={`${className} animate-spin`} aria-hidden="true" />
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-16 text-ink-subtle"
         role="status" aria-live="polite">
      <Spinner />
      <span className="text-sm">{label}…</span>
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`rounded-md bg-line/70 ${className}`}
         style={{ animation: 'nd-pulse 1.6s ease-in-out infinite' }} />
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-danger/25 bg-danger-soft px-6 py-10 text-center"
         role="alert">
      <AlertCircle className="size-6 text-danger" aria-hidden="true" />
      <p className="max-w-md text-sm text-ink">{message}</p>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function EmptyState({ icon, title, hint, action }: {
  icon?: ReactNode; title: string; hint?: string; action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      {icon && <div className="text-ink-subtle" aria-hidden="true">{icon}</div>}
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint && <p className="max-w-sm text-sm text-ink-subtle">{hint}</p>}
      {action}
    </div>
  )
}

/* ------------------------------------------------------------------ */
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export function Button({
  children, variant = 'primary', size = 'md', loading, className = '',
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant; size?: 'sm' | 'md'; loading?: boolean
}) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-lg font-medium ' +
    'transition-colors disabled:cursor-not-allowed disabled:opacity-50 ' +
    'whitespace-nowrap'
  const sizes = { sm: 'h-8 px-3 text-[13px]', md: 'h-9.5 px-4 text-sm' }
  const variants: Record<ButtonVariant, string> = {
    primary: 'bg-accent text-white hover:bg-accent-hover',
    secondary: 'border border-line-strong bg-surface text-ink hover:bg-canvas',
    ghost: 'text-ink-muted hover:bg-canvas hover:text-ink',
    danger: 'bg-danger text-white hover:brightness-95',
  }
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
            disabled={rest.disabled || loading} {...rest}>
      {loading && <Spinner className="size-3.5" />}
      {children}
    </button>
  )
}

/* ------------------------------------------------------------------ */
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-line bg-surface ${className}`}>
      {children}
    </div>
  )
}

export function CardHeader({ title, subtitle, action }: {
  title: string; subtitle?: string; action?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-ink-subtle">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

/* ------------------------------------------------------------------ */
type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'accent'

const TONES: Record<Tone, string> = {
  neutral: 'bg-canvas text-ink-muted border-line-strong',
  ok: 'bg-ok-soft text-ok border-ok/25',
  warn: 'bg-warn-soft text-warn border-warn/30',
  danger: 'bg-danger-soft text-danger border-danger/25',
  accent: 'bg-accent-soft text-accent border-accent/25',
}

export function Badge({ children, tone = 'neutral', className = '' }: {
  children: ReactNode; tone?: Tone; className?: string
}) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${TONES[tone]} ${className}`}>
      {children}
    </span>
  )
}

export function riskTone(risk: string | null | undefined): Tone {
  if (risk === 'HIGH') return 'danger'
  if (risk === 'MEDIUM') return 'warn'
  if (risk === 'LOW') return 'ok'
  return 'neutral'
}

export function outcomeTone(outcome: string): Tone {
  if (['executed', 'approved'].includes(outcome)) return 'ok'
  if (['blocked', 'rejected', 'error', 'failed'].includes(outcome)) return 'danger'
  if (['pending_approval', 'pending', 'executing'].includes(outcome)) return 'warn'
  return 'neutral'
}

/* ------------------------------------------------------------------ */
export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  )
}
export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <th scope="col"
        className={`border-b border-line px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-subtle ${className}`}>
      {children}
    </th>
  )
}
export function Td({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <td className={`border-b border-line px-4 py-3 align-middle ${className}`}>{children}</td>
}

/* ------------------------------------------------------------------ */
export function Field({ label, hint, children }: {
  label: string; hint?: string; children: (id: string) => ReactNode
}) {
  const id = useId()
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-ink">{label}</label>
      {children(id)}
      {hint && <p className="text-xs text-ink-subtle">{hint}</p>}
    </div>
  )
}

export const inputClass =
  'w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm ' +
  'text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none ' +
  'focus:ring-2 focus:ring-accent/20'

/* ------------------------------------------------------------------ */
/** Modal dialog with focus trapping, Escape to close and a labelled title. */
export function Dialog({ open, onClose, title, description, children, footer }: {
  open: boolean; onClose: () => void; title: string
  description?: string; children?: ReactNode; footer?: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    const first = ref.current?.querySelector<HTMLElement>(
      'button, input, textarea, [tabindex]:not([tabindex="-1"])',
    )
    first?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink/35 backdrop-blur-[2px]"
           onClick={onClose} aria-hidden="true" />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId}
           className="nd-enter relative w-full max-w-lg overflow-hidden rounded-xl border border-line bg-surface shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 id={titleId} className="text-sm font-semibold text-ink">{title}</h2>
            {description && <p className="mt-1 text-[13px] text-ink-subtle">{description}</p>}
          </div>
          <button onClick={onClose} aria-label="Close dialog"
                  className="rounded-md p-1 text-ink-subtle hover:bg-canvas hover:text-ink">
            <X className="size-4" />
          </button>
        </div>
        {children && <div className="max-h-[60vh] overflow-y-auto px-5 py-4">{children}</div>}
        {footer && <div className="flex justify-end gap-2 border-t border-line bg-canvas px-5 py-3">{footer}</div>}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
type Toast = { id: number; text: string; tone: 'ok' | 'danger' | 'info' }
const ToastCtx = createContext<(text: string, tone?: Toast['tone']) => void>(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = (text: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    setItems((prev) => [...prev, { id, text, tone }])
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 5000)
  }
  const icons = {
    ok: <CheckCircle2 className="size-4 text-ok" />,
    danger: <AlertTriangle className="size-4 text-danger" />,
    info: <Info className="size-4 text-accent" />,
  }
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2"
           role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id}
               className="nd-enter pointer-events-auto flex items-start gap-2.5 rounded-lg border border-line bg-surface px-3.5 py-2.5 shadow-lg">
            <span className="mt-0.5 shrink-0">{icons[t.tone]}</span>
            <p className="text-[13px] leading-snug text-ink">{t.text}</p>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

/* ------------------------------------------------------------------ */
export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}


/* ------------------------------------------------------------------ */
export function PageTitle({ title, subtitle, action }: {
  title: string; subtitle?: string; action?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-ink-subtle">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}
