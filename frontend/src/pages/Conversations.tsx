import { LifeBuoy, MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import { useApi } from '../lib/useApi'
import type {
  ConversationDetail, ConversationSummary, Escalation,
} from '../lib/types'
import {
  Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Loading,
  Table, Td, Th, timeAgo,
  PageTitle,
} from '../components/ui'

const STATE_TONE: Record<string, 'neutral' | 'ok' | 'warn' | 'danger'> = {
  active: 'ok', awaiting_approval: 'warn', escalated: 'danger', closed: 'neutral',
}

export function Conversations() {
  const convos = useApi<ConversationSummary[]>(() => api.conversations())
  const escalations = useApi<Escalation[]>(() => api.escalations())
  const [openId, setOpenId] = useState<number | null>(null)

  return (
    <div className="space-y-6">
      <PageTitle title="AI Conversations"
                 subtitle="Customer sessions and the tickets the agent raised" />

      <Card>
        <CardHeader title="Conversations" subtitle="Most recently active first" />
        {convos.loading && !convos.data ? <Loading label="Loading conversations" />
          : convos.error ? <ErrorState message={convos.error} onRetry={convos.refetch} />
          : !convos.data || convos.data.length === 0 ? (
            <EmptyState icon={<MessageSquare className="size-7" />}
              title="No conversations yet"
              hint="Customer sessions appear here as soon as someone uses the chat." />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Conversation</Th>
                  <Th>State</Th>
                  <Th>Messages</Th>
                  <Th>Pending</Th>
                  <Th>Last active</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {convos.data.map((c) => (
                  <tr key={c.id} className="hover:bg-canvas/60">
                    <Td>
                      <p className="font-medium text-ink">#{c.id}</p>
                      <p className="text-[12px] text-ink-subtle">
                        {c.customer_id ? `customer ${c.customer_id}` : 'not identified'}
                      </p>
                    </Td>
                    <Td>
                      <Badge tone={STATE_TONE[c.state] ?? 'neutral'}>
                        {c.state.replace('_', ' ')}
                      </Badge>
                    </Td>
                    <Td className="tabular-nums text-ink-muted">{c.message_count}</Td>
                    <Td>
                      {c.pending_actions > 0
                        ? <Badge tone="warn">{c.pending_actions}</Badge>
                        : <span className="text-ink-subtle">—</span>}
                    </Td>
                    <Td className="whitespace-nowrap text-[13px] text-ink-subtle">
                      {timeAgo(c.last_active_at)}
                    </Td>
                    <Td>
                      <div className="flex justify-end">
                        <Button size="sm" variant="ghost" onClick={() => setOpenId(c.id)}>
                          Transcript
                        </Button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
      </Card>

      <Card>
        <CardHeader title="Escalations" subtitle="Raised by escalate_to_human" />
        {escalations.loading && !escalations.data ? <Loading />
          : !escalations.data || escalations.data.length === 0 ? (
            <EmptyState icon={<LifeBuoy className="size-7" />} title="No escalations" />
          ) : (
            <ul className="divide-y divide-line">
              {escalations.data.map((e) => (
                <li key={e.id} className="flex items-start justify-between gap-4 px-5 py-3.5">
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-ink">{e.reason}</p>
                    {e.summary && (
                      <p className="mt-0.5 text-[13px] text-ink-subtle">{e.summary}</p>
                    )}
                    <p className="mt-1 text-[12px] text-ink-subtle">
                      {e.conversation_id ? `conversation ${e.conversation_id}` : 'no conversation'}
                      {' · '}{timeAgo(e.created_at)}
                    </p>
                  </div>
                  <Badge tone={e.status === 'open' ? 'warn' : 'ok'}>{e.status}</Badge>
                </li>
              ))}
            </ul>
          )}
      </Card>

      {openId !== null && (
        <TranscriptDialog id={openId} onClose={() => setOpenId(null)} />
      )}
    </div>
  )
}

function TranscriptDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, loading, error } = useApi<ConversationDetail>(
    () => api.conversation(id), [id],
  )
  return (
    <Dialog open onClose={onClose} title={`Conversation #${id}`}
      description={data ? `${data.message_count} messages · ${data.state.replace('_', ' ')}` : ''}
      footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      {loading ? <Loading label="Loading transcript" />
        : error ? <ErrorState message={error} />
        : !data ? null : (
          <ul className="space-y-3">
            {data.messages.map((m) => (
              <li key={m.seq}
                  className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                <div className={`max-w-[85%] rounded-xl px-3 py-2 text-[13px] ${
                  m.role === 'user' ? 'bg-accent text-white'
                    : m.role === 'tool' ? 'border border-line bg-canvas font-mono text-ink-muted'
                    : 'border border-line bg-surface text-ink'
                }`}>
                  {m.content || <em className="opacity-70">(tool exchange)</em>}
                  {m.tool_calls.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {m.tool_calls.map((t, i) => (
                        <span key={i}
                              className="rounded bg-ink/10 px-1.5 py-0.5 font-mono text-[11px]">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
    </Dialog>
  )
}
