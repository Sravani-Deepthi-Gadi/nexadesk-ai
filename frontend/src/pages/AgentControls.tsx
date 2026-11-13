import {
  AlertTriangle, Power, PowerOff, ShieldAlert, ShieldCheck,
} from 'lucide-react'
import { useState } from 'react'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/useApi'
import type { AgentInfo, AgentPermissionRow } from '../lib/types'
import {
  Badge, Button, Card, CardHeader, Dialog, ErrorState, Field, Loading,
  inputClass, useToast,
  PageTitle,
} from '../components/ui'

/** Permissions that unlock actions the engine treats as HIGH risk.
 *  Granting one deserves a confirmation step of its own. */
const SENSITIVE = new Set(['CANCEL_APPOINTMENT', 'MODIFY_CUSTOMER_DATA'])

export function AgentControls() {
  const { isAdmin } = useAuth()
  const toast = useToast()
  const { data, loading, error, refetch, setData } = useApi<AgentInfo>(() => api.agent())

  const [confirmStop, setConfirmStop] = useState(false)
  const [stopReason, setStopReason] = useState('')
  const [confirmGrant, setConfirmGrant] = useState<AgentPermissionRow | null>(null)
  const [busy, setBusy] = useState(false)

  async function changeStatus(status: 'active' | 'disabled', reason?: string) {
    setBusy(true)
    try {
      setData(await api.setAgentStatus(status, reason))
      toast(
        status === 'disabled'
          ? 'Emergency stop engaged. All tool calls are now rejected.'
          : 'Agent re-enabled.',
        status === 'disabled' ? 'danger' : 'ok',
      )
      setConfirmStop(false)
      setStopReason('')
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Could not change status.', 'danger')
    } finally {
      setBusy(false)
    }
  }

  async function togglePermission(perm: AgentPermissionRow, granted: boolean) {
    setBusy(true)
    try {
      setData(await api.setPermission(perm.permission, granted))
      toast(`${granted ? 'Granted' : 'Revoked'} ${perm.permission}.`, granted ? 'ok' : 'info')
      setConfirmGrant(null)
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Could not change the permission.', 'danger')
    } finally {
      setBusy(false)
    }
  }

  if (loading && !data) return <Loading label="Loading agent" />
  if (error) return <ErrorState message={error} onRetry={refetch} />
  if (!data) return null

  const disabled = data.status === 'disabled'

  return (
    <div className="space-y-6">
      <PageTitle title="Agent Controls"
                 subtitle={`Identity, emergency stop and permissions for "${data.name}"`} />

      {!isAdmin && (
        <p className="rounded-lg border border-line bg-surface px-4 py-2.5 text-[13px] text-ink-muted">
          Viewers can see the agent's configuration but cannot change it.
        </p>
      )}

      <Card className={disabled ? 'border-danger/30' : ''}>
        <div className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div className="flex items-start gap-3.5">
            <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${
              disabled ? 'bg-danger-soft text-danger' : 'bg-ok-soft text-ok'
            }`}>
              {disabled ? <ShieldAlert className="size-5" /> : <ShieldCheck className="size-5" />}
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold">
                  Agent is {disabled ? 'disabled' : 'active'}
                </h2>
                <Badge tone={disabled ? 'danger' : 'ok'}>{data.status}</Badge>
              </div>
              <p className="mt-1 max-w-lg text-[13px] text-ink-muted">
                {disabled
                  ? 'Every tool call is being rejected at the governance layer. The agent cannot act, and cannot bypass this.'
                  : 'The agent may use the tools permitted below. High-risk actions still require human approval.'}
              </p>
              <p className="mt-1.5 font-mono text-[12px] text-ink-subtle">
                agent id {data.id}
              </p>
            </div>
          </div>

          {isAdmin && (
            disabled ? (
              <Button loading={busy} onClick={() => void changeStatus('active')}>
                <Power className="size-4" aria-hidden="true" />
                Re-enable agent
              </Button>
            ) : (
              <Button variant="danger" onClick={() => setConfirmStop(true)}>
                <PowerOff className="size-4" aria-hidden="true" />
                Emergency stop
              </Button>
            )
          )}
        </div>
      </Card>

      <Card>
        <CardHeader title="Permissions"
                    subtitle="Checked in the database on every tool call, never taken from the prompt" />
        <ul className="divide-y divide-line">
          {data.permissions.map((perm) => (
            <li key={perm.permission}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[13px] text-ink">{perm.permission}</span>
                  {SENSITIVE.has(perm.permission) && (
                    <Badge tone="danger">high risk</Badge>
                  )}
                </div>
                <p className="mt-0.5 text-[13px] text-ink-subtle">{perm.description}</p>
              </div>

              <label className="flex shrink-0 items-center gap-2.5">
                <span className={`text-[13px] font-medium ${
                  perm.granted ? 'text-ok' : 'text-ink-subtle'
                }`}>
                  {perm.granted ? 'Granted' : 'Not granted'}
                </span>
                <button
                  role="switch" aria-checked={perm.granted}
                  aria-label={`${perm.granted ? 'Revoke' : 'Grant'} ${perm.permission}`}
                  disabled={!isAdmin || busy}
                  onClick={() => {
                    if (!perm.granted && SENSITIVE.has(perm.permission)) {
                      setConfirmGrant(perm)
                    } else {
                      void togglePermission(perm, !perm.granted)
                    }
                  }}
                  className={`relative h-5.5 w-10 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                    perm.granted ? 'bg-accent' : 'bg-line-strong'
                  }`}>
                  <span className={`absolute top-0.5 size-4.5 rounded-full bg-white transition-all ${
                    perm.granted ? 'left-5' : 'left-0.5'
                  }`} />
                </button>
              </label>
            </li>
          ))}
        </ul>
      </Card>

      <Dialog open={confirmStop} onClose={() => setConfirmStop(false)}
        title="Engage emergency stop?"
        description="The agent will immediately stop being able to use any tool. Customers can still send messages, but nothing will be acted on."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmStop(false)}>Cancel</Button>
            <Button variant="danger" loading={busy}
                    onClick={() => void changeStatus('disabled', stopReason)}>
              <PowerOff className="size-4" aria-hidden="true" />
              Disable the agent
            </Button>
          </>
        }>
        <div className="space-y-3">
          <div className="flex items-start gap-2.5 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2.5">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden="true" />
            <p className="text-[13px] text-ink">
              Takes effect on the very next tool call — no restart needed.
              Already-approved actions awaiting execution will also be refused.
            </p>
          </div>
          <Field label="Reason" hint="Recorded in the audit trail against your account.">
            {(id) => (
              <input id={id} className={inputClass} value={stopReason}
                     onChange={(e) => setStopReason(e.target.value)}
                     placeholder="Suspicious activity in conversation 42" />
            )}
          </Field>
        </div>
      </Dialog>

      <Dialog open={!!confirmGrant} onClose={() => setConfirmGrant(null)}
        title={`Grant ${confirmGrant?.permission}?`}
        description="This unlocks an action the engine classifies as high risk."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmGrant(null)}>Cancel</Button>
            <Button variant="danger" loading={busy}
                    onClick={() => confirmGrant && void togglePermission(confirmGrant, true)}>
              Grant permission
            </Button>
          </>
        }>
        <p className="text-[13px] text-ink">
          {confirmGrant?.description}. The agent will still not be able to
          perform it without a human approving each individual request — but
          it will be able to propose them.
        </p>
      </Dialog>
    </div>
  )
}
