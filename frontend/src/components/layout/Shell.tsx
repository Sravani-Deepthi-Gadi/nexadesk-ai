import {
  Activity, BookOpen, FileClock, LayoutDashboard, LogOut, Menu,
  MessageSquare, ShieldCheck, SlidersHorizontal, X,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../lib/auth'
import { Badge } from '../ui'

const NAV = [
  { to: '/admin', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/admin/conversations', label: 'Conversations', icon: MessageSquare },
  { to: '/admin/knowledge', label: 'Knowledge Base', icon: BookOpen },
  { to: '/admin/approvals', label: 'Approvals', icon: ShieldCheck },
  { to: '/admin/agent', label: 'Agent Controls', icon: SlidersHorizontal },
  { to: '/admin/audit', label: 'Audit Logs', icon: FileClock },
]

export function Shell() {
  const { user, signOut, isAdmin } = useAuth()
  const [open, setOpen] = useState(false)
  const location = useLocation()

  const nav = (
    <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
              isActive
                ? 'bg-accent-soft text-accent'
                : 'text-ink-muted hover:bg-canvas hover:text-ink'
            }`}>
          <Icon className="size-4 shrink-0" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </nav>
  )

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-surface lg:flex">
        <Brand />
        {nav}
        <AccountBox email={user?.email} role={user?.role} isAdmin={isAdmin} onSignOut={signOut} />
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink/35" onClick={() => setOpen(false)} aria-hidden="true" />
          <aside className="nd-enter relative flex h-full w-64 flex-col border-r border-line bg-surface">
            <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
              <Brand bare />
              <button onClick={() => setOpen(false)} aria-label="Close navigation"
                      className="rounded-md p-1 text-ink-subtle hover:bg-canvas">
                <X className="size-4" />
              </button>
            </div>
            {nav}
            <AccountBox email={user?.email} role={user?.role} isAdmin={isAdmin} onSignOut={signOut} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 lg:hidden">
          <button onClick={() => setOpen(true)} aria-label="Open navigation"
                  className="rounded-md p-1.5 text-ink-muted hover:bg-canvas">
            <Menu className="size-5" />
          </button>
          <span className="text-sm font-semibold">
            {NAV.find((n) => n.to === location.pathname)?.label ?? 'NexaDesk'}
          </span>
        </header>
        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function Brand({ bare }: { bare?: boolean }) {
  return (
    <div className={bare ? 'flex items-center gap-2' : 'flex items-center gap-2 px-5 py-4.5'}>
      <span className="grid size-7 place-items-center rounded-lg bg-accent text-white">
        <Activity className="size-4" aria-hidden="true" />
      </span>
      <span className="text-[15px] font-semibold tracking-tight">NexaDesk</span>
    </div>
  )
}

function AccountBox({ email, role, isAdmin, onSignOut }: {
  email?: string; role?: string; isAdmin: boolean; onSignOut: () => void
}) {
  return (
    <div className="border-t border-line p-3">
      <div className="mb-2 px-2">
        <p className="truncate text-[13px] font-medium text-ink">{email}</p>
        <Badge tone={isAdmin ? 'accent' : 'neutral'} className="mt-1">
          {role === 'admin' ? 'Administrator' : 'Viewer (read-only)'}
        </Badge>
      </div>
      <button onClick={onSignOut}
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium text-ink-muted hover:bg-canvas hover:text-ink">
        <LogOut className="size-4" aria-hidden="true" />
        Sign out
      </button>
    </div>
  )
}
