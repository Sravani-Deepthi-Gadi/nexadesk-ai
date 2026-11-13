# NexaDesk AI — API Reference (Milestone 2)

Interactive docs are served at `/docs` when the app is running.

All admin routes require `Authorization: Bearer <token>`.

| Code | Meaning in this API |
|---|---|
| 401 | No token, malformed token, wrong signature, expired, or the account is deactivated |
| 403 | Authenticated, but the role is insufficient (VIEWER trying to decide) |
| 404 | No such action request |
| 409 | The decision conflicts with the request's current state, or `params_hash` is stale |
| 422 | Request body failed validation |

---

## Public

### `GET /api/health`
```json
{ "status": "ok" }
```

### `POST /api/chat`
```json
{ "message": "I'd like to cancel my appointment", "session_token": "optional" }
```
Omit `session_token` to start a new conversation; pass the one you were
given to continue it.

**Response**
```json
{
  "reply": "That needs approval from a member of staff...",
  "session_token": "T4bX...",
  "conversation_id": 1,
  "tool_calls": [
    {
      "tool": "cancel_appointment",
      "outcome": "pending_approval",
      "risk_level": "HIGH",
      "audit_log_id": 1,
      "action_request_id": 1
    }
  ]
}
```

`outcome` is one of `executed`, `blocked`, `pending_approval`, `error`.
`action_request_id` is non-null only when an action was withheld.

---

## Admin — authentication

### `POST /api/admin/auth/login`
```json
{ "email": "ops@nexacare.co", "password": "..." }
```
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in_minutes": 60,
  "role": "admin"
}
```
Unknown email and wrong password return the same 401 and the same message,
so the endpoint cannot be used to discover which addresses are registered.

### `GET /api/admin/auth/me`
Returns `{ "id", "email", "role" }` for the bearer token's owner.

---

## Admin — approvals

Roles: **VIEWER** may read. **ADMIN** may read and decide.

### `GET /api/admin/approvals/pending`
### `GET /api/admin/approvals?status=&limit=&offset=`
`status` is one of `pending`, `approved`, `rejected`, `executing`,
`executed`, `failed`.

### `GET /api/admin/approvals/{id}`

**Response shape**
```json
{
  "id": 1,
  "agent_id": 1,
  "conversation_id": 1,
  "tool_name": "cancel_appointment",
  "params": { "appointment_id": 7, "reason": "schedule clash" },
  "params_hash": "9f2c...64 hex chars",
  "risk_level": "HIGH",
  "status": "pending",
  "requested_at": "2026-11-12T07:40:00+00:00",
  "decided_at": null,
  "decided_by_admin_id": null,
  "decision_note": null,
  "executed_at": null,
  "result": null,
  "error_message": null
}
```

### `POST /api/admin/approvals/{id}/approve` — role ADMIN
### `POST /api/admin/approvals/{id}/reject` — role ADMIN

```json
{ "params_hash": "9f2c...", "note": "Customer confirmed by phone" }
```

**`params_hash` is required.** Send back the hash you were shown alongside
the parameters. If the stored request no longer matches it, the decision is
refused with 409 rather than being applied to parameters you did not
review. This is what binds an approval to one exact action.

**Response**
```json
{
  "request": { "...": "the updated action request" },
  "execution_outcome": "executed",
  "execution_message": "ok"
}
```
`execution_outcome` is `null` on a rejection, because rejection is terminal
and has no execution path.

Approving runs the action immediately, but execution re-checks the
emergency stop and the agent's permission first. If the agent was disabled
after approval, `execution_outcome` is `blocked` and the request ends as
`failed`.

---

## Admin — audit

### `GET /api/admin/audit`

Query parameters: `event_type`, `outcome`, `action_request_id`, `limit`,
`offset`.

`event_type` is `tool_invocation`, `approval_decision` or `execution`.
Filtering by `action_request_id` returns the complete story of one
high-risk action — three rows, in order.

```json
[
  {
    "id": 3,
    "ts": "2026-11-12T07:41:10+00:00",
    "event_type": "execution",
    "agent_id": 1,
    "admin_user_id": null,
    "conversation_id": 1,
    "action_request_id": 1,
    "tool_name": "cancel_appointment",
    "params": { "appointment_id": 7, "reason": "schedule clash" },
    "risk_level": "HIGH",
    "permission_result": "pass",
    "approval_status": "approved",
    "outcome": "executed",
    "error_message": null
  }
]
```

Audit rows are append-only. There is no update or delete endpoint, and the
ORM rejects both.

---

# Milestone 3A additions

## Customer

### `GET /api/chat/status?session_token=…`

Lets a customer poll for the outcome of a withheld action. Scoped by
session token alone — there is no conversation id parameter, so one
customer cannot read another's approvals.

```json
{
  "session_token": "T4bX...",
  "conversation_id": 1,
  "state": "awaiting_approval",
  "pending_actions": [
    {
      "action_request_id": 1,
      "tool_name": "cancel_appointment",
      "status": "pending",
      "risk_level": "HIGH",
      "requested_at": "2026-11-12T08:10:00+00:00",
      "decided_at": null,
      "executed_at": null,
      "message": "Waiting for a member of staff to review this."
    }
  ],
  "resolved_actions": []
}
```

`state` is `active`, `awaiting_approval`, `escalated` or `closed`.
`message` is customer-facing wording. The administrator's internal
`decision_note` is deliberately **not** returned.

404 if the session token is unknown.

## Admin — documents

Upload and destructive operations require the **ADMIN** role; reading is
open to **VIEWER** as well.

### `POST /api/admin/documents`
`multipart/form-data` with `file` and optional `title`.
Accepts PDF, `.txt` and `.md`, up to 10 MB.

| Code | Meaning |
|---|---|
| 201 | Indexed |
| 409 | Identical file already indexed (matched by SHA-256) |
| 415 | Unsupported file type |
| 422 | No extractable text (e.g. a scanned PDF needing OCR) |
| 413 | Over the size limit |

```json
{
  "id": 1, "filename": "policies.pdf", "title": "Company Policies",
  "content_type": "application/pdf", "size_bytes": 48120,
  "status": "indexed", "chunk_count": 12,
  "suspicious_chunk_count": 1, "error_message": null,
  "uploaded_at": "2026-11-12T08:00:00+00:00", "uploaded_by_admin_id": 1
}
```

`suspicious_chunk_count` is how many passages tripped the prompt-injection
heuristics. It is a prompt for human review, not a security control.

### `GET /api/admin/documents?status=`
### `GET /api/admin/documents/{id}`
### `GET /api/admin/documents/{id}/chunks?suspicious_only=true`

Shows exactly what was indexed, in its **original** form — neutralisation
happens at retrieval, so an administrator reads back what was uploaded.

### `POST /api/admin/documents/{id}/reindex`
Rebuilds this document's vectors from the chunk text in SQLite. Use after a
host wipes the vector store; nothing needs re-uploading.

### `DELETE /api/admin/documents/{id}`
204. Removes the document, its chunks and its vectors.

## New tools

| Tool | Permission | Risk | Approval |
|---|---|---|---|
| `search_knowledge_base` | READ_BUSINESS_DATA | LOW | no |
| `check_availability` | CHECK_AVAILABILITY | LOW | no |
| `book_appointment` | CREATE_APPOINTMENT | MEDIUM | no |
| `get_customer_details` | READ_CUSTOMER_DATA | MEDIUM | no |
| `escalate_to_human` | ESCALATE_TO_HUMAN | LOW | no |

`get_customer_details` takes no parameters by design — see
[`docs/RAG.md`](RAG.md#customer-data-isolation).
