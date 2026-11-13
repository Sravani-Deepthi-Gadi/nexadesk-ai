import { FileClock, Filter, User } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import type { AuditLogRow } from '../lib/types'
import {
  Badge, Button, Card, Dialog, EmptyState, ErrorState, Loading, Table, Td,
  Th, outcomeTone, riskTone,
  PageTitle,
} from '../components/ui'

const EVENTS = [
  { label: 'All events', value: '' },
  { label: 'Tool invocation', value: 'tool_invocation' },
  { label: 'Approval decision', value: 'approval_decision' },
  { label: 'Execution', value: 'execution' },
]
const OUTCOMES = [
  { label: 'All outcomes', value: '' },
  { label: 'Executed', value: 'executed' },
  { label: 'Blocked', value: 'blocked' },
  { label: 'Pending approval', value: 'pending_approval' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'Error', value: 'error' },
]

export function AuditLogs() {
  const [event, setEvent] = useState('')
  const [outcome, setOutcome] = useState('')
  const [detail, setDetail] = useState<AuditLogRow | null>(null)

  const { data, loading, error, refetch } = useApi<AuditLogRow[]>(
    () => api.audit({ event_type: event || undefined, outcome: outcome || undefined }),
    [event, outcome],
  )

  const select =
    'rounded-lg border border-line-strong bg-surface px-3 py-1.5 text-[13px] ' +
    'text-ink focus:border-accent focus:outline-none'

  return (
    <div className="space-y-6">
      <PageTitle title="Audit Logs"
                 subtitle="Append-only record of every governed action, including refusals" />

      <div className="flex flex-wrap items-center gap-2.5">
        <Filter className="size-4 text-ink-subtle" aria-hidden="true" />
        <label htmlFor="f-event" className="sr-only">Event type</label>
        <select id="f-event" className={select} value={event}
                onChange={(e) => setEvent(e.target.value)}>
          {EVENTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <label htmlFor="f-outcome" className="sr-only">Outcome</label>
        <select id="f-outcome" className={select} value={outcome}
                onChange={(e) => setOutcome(e.target.value)}>
          {OUTCOMES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        {(event || outcome) && (
          <Button size="sm" variant="ghost"
                  onClick={() => { setEvent(''); setOutcome('') }}>
            Clear
          </Button>
        )}
        <span className="ml-auto text-[13px] text-ink-subtle">
          {data ? `${data.length} entries` : ''}
        </span>
      </div>

      <Card>
        {loading && !data ? <Loading label="Loading audit log" />
          : error ? <ErrorState message={error} onRetry={refetch} />
          : !data || data.length === 0 ? (
            <EmptyState icon={<FileClock className="size-7" />}
              title="No entries match"
              hint="Every governed action writes a row here — including blocked ones." />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Event</Th>
                  <Th>Tool</Th>
                  <Th>Risk</Th>
                  <Th>Permission</Th>
                  <Th>Outcome</Th>
                  <Th>By</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {data.map((row) => (
                  <tr key={row.id} className="hover:bg-canvas/60">
                    <Td className="whitespace-nowrap font-mono text-[12px] text-ink-subtle">
                      {new Date(row.ts).toLocaleString()}
                    </Td>
                    <Td className="whitespace-nowrap text-[13px] text-ink-muted">
                      {row.event_type.replace('_', ' ')}
                    </Td>
                    <Td className="font-mono text-[12.5px]">{row.tool_name}</Td>
                    <Td>
                      {row.risk_level
                        ? <Badge tone={riskTone(row.risk_level)}>{row.risk_level}</Badge>
                        : <span className="text-ink-subtle">—</span>}
                    </Td>
                    <Td>
                      {row.permission_result
                        ? <Badge tone={row.permission_result === 'pass' ? 'ok' : 'danger'}>
                            {row.permission_result}
                          </Badge>
                        : <span className="text-ink-subtle">—</span>}
                    </Td>
                    <Td>
                      <Badge tone={outcomeTone(row.outcome)}>
                        {row.outcome.replace('_', ' ')}
                      </Badge>
                    </Td>
                    <Td>
                      {row.admin_user_id ? (
                        <span className="flex items-center gap-1 text-[13px] text-ink-muted">
                          <User className="size-3.5" aria-hidden="true" />
                          admin {row.admin_user_id}
                        </span>
                      ) : (
                        <span className="text-[13px] text-ink-subtle">agent</span>
                      )}
                    </Td>
                    <Td>
                      <Button size="sm" variant="ghost" onClick={() => setDetail(row)}>
                        Details
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
      </Card>

      <Dialog open={!!detail} onClose={() => setDetail(null)}
        title={`Audit entry #${detail?.id}`}
        description={detail ? new Date(detail.ts).toLocaleString() : ''}
        footer={<Button variant="secondary" onClick={() => setDetail(null)}>Close</Button>}>
        {detail && (
          <div className="space-y-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[13px]">
              <Row label="Event" value={detail.event_type.replace('_', ' ')} />
              <Row label="Tool" value={detail.tool_name} mono />
              <Row label="Outcome" value={detail.outcome} />
              <Row label="Approval" value={detail.approval_status} />
              <Row label="Risk" value={detail.risk_level ?? '—'} />
              <Row label="Permission" value={detail.permission_result ?? '—'} />
              <Row label="Agent" value={detail.agent_id ? `#${detail.agent_id}` : '—'} />
              <Row label="Admin" value={detail.admin_user_id ? `#${detail.admin_user_id}` : '—'} />
              <Row label="Conversation"
                   value={detail.conversation_id ? `#${detail.conversation_id}` : '—'} />
              <Row label="Action request"
                   value={detail.action_request_id ? `#${detail.action_request_id}` : '—'} />
            </dl>

            <section>
              <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wider text-ink-subtle">
                Parameters
              </h3>
              <pre className="overflow-x-auto rounded-lg border border-line bg-canvas px-3 py-2.5 font-mono text-[12.5px] text-ink">
{JSON.stringify(detail.params, null, 2)}
              </pre>
              <p className="mt-1.5 text-[12px] text-ink-subtle">
                Customer names and email addresses are redacted before the row
                is written, so this trail never accumulates personal data.
              </p>
            </section>

            {detail.error_message && (
              <section>
                <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wider text-ink-subtle">
                  Detail
                </h3>
                <p className="rounded-lg border border-line bg-canvas px-3 py-2.5 text-[13px] text-ink">
                  {detail.error_message}
                </p>
              </section>
            )}
          </div>
        )}
      </Dialog>
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <>
      <dt className="text-ink-subtle">{label}</dt>
      <dd className={mono ? 'font-mono text-[12.5px] text-ink' : 'text-ink'}>{value}</dd>
    </>
  )
}
