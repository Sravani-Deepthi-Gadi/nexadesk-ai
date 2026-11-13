import {
  AlertTriangle, Check, Fingerprint, Inbox, ShieldCheck, X,
} from 'lucide-react'
import { useState } from 'react'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/useApi'
import type { ActionRequest, RequestStatus } from '../lib/types'
import {
  Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Loading,
  Table, Td, Th, inputClass, outcomeTone, riskTone, timeAgo, useToast,
  PageTitle,
} from '../components/ui'

const FILTERS: { label: string; value: RequestStatus | '' }[] = [
  { label: 'Pending', value: 'pending' },
  { label: 'Executed', value: 'executed' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'Failed', value: 'failed' },
  { label: 'All', value: '' },
]

export function Approvals() {
  const { isAdmin } = useAuth()
  const [filter, setFilter] = useState<RequestStatus | ''>('pending')
  const { data, loading, error, refetch } = useApi<ActionRequest[]>(
    () => api.approvals(filter || undefined), [filter],
  )
  const [review, setReview] = useState<ActionRequest | null>(null)

  return (
    <div className="space-y-6">
      <PageTitle title="Approval Requests"
                 subtitle="High-risk actions the agent proposed and the engine withheld" />

      {!isAdmin && (
        <p className="rounded-lg border border-line bg-surface px-4 py-2.5 text-[13px] text-ink-muted">
          Viewers can read requests but cannot approve or reject them.
        </p>
      )}

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button key={f.label} role="tab" aria-selected={filter === f.value}
            onClick={() => setFilter(f.value)}
            className={`rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors ${
              filter === f.value
                ? 'bg-accent text-white'
                : 'border border-line-strong bg-surface text-ink-muted hover:text-ink'
            }`}>
            {f.label}
          </button>
        ))}
      </div>

      <Card>
        {loading && !data ? <Loading label="Loading requests" />
          : error ? <ErrorState message={error} onRetry={refetch} />
          : !data || data.length === 0 ? (
            <EmptyState icon={<Inbox className="size-7" />}
              title={filter === 'pending' ? 'No requests waiting' : 'Nothing to show'}
              hint={filter === 'pending'
                ? 'High-risk actions appear here the moment the agent proposes one.'
                : 'Try a different status filter.'} />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Action</Th>
                  <Th>Risk</Th>
                  <Th>Status</Th>
                  <Th>Requested</Th>
                  <Th className="text-right">{isAdmin ? 'Review' : 'Details'}</Th>
                </tr>
              </thead>
              <tbody>
                {data.map((req) => (
                  <tr key={req.id} className="hover:bg-canvas/60">
                    <Td>
                      <p className="font-mono text-[13px] text-ink">{req.tool_name}</p>
                      <p className="text-[12px] text-ink-subtle">
                        Request #{req.id}
                        {req.conversation_id && ` · conversation ${req.conversation_id}`}
                      </p>
                    </Td>
                    <Td><Badge tone={riskTone(req.risk_level)}>{req.risk_level}</Badge></Td>
                    <Td><Badge tone={outcomeTone(req.status)}>{req.status}</Badge></Td>
                    <Td className="whitespace-nowrap text-[13px] text-ink-subtle">
                      {timeAgo(req.requested_at)}
                    </Td>
                    <Td>
                      <div className="flex justify-end">
                        <Button size="sm"
                                variant={req.status === 'pending' && isAdmin ? 'primary' : 'secondary'}
                                onClick={() => setReview(req)}>
                          {req.status === 'pending' && isAdmin ? 'Review' : 'View'}
                        </Button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
      </Card>

      {review && (
        <ReviewDialog request={review} canDecide={isAdmin}
          onClose={() => setReview(null)}
          onDone={() => { setReview(null); void refetch() }} />
      )}
    </div>
  )
}

function ReviewDialog({ request, canDecide, onClose, onDone }: {
  request: ActionRequest; canDecide: boolean
  onClose: () => void; onDone: () => void
}) {
  const toast = useToast()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmApprove, setConfirmApprove] = useState(false)
  const pending = request.status === 'pending'

  async function decide(kind: 'approve' | 'reject') {
    setBusy(kind)
    setError(null)
    try {
      // The hash shown above is sent back verbatim. If the stored request
      // changed since it was displayed, the backend answers 409 and the
      // decision is not applied to parameters nobody reviewed.
      const res = kind === 'approve'
        ? await api.approve(request.id, request.params_hash, note)
        : await api.reject(request.id, request.params_hash, note)
      toast(
        kind === 'approve'
          ? `Approved. Execution: ${res.execution_outcome ?? 'n/a'}.`
          : 'Request rejected. It can never execute.',
        kind === 'approve' && res.execution_outcome === 'executed' ? 'ok' : 'info',
      )
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The decision failed.')
      setConfirmApprove(false)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Dialog open onClose={onClose} title={`Review request #${request.id}`}
      description="Check the exact parameters and hash before deciding."
      footer={
        canDecide && pending ? (
          <>
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            <Button variant="danger" loading={busy === 'reject'}
                    onClick={() => void decide('reject')}>
              <X className="size-4" aria-hidden="true" />
              Reject
            </Button>
            <Button loading={busy === 'approve'}
                    onClick={() => setConfirmApprove(true)}>
              <Check className="size-4" aria-hidden="true" />
              Approve
            </Button>
          </>
        ) : <Button variant="secondary" onClick={onClose}>Close</Button>
      }>
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Badge tone={riskTone(request.risk_level)}>{request.risk_level} RISK</Badge>
          <Badge tone={outcomeTone(request.status)}>{request.status}</Badge>
          <Badge>{request.tool_name}</Badge>
        </div>

        {request.risk_level === 'HIGH' && pending && (
          <div className="flex items-start gap-2.5 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2.5">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden="true" />
            <p className="text-[13px] text-ink">
              Approving runs this action immediately. The engine re-checks the
              emergency stop and the agent's permission first.
            </p>
          </div>
        )}

        <section>
          <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wider text-ink-subtle">
            Exact parameters
          </h3>
          <pre className="overflow-x-auto rounded-lg border border-line bg-canvas px-3 py-2.5 font-mono text-[12.5px] leading-relaxed text-ink">
{JSON.stringify(request.params, null, 2)}
          </pre>
        </section>

        <section>
          <h3 className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wider text-ink-subtle">
            <Fingerprint className="size-3.5" aria-hidden="true" />
            Parameter hash
          </h3>
          <p className="break-all rounded-lg border border-line bg-canvas px-3 py-2 font-mono text-[11.5px] text-ink-muted">
            {request.params_hash}
          </p>
          <p className="mt-1.5 text-[12px] text-ink-subtle">
            Your decision is bound to this hash. If the stored request has
            changed since this was displayed, the decision is refused rather
            than applied to different parameters.
          </p>
        </section>

        {request.result && (
          <section>
            <h3 className="mb-1.5 text-[12px] font-semibold uppercase tracking-wider text-ink-subtle">
              Execution result
            </h3>
            <pre className="overflow-x-auto rounded-lg border border-ok/25 bg-ok-soft px-3 py-2.5 font-mono text-[12.5px] text-ink">
{JSON.stringify(request.result, null, 2)}
            </pre>
          </section>
        )}
        {request.error_message && (
          <p className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-[13px] text-ink">
            {request.error_message}
          </p>
        )}
        {request.decision_note && (
          <p className="text-[13px] text-ink-muted">
            <span className="font-medium text-ink">Decision note:</span>{' '}
            {request.decision_note}
          </p>
        )}

        {canDecide && pending && (
          <Field label="Note (optional)" hint="Recorded in the audit trail. Never shown to the customer.">
            {(id) => (
              <input id={id} className={inputClass} value={note}
                     onChange={(e) => setNote(e.target.value)}
                     placeholder="Customer confirmed by phone" />
            )}
          </Field>
        )}

        {error && (
          <p className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-[13px] text-ink"
             role="alert">{error}</p>
        )}
      </div>

      <Dialog open={confirmApprove} onClose={() => setConfirmApprove(false)}
        title="Approve and execute?"
        description="This carries out the action now. It cannot be undone from here."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmApprove(false)}>
              Cancel
            </Button>
            <Button loading={busy === 'approve'} onClick={() => void decide('approve')}>
              <ShieldCheck className="size-4" aria-hidden="true" />
              Yes, approve
            </Button>
          </>
        }>
        <pre className="overflow-x-auto rounded-lg border border-line bg-canvas px-3 py-2.5 font-mono text-[12.5px] text-ink">
{request.tool_name}({JSON.stringify(request.params)})
        </pre>
      </Dialog>
    </Dialog>
  )
}
