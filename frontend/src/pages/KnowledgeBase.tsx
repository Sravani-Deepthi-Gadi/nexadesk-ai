import {
  AlertTriangle, BookOpen, Eye, FileText, RefreshCw, Trash2, Upload,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useApi } from '../lib/useApi'
import type { ChunkRow, DocumentRow } from '../lib/types'
import {
  Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Loading,
  Table, Td, Th, formatBytes, inputClass, timeAgo, useToast,
  PageTitle,
} from '../components/ui'

export function KnowledgeBase() {
  const { isAdmin } = useAuth()
  const toast = useToast()
  const { data, loading, error, refetch } = useApi<DocumentRow[]>(() => api.documents())

  const [uploadOpen, setUploadOpen] = useState(false)
  const [inspect, setInspect] = useState<DocumentRow | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<DocumentRow | null>(null)
  const [workingId, setWorkingId] = useState<number | null>(null)

  async function doReindex(doc: DocumentRow) {
    setWorkingId(doc.id)
    try {
      await api.reindex(doc.id)
      toast(`Rebuilt the index for "${doc.title}".`, 'ok')
      await refetch()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Reindex failed.', 'danger')
    } finally {
      setWorkingId(null)
    }
  }

  async function doDelete(doc: DocumentRow) {
    setWorkingId(doc.id)
    try {
      await api.deleteDocument(doc.id)
      toast(`Deleted "${doc.title}".`, 'ok')
      setConfirmDelete(null)
      await refetch()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Delete failed.', 'danger')
    } finally {
      setWorkingId(null)
    }
  }

  return (
    <div className="space-y-6">
      <PageTitle
        title="Knowledge Base"
        subtitle="Documents the agent can quote from, with sources"
        action={isAdmin && (
          <Button onClick={() => setUploadOpen(true)}>
            <Upload className="size-4" aria-hidden="true" />
            Upload document
          </Button>
        )}
      />

      {!isAdmin && (
        <p className="rounded-lg border border-line bg-surface px-4 py-2.5 text-[13px] text-ink-muted">
          You are signed in as a viewer. Uploading, reindexing and deleting
          require an administrator account.
        </p>
      )}

      <Card>
        {loading && !data ? <Loading label="Loading documents" />
          : error ? <ErrorState message={error} onRetry={refetch} />
          : !data || data.length === 0 ? (
            <EmptyState icon={<BookOpen className="size-7" />}
              title="No documents yet"
              hint="Upload a PDF or text file of policies, pricing or FAQs. The agent will answer from it and cite the source."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Document</Th>
                  <Th>Status</Th>
                  <Th>Chunks</Th>
                  <Th>Flagged</Th>
                  <Th>Uploaded</Th>
                  <Th className="text-right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {data.map((doc) => (
                  <tr key={doc.id} className="hover:bg-canvas/60">
                    <Td>
                      <div className="flex items-center gap-2.5">
                        <FileText className="size-4 shrink-0 text-ink-subtle" aria-hidden="true" />
                        <div className="min-w-0">
                          <p className="truncate font-medium text-ink">{doc.title}</p>
                          <p className="truncate text-[12px] text-ink-subtle">
                            {doc.filename} · {formatBytes(doc.size_bytes)}
                          </p>
                        </div>
                      </div>
                    </Td>
                    <Td>
                      <Badge tone={doc.status === 'indexed' ? 'ok'
                        : doc.status === 'failed' ? 'danger' : 'warn'}>
                        {doc.status}
                      </Badge>
                    </Td>
                    <Td className="tabular-nums text-ink-muted">{doc.chunk_count}</Td>
                    <Td>
                      {doc.suspicious_chunk_count > 0 ? (
                        <Badge tone="warn">
                          <AlertTriangle className="size-3" aria-hidden="true" />
                          {doc.suspicious_chunk_count}
                        </Badge>
                      ) : (
                        <span className="text-[13px] text-ink-subtle">—</span>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap text-[13px] text-ink-subtle">
                      {timeAgo(doc.uploaded_at)}
                    </Td>
                    <Td>
                      <div className="flex justify-end gap-1.5">
                        <Button size="sm" variant="ghost" onClick={() => setInspect(doc)}>
                          <Eye className="size-3.5" aria-hidden="true" />
                          Inspect
                        </Button>
                        {isAdmin && (
                          <>
                            <Button size="sm" variant="ghost"
                                    loading={workingId === doc.id}
                                    onClick={() => void doReindex(doc)}>
                              <RefreshCw className="size-3.5" aria-hidden="true" />
                              Reindex
                            </Button>
                            <Button size="sm" variant="ghost"
                                    onClick={() => setConfirmDelete(doc)}
                                    className="!text-danger hover:!bg-danger-soft">
                              <Trash2 className="size-3.5" aria-hidden="true" />
                            </Button>
                          </>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
      </Card>

      {uploadOpen && (
        <UploadDialog onClose={() => setUploadOpen(false)}
                      onDone={() => { setUploadOpen(false); void refetch() }} />
      )}
      {inspect && <InspectDialog doc={inspect} onClose={() => setInspect(null)} />}

      <Dialog open={!!confirmDelete} onClose={() => setConfirmDelete(null)}
        title="Delete this document?"
        description="Its chunks and vectors are removed. The agent will no longer be able to answer from it. This cannot be undone."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Cancel</Button>
            <Button variant="danger" loading={workingId === confirmDelete?.id}
                    onClick={() => confirmDelete && void doDelete(confirmDelete)}>
              Delete document
            </Button>
          </>
        }>
        <p className="text-sm text-ink">
          <span className="font-medium">{confirmDelete?.title}</span>{' '}
          <span className="text-ink-subtle">
            ({confirmDelete?.chunk_count} chunks)
          </span>
        </p>
      </Dialog>
    </div>
  )
}

function UploadDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function submit() {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const doc = await api.uploadDocument(file, title || file.name)
      toast(
        doc.suspicious_chunk_count > 0
          ? `Indexed with ${doc.suspicious_chunk_count} flagged passage(s) — review them.`
          : `Indexed "${doc.title}" into ${doc.chunk_count} chunks.`,
        doc.suspicious_chunk_count > 0 ? 'danger' : 'ok',
      )
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} title="Upload a document"
      description="PDF, .txt or .md, up to 10 MB. Text is extracted, chunked and embedded."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={busy} disabled={!file} onClick={() => void submit()}>
            Upload and index
          </Button>
        </>
      }>
      <div className="space-y-4">
        <div>
          <button onClick={() => inputRef.current?.click()}
            className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-line-strong px-4 py-8 text-center transition-colors hover:border-accent/50 hover:bg-accent-soft/40">
            <Upload className="size-5 text-ink-subtle" aria-hidden="true" />
            <span className="text-[13px] font-medium text-ink">
              {file ? file.name : 'Choose a file'}
            </span>
            <span className="text-xs text-ink-subtle">
              {file ? formatBytes(file.size) : 'PDF, TXT or Markdown'}
            </span>
          </button>
          <input ref={inputRef} type="file" className="sr-only"
                 accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>

        <Field label="Title" hint="Shown as the citation the agent quotes.">
          {(id) => (
            <input id={id} className={inputClass} value={title}
                   onChange={(e) => setTitle(e.target.value)}
                   placeholder={file?.name ?? 'Company Policies'} />
          )}
        </Field>

        {error && (
          <p className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-[13px] text-ink"
             role="alert">{error}</p>
        )}
      </div>
    </Dialog>
  )
}

function InspectDialog({ doc, onClose }: { doc: DocumentRow; onClose: () => void }) {
  const [onlyFlagged, setOnlyFlagged] = useState(doc.suspicious_chunk_count > 0)
  const { data, loading, error } = useApi<ChunkRow[]>(
    () => api.chunks(doc.id, onlyFlagged), [doc.id, onlyFlagged],
  )

  return (
    <Dialog open onClose={onClose} title={doc.title}
      description={`${doc.chunk_count} chunks indexed. Text is shown exactly as uploaded.`}
      footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <div className="space-y-3">
        {doc.suspicious_chunk_count > 0 && (
          <div className="flex items-start gap-2.5 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2.5">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden="true" />
            <p className="text-[13px] text-ink">
              {doc.suspicious_chunk_count} passage(s) matched prompt-injection
              heuristics. This is a prompt to review the document, not a block —
              the governance engine is what actually constrains the agent.
            </p>
          </div>
        )}

        <label className="flex items-center gap-2 text-[13px] text-ink-muted">
          <input type="checkbox" checked={onlyFlagged}
                 onChange={(e) => setOnlyFlagged(e.target.checked)}
                 className="size-3.5 rounded border-line-strong accent-[oklch(0.52_0.19_272)]" />
          Show flagged passages only
        </label>

        {loading ? <Loading label="Loading chunks" />
          : error ? <ErrorState message={error} />
          : !data || data.length === 0
            ? <EmptyState title={onlyFlagged ? 'No flagged passages' : 'No chunks'} />
            : (
              <ul className="space-y-2">
                {data.map((c) => (
                  <li key={c.id}
                      className={`rounded-lg border px-3 py-2.5 ${
                        c.is_suspicious ? 'border-warn/30 bg-warn-soft' : 'border-line bg-canvas'
                      }`}>
                    <div className="mb-1.5 flex items-center gap-2 text-[11px] text-ink-subtle">
                      <span className="font-mono">#{c.chunk_index}</span>
                      {c.page_number && <span>p. {c.page_number}</span>}
                      <span>{c.char_count} chars</span>
                      {c.is_suspicious && <Badge tone="warn">flagged</Badge>}
                    </div>
                    <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
                      {c.text}
                    </p>
                  </li>
                ))}
              </ul>
            )}
      </div>
    </Dialog>
  )
}
