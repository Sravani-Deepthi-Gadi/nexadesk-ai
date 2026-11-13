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
