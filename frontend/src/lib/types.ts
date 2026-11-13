/** Types mirroring the backend's response schemas. Kept in one file so a
 *  contract change surfaces as a compile error rather than a runtime one. */

export type Role = 'admin' | 'viewer'
export type Outcome = 'executed' | 'blocked' | 'pending_approval' | 'error' | 'approved' | 'rejected'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH'
export type RequestStatus = 'pending' | 'approved' | 'rejected' | 'executing' | 'executed' | 'failed'
export type DocStatus = 'pending' | 'indexed' | 'failed'
export type AgentStatus = 'active' | 'disabled'

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in_minutes: number
  role: Role
}
export interface Me { id: number; email: string; role: Role }

export interface ToolCallInfo {
  tool: string
  outcome: Outcome
  risk_level: RiskLevel | null
  audit_log_id: number | null
  action_request_id: number | null
}
export interface ChatResponse {
  reply: string
  session_token: string
  conversation_id: number
  tool_calls: ToolCallInfo[]
}

export interface ActionStatus {
  action_request_id: number
  tool_name: string
  status: RequestStatus
  risk_level: RiskLevel
  requested_at: string
  decided_at: string | null
  executed_at: string | null
  message: string
}
export interface ConversationStatus {
  session_token: string
  conversation_id: number
  state: string
  pending_actions: ActionStatus[]
  resolved_actions: ActionStatus[]
}

export interface ActionRequest {
  id: number
  agent_id: number
  conversation_id: number | null
  tool_name: string
  params: Record<string, unknown>
  params_hash: string
  risk_level: RiskLevel
  status: RequestStatus
  requested_at: string
  decided_at: string | null
  decided_by_admin_id: number | null
  decision_note: string | null
  executed_at: string | null
  result: Record<string, unknown> | null
  error_message: string | null
}
export interface DecisionResponse {
  request: ActionRequest
  execution_outcome: string | null
  execution_message: string | null
}

export interface AuditLogRow {
  id: number
  ts: string
  event_type: 'tool_invocation' | 'approval_decision' | 'execution'
  agent_id: number | null
  admin_user_id: number | null
  conversation_id: number | null
  action_request_id: number | null
  tool_name: string
  params: Record<string, unknown>
  risk_level: RiskLevel | null
  permission_result: 'pass' | 'fail' | null
  approval_status: string
  outcome: Outcome
  error_message: string | null
}

export interface DocumentRow {
  id: number
  filename: string
  title: string
  content_type: string
  size_bytes: number
  status: DocStatus
  chunk_count: number
  suspicious_chunk_count: number
  error_message: string | null
  uploaded_at: string
  uploaded_by_admin_id: number | null
}
export interface ChunkRow {
  id: number
  chunk_index: number
  page_number: number | null
  char_count: number
  is_suspicious: boolean
  text: string
}

export interface AgentPermissionRow {
  permission: string
  granted: boolean
  description: string
}
export interface AgentInfo {
  id: number
  name: string
  status: AgentStatus
  created_at: string
  permissions: AgentPermissionRow[]
}

export interface Overview {
  total_conversations: number
  total_tool_calls: number
  successful_actions: number
  blocked_actions: number
  pending_approvals: number
  open_escalations: number
  indexed_documents: number
  agent_status: AgentStatus | string
  agent_name: string
  risk_distribution: { risk_level: string; count: number }[]
  recent_activity: {
    id: number; ts: string; event_type: string; tool_name: string
    outcome: Outcome; risk_level: RiskLevel | null
    admin_user_id: number | null; action_request_id: number | null
  }[]
  tool_calls_last_7_days: { date: string; calls: number }[]
}

export interface ConversationSummary {
  id: number
  state: string
  customer_id: number | null
  started_at: string
  last_active_at: string
  message_count: number
  pending_actions: number
}
export interface ConversationDetail extends ConversationSummary {
  messages: { seq: number; role: string; content: string; tool_calls: string[]; created_at: string }[]
}

export interface Escalation {
  id: number
  conversation_id: number | null
  customer_id: number | null
  reason: string
  summary: string
  status: string
  created_at: string
}
