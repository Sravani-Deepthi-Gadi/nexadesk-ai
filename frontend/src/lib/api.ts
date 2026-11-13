/** Typed API client.
 *
 *  Token handling: the JWT lives in localStorage under one key, is attached
 *  by this module alone, and is cleared on any 401 so an expired session
 *  cannot leave the UI in a half-authenticated state. Nothing secret is
 *  ever stored here -- the token is a short-lived credential the server
 *  issued, and the backend re-checks the account on every request.
 */
import type {
  ActionRequest, AgentInfo, AuditLogRow, ChatResponse, ChunkRow,
  ConversationDetail, ConversationStatus, ConversationSummary,
  DecisionResponse, DocumentRow, Escalation, LoginResponse, Me, Overview,
} from './types'

const TOKEN_KEY = 'nexadesk.token'
const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
  get isAuth() { return this.status === 401 }
  get isForbidden() { return this.status === 403 }
  get isConflict() { return this.status === 409 }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

/** Called when any request comes back 401, so the app can redirect. */
let onUnauthorised: (() => void) | null = null
export function setUnauthorisedHandler(fn: () => void) { onUnauthorised = fn }

async function request<T>(
  path: string,
  { method = 'GET', body, auth = true, raw }: {
    method?: string; body?: unknown; auth?: boolean; raw?: FormData
  } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  if (!raw && body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth) {
    const token = tokenStore.get()
    if (token) headers['Authorization'] = `Bearer ${token}`
  }

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
    })
  } catch {
    throw new ApiError(0, 'Could not reach the server. Is the backend running?')
  }

  if (res.status === 401 && auth) {
    tokenStore.clear()
    onUnauthorised?.()
    throw new ApiError(401, 'Your session has expired. Please sign in again.')
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') detail = data.detail
      else if (Array.isArray(data?.detail)) {
        detail = data.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ') || detail
      }
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  // --- public -----------------------------------------------------------
  chat: (message: string, session_token?: string | null) =>
    request<ChatResponse>('/api/chat', {
      method: 'POST', auth: false,
      body: session_token ? { message, session_token } : { message },
    }),
  chatStatus: (session_token: string) =>
    request<ConversationStatus>(
      `/api/chat/status?session_token=${encodeURIComponent(session_token)}`,
      { auth: false },
    ),

  // --- auth -------------------------------------------------------------
  login: (email: string, password: string) =>
    request<LoginResponse>('/api/admin/auth/login', {
      method: 'POST', auth: false, body: { email, password },
    }),
  me: () => request<Me>('/api/admin/auth/me'),

  // --- metrics ----------------------------------------------------------
  overview: () => request<Overview>('/api/admin/metrics/overview'),
  conversations: () => request<ConversationSummary[]>('/api/admin/conversations'),
  conversation: (id: number) =>
    request<ConversationDetail>(`/api/admin/conversations/${id}`),
  escalations: () => request<Escalation[]>('/api/admin/escalations'),

  // --- documents --------------------------------------------------------
  documents: () => request<DocumentRow[]>('/api/admin/documents'),
  uploadDocument: (file: File, title: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    return request<DocumentRow>('/api/admin/documents', { method: 'POST', raw: form })
  },
  chunks: (id: number, suspiciousOnly = false) =>
    request<ChunkRow[]>(
      `/api/admin/documents/${id}/chunks${suspiciousOnly ? '?suspicious_only=true' : ''}`,
    ),
  reindex: (id: number) =>
    request<DocumentRow>(`/api/admin/documents/${id}/reindex`, { method: 'POST' }),
  deleteDocument: (id: number) =>
    request<void>(`/api/admin/documents/${id}`, { method: 'DELETE' }),

  // --- approvals --------------------------------------------------------
  approvals: (status?: string) =>
    request<ActionRequest[]>(`/api/admin/approvals${status ? `?status=${status}` : ''}`),
  approve: (id: number, params_hash: string, note?: string) =>
    request<DecisionResponse>(`/api/admin/approvals/${id}/approve`, {
      method: 'POST', body: { params_hash, note: note || null },
    }),
  reject: (id: number, params_hash: string, note?: string) =>
    request<DecisionResponse>(`/api/admin/approvals/${id}/reject`, {
      method: 'POST', body: { params_hash, note: note || null },
    }),

  // --- agent ------------------------------------------------------------
  agent: () => request<AgentInfo>('/api/admin/agent'),
  setAgentStatus: (status: 'active' | 'disabled', reason?: string) =>
    request<AgentInfo>('/api/admin/agent/status', {
      method: 'POST', body: { status, reason: reason || null },
    }),
  setPermission: (permission: string, granted: boolean) =>
    request<AgentInfo>('/api/admin/agent/permissions', {
      method: 'PUT', body: { permission, granted },
    }),

  // --- audit ------------------------------------------------------------
  audit: (q: { event_type?: string; outcome?: string; action_request_id?: number; limit?: number }) => {
    const p = new URLSearchParams()
    if (q.event_type) p.set('event_type', q.event_type)
    if (q.outcome) p.set('outcome', q.outcome)
    if (q.action_request_id) p.set('action_request_id', String(q.action_request_id))
    p.set('limit', String(q.limit ?? 150))
    return request<AuditLogRow[]>(`/api/admin/audit?${p.toString()}`)
  },
}
