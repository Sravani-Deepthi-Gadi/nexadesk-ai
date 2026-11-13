import {
  AlertTriangle, BookOpen, CheckCircle2, LifeBuoy, MessageSquare,
  ShieldAlert, ShieldCheck, Zap,
} from 'lucide-react'
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import {
  Badge, Card, CardHeader, EmptyState, ErrorState, Loading, Skeleton,
  outcomeTone, timeAgo, PageTitle,
} from '../components/ui'
import type { Overview as OverviewData } from '../lib/types'

const RISK_COLOURS: Record<string, string> = {
  LOW: 'oklch(0.58 0.14 155)',
  MEDIUM: 'oklch(0.70 0.15 75)',
  HIGH: 'oklch(0.56 0.21 25)',
}

export function Overview() {
  const { data, loading, error, refetch } = useApi<OverviewData>(() => api.overview())

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <PageTitle title="Overview" subtitle="Loading live agent activity" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
        <Loading />
      </div>
    )
  }
  if (error) return <ErrorState message={error} onRetry={refetch} />
  if (!data) return null

  const disabled = data.agent_status === 'disabled'
  const risk = data.risk_distribution.filter((r) => r.count > 0)

  return (
    <div className="space-y-6">
      <PageTitle title="Overview"
                 subtitle={`Live activity for agent "${data.agent_name}"`} />

      {disabled && (
        <div className="flex items-start gap-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3"
             role="alert">
          <ShieldAlert className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-ink">Emergency stop is engaged</p>
            <p className="mt-0.5 text-[13px] text-ink-muted">
              The agent is disabled and every tool call is being rejected.{' '}
              <Link to="/admin/agent" className="font-medium text-accent underline">
                Agent controls
              </Link>
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Conversations" value={data.total_conversations} icon={MessageSquare} />
        <Kpi label="Tool calls" value={data.total_tool_calls} icon={Zap} />
        <Kpi label="Executed" value={data.successful_actions} icon={CheckCircle2} tone="ok" />
        <Kpi label="Blocked" value={data.blocked_actions} icon={ShieldCheck}
             tone={data.blocked_actions > 0 ? 'danger' : 'neutral'} />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Kpi label="Pending approvals" value={data.pending_approvals}
             icon={AlertTriangle} tone={data.pending_approvals > 0 ? 'warn' : 'neutral'}
             to="/admin/approvals" />
        <Kpi label="Open escalations" value={data.open_escalations} icon={LifeBuoy} />
        <Kpi label="Indexed documents" value={data.indexed_documents}
             icon={BookOpen} to="/admin/knowledge" />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Tool calls" subtitle="Last 7 days" />
          <div className="h-60 px-3 py-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.tool_calls_last_7_days}
                        margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.922 0.004 250)" vertical={false} />
                <XAxis dataKey="date" tickLine={false} axisLine={false}
                       tick={{ fontSize: 11, fill: 'oklch(0.62 0.01 265)' }}
                       tickFormatter={(d: string) => d.slice(5)} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false}
                       tick={{ fontSize: 11, fill: 'oklch(0.62 0.01 265)' }} />
                <Tooltip cursor={{ fill: 'oklch(0.96 0.025 272)' }}
                         contentStyle={{
                           borderRadius: 10, border: '1px solid oklch(0.922 0.004 250)',
                           fontSize: 12,
                         }} />
                <Bar dataKey="calls" fill="oklch(0.52 0.19 272)" radius={[5, 5, 0, 0]} maxBarSize={44} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <CardHeader title="Risk distribution" subtitle="By tool invocation" />
          <div className="h-60 px-3 py-4">
            {risk.length === 0 ? (
              <EmptyState title="No tool calls yet"
                          hint="Risk levels appear once the agent runs a tool." />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={risk} dataKey="count" nameKey="risk_level"
                       innerRadius={48} outerRadius={74} paddingAngle={3}>
                    {risk.map((r) => (
                      <Cell key={r.risk_level} fill={RISK_COLOURS[r.risk_level]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{
                    borderRadius: 10, border: '1px solid oklch(0.922 0.004 250)',
                    fontSize: 12,
                  }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          {risk.length > 0 && (
            <div className="flex flex-wrap gap-3 border-t border-line px-5 py-3">
              {risk.map((r) => (
                <span key={r.risk_level} className="flex items-center gap-1.5 text-[12px] text-ink-muted">
                  <span className="size-2.5 rounded-full"
                        style={{ background: RISK_COLOURS[r.risk_level] }} aria-hidden="true" />
                  {r.risk_level} · {r.count}
                </span>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card>
        <CardHeader title="Recent agent activity" subtitle="Newest audit events" />
        {data.recent_activity.length === 0 ? (
          <EmptyState title="Nothing recorded yet"
                      hint="Activity appears here as soon as the agent does anything." />
        ) : (
          <ul className="divide-y divide-line">
            {data.recent_activity.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-4 px-5 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <Badge tone={outcomeTone(row.outcome)}>{row.outcome.replace('_', ' ')}</Badge>
                  <span className="truncate font-mono text-[12.5px] text-ink">{row.tool_name}</span>
                  <span className="hidden text-[12px] text-ink-subtle sm:inline">
                    {row.event_type.replace('_', ' ')}
                  </span>
                </div>
                <span className="shrink-0 text-[12px] text-ink-subtle">{timeAgo(row.ts)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

export { PageTitle }

function Kpi({ label, value, icon: Icon, tone = 'neutral', to }: {
  label: string; value: number
  icon: React.ComponentType<{ className?: string }>
  tone?: 'neutral' | 'ok' | 'warn' | 'danger'; to?: string
}) {
  const tones = {
    neutral: 'text-ink-subtle', ok: 'text-ok',
    warn: 'text-warn', danger: 'text-danger',
  }
  const inner = (
    <Card className="p-4.5 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between">
        <p className="text-[13px] font-medium text-ink-muted">{label}</p>
        <Icon className={`size-4 ${tones[tone]}`} aria-hidden="true" />
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
    </Card>
  )
  return to ? <Link to={to} className="block">{inner}</Link> : inner
}
