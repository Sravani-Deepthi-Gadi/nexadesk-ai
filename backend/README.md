# NexaDesk AI — Backend (Milestone 2, final)

An AI business concierge with an enterprise agent governance layer.

**Milestone 1:** the vertical slice — a message travels from the API,
through the agent loop, through the governance engine, into a tool, and out
to an audit log; and is correctly refused when it should be.

**Milestone 2:** the human approval workflow — withheld actions become
reviewable records, an authenticated human rules on them, and only then
does anything run. Plus JWT auth, role-based authorisation, and an audit
trail that covers decisions as well as invocations.

RAG, the remaining tools and the React frontend arrive in later
milestones.

---

## The central invariant

> The LLM never executes anything. It only emits a request.
> A deterministic governance engine is the sole caller of every tool
> implementation.

This is enforced structurally, not by convention:

| Package | May import | Purpose |
|---|---|---|
| `app/agent/` | `app/schemas/tool_catalog.py` | Knows tool *names and shapes*. Cannot run them. |
| `app/governance/` | `app/tools/registry.py` | The only code that can reach an implementation. |
| `app/tools/` | — | Real functions that touch the database. |

`tests/test_import_boundary.py` parses every module under `app/agent/` with
Python's `ast` module and fails the build if any of them imports
`app.tools`, `app.governance.approvals` or `app.governance.action_requests`.
A permission check the agent could skip by importing a function directly
would be theatre.

A second test closes the back door: `app/governance/engine.py` must not
import the approval service either. The engine may *create* an action
request; it may never *decide* on one. Without that check the agent would
acquire a transitive path to approving its own actions through a module it
is allowed to import.

Permissions live in the **database**, keyed to `agent_id` — never in the
prompt. Anything in a prompt is negotiable; anything in a `WHERE` clause is
not.

## Order of checks

```
1. kill switch       — is this agent enabled at all?
2. tool exists       — is the name in the registry?
3. schema validation — do the params match the declared Pydantic model?
4. permission        — does this agent hold the required permission?
5. risk              — does this risk level need a human?
6. execute           — only now, and only via registry.impl
```

Every path writes exactly one audit row, **including every rejection**.
`audit_logs` is append-only, enforced by a SQLAlchemy `before_flush` listener.

## The approval workflow (Milestone 2)

```
PENDING ──approve──> APPROVED ──claim──> EXECUTING ──> EXECUTED
   │                                          └──────> FAILED
   └──reject──> REJECTED        (terminal: no execution path exists)
```

Four properties hold, and each has a test that fails without it:

**1. An approval is bound to exact parameters.** Parameters are stored
canonically (sorted keys, no incidental whitespace) with
`params_hash = sha256(tool_name + canonical_params)`. The approve and
reject endpoints *require* the client to send back the hash it displayed; a
mismatch is a 409. `expected_params_hash` is a keyword argument **with no
default**, so an internal caller that omits it fails with a `TypeError`
rather than approving unverified parameters — an optional check is a check
plus a bypass. The executor re-derives the hash from storage and
compares again before running. An administrator approves one specific
action, not "whatever is in that row by the time it executes."

**2. Decisions and executions happen at most once.** Every transition is an
atomic conditional UPDATE:

```sql
UPDATE action_requests SET status = 'approved' WHERE id = ? AND status = 'pending'
```

followed by a `rowcount == 1` check. A read-then-write here would be a
TOCTOU race. `tests/test_concurrency.py` fires eight threads at the same
request against a file-backed database and asserts exactly one wins —
swapping in the naive implementation makes all eight succeed and the
appointment gets cancelled eight times.

**3. Execution is at-most-once, and a crash is recoverable.** The
business change and the `EXECUTING → EXECUTED` transition commit *together*,
so a request found in `EXECUTING` after a restart proves the action never
happened and can be safely retried. Tools therefore must not commit, and
`tests/test_import_boundary.py` fails the build if one does. This is **not**
exactly-once — see [`docs/RECOVERY.md`](docs/RECOVERY.md) for the precise
guarantee, the assumption it rests on, and the one window that cannot be
closed.

**4. Approval is not a bypass of governance.** Minutes may pass between a
decision and execution, so `execute_approved()` re-checks the emergency
stop and re-checks the agent's permission. An agent disabled after approval
does not get to act.

**5. The LLM cannot approve its own actions.** `decided_by_admin_id` is a
foreign key to `admin_users`, set only behind JWT plus a role check, and
the import boundary above means no module the agent can reach even contains
the approval code.

---

## Setup (Windows PowerShell)

```powershell
# One-time: allow venv activation in this session
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# Configure secrets
Copy-Item .env.example .env
notepad .env        # paste your ANTHROPIC_API_KEY and a JWT_SECRET
```

Generate a JWT secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The app refuses to issue or verify tokens if `JWT_SECRET` is unset or left
as a placeholder — failing loudly beats signing tokens with a default
everyone knows.

### Database migrations

```powershell
alembic upgrade head          # create or update the schema
alembic downgrade base        # tear it back down (development only)
```

Alembic reads `DATABASE_URL` from your `.env` via `alembic/env.py`; no
connection string is committed. `render_as_batch` is on because SQLite
cannot `ALTER` most columns in place.

### Create an administrator

```powershell
python -m scripts.create_admin
```

Or set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env` to have one seeded at
startup. No credentials are hardcoded anywhere; with both unset, no admin
is created.

> **An Anthropic (Claude.ai) subscription is not API access.** You need
> prepaid credits at `console.anthropic.com`. $5 covers all of development
> on `claude-haiku-5-5` ($0.10 / $0.50 per million tokens) plus a demo
> recording on `claude-sonnet-5-5` ($2 / $10).

### Run the tests (no API key needed)

```powershell
python -m pytest -q
```

The suite runs against in-memory SQLite with a scripted fake LLM: no
network, no cost, deterministic. The concurrency tests use a temporary
file-backed database, because threads need to see each other's writes.

**Actual result: 72 passed.**

### Run the server

```powershell
uvicorn app.main:app --reload
```

- Health check: http://127.0.0.1:8000/api/health
- Interactive API docs: http://127.0.0.1:8000/docs
- Full API reference: [`docs/API.md`](docs/API.md)
- Execution guarantees and crash recovery: [`docs/RECOVERY.md`](docs/RECOVERY.md)

```powershell
# Try a real turn (requires ANTHROPIC_API_KEY)
$body = @{ message = "What services do you offer?" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/chat -Method Post `
  -ContentType "application/json" -Body $body
```

Pass the `session_token` from the response back on the next request to
continue the same conversation.

---

## Seeded state

The concierge agent is granted `READ_BUSINESS_DATA`, `CHECK_AVAILABILITY`
and `CREATE_APPOINTMENT`.

Note what is **absent**: `CANCEL_APPOINTMENT` and `MODIFY_CUSTOMER_DATA`.
That absence is what the headline test exercises.

## What the tests prove

### Milestone 1 — governance

| Test | Claim |
|---|---|
| `test_permitted_low_risk_tool_executes_and_is_audited` | Happy path works and is logged |
| `test_missing_permission_blocks_and_does_not_mutate_data` | Blocked means **the row did not change** |
| `test_high_risk_with_permission_still_withholds_execution` | Permission alone ≠ authorisation for HIGH risk |
| `test_unknown_tool_is_blocked_and_audited` | A hallucinated tool name is refused and recorded |
| `test_emergency_stop_blocks_even_a_permitted_tool` | Kill switch takes effect on the next call, no restart |
| `test_invalid_parameters_are_rejected_before_execution` | Bad params never reach the implementation |
| `test_audit_rows_cannot_be_modified` | The audit trail has no UPDATE path |
| `test_agent_package_never_imports_tool_implementations` | The boundary is real |
| `test_agent_cannot_reach_approvals_transitively` | No back door through the engine |
| `test_sessions_are_isolated` | One customer cannot read another's history |

### Milestone 2 — approvals and auth

| Test | Claim |
|---|---|
| `test_high_risk_action_creates_pending_request` | A withheld action becomes a reviewable record |
| `test_approval_executes_the_action` | Approval actually cancels the appointment |
| `test_rejection_never_executes` | Rejected actions leave the data untouched |
| `test_rejected_request_cannot_be_executed_afterwards` | REJECTED is terminal even via internal misuse |
| `test_approval_with_stale_params_hash_is_refused` | You cannot approve parameters you were not shown |
| `test_params_tampered_after_approval_are_not_executed` | Editing `params_json` post-approval blocks execution |
| `test_duplicate_approval_is_refused` | Second decision gets 409 |
| `test_duplicate_execution_is_impossible` | The action runs exactly once |
| `test_emergency_stop_after_approval_blocks_execution` | Approval is not immunity from the kill switch |
| `test_permission_revoked_after_approval_blocks_execution` | Permissions are re-checked at execution time |
| `test_no_token_is_rejected` / `test_malformed_tokens_are_rejected` | 401 on absent or junk credentials |
| `test_token_signed_with_another_secret_is_rejected` | Forged tokens fail |
| `test_expired_token_is_rejected` | Expiry is enforced |
| `test_viewer_may_read_but_not_decide` | Role gate works |
| `test_role_escalation_in_token_is_ignored` | A token claiming `admin` does not make you one |
| `test_deactivated_admin_token_stops_working` | Revocation is immediate, not at expiry |
| `test_login_does_not_reveal_whether_an_email_exists` | No account enumeration |
| `test_full_lifecycle_produces_three_linked_audit_rows` | Invocation → decision → execution, all linked |

### Hardening — mandatory hash verification

| Test | Claim |
|---|---|
| `test_approve_without_hash_is_a_type_error` | No internal path can skip verification |
| `test_reject_without_hash_is_a_type_error` | Same for rejection |
| `test_approve_with_bad_hash_is_refused` | Empty, blank, wrong and malformed hashes all refused |
| `test_hash_of_another_request_does_not_authorise_this_one` | A valid hash is not a master key |

### Crash recovery (`tests/test_crash_recovery.py`)

| Test | Claim |
|---|---|
| `test_tool_failure_rolls_back_the_business_change` | A tool that mutates then raises changes nothing |
| `test_interrupted_execution_leaves_no_business_change` | Failure between flush and commit is invisible |
| `test_stranded_request_is_found` | Crashed work is detectable |
| `test_recently_claimed_request_is_left_alone` | Recovery does not fight a live worker |
| `test_recovery_returns_stranded_request_to_approved` | Stranded work becomes retryable |
| `test_recovered_request_executes_exactly_once` | Interrupt → recover → retry → performed once |
| `test_repeatedly_interrupted_request_is_abandoned_not_retried_forever` | Poison requests stop after 3 attempts |
| `test_execution_without_audit_row_is_detected` | The unclosable window is at least visible |
| `test_reconciliation_reports_but_never_fabricates_audit_rows` | No invented audit evidence |
| `test_tool_implementations_never_commit` | The transaction boundary cannot regress |

### Concurrency (`tests/test_concurrency.py`)

Eight threads, one request, a real file-backed database:

| Test | Claim |
|---|---|
| `test_concurrent_approvals_only_one_wins` | Exactly one approval succeeds |
| `test_concurrent_approve_and_reject_only_one_decision_sticks` | Approve/reject races resolve to one decision |
| `test_concurrent_execution_runs_the_action_exactly_once` | The appointment is cancelled once, not eight times |

---

## Honest limitations

These are real. None of them is hidden behind a passing test.

**Security**

1. **`params_hash` does not stop an attacker with database write access.**
   It catches a `params_json` edited in isolation, which is the realistic
   bug and the realistic insider mistake. Someone who rewrites both
   `params_json` and `params_hash` defeats it. A real fix is an HMAC with a
   server-side key the database does not hold, or signing the approval
   itself. Worth saying out loud rather than overclaiming.
2. **Audit append-only is enforced in the ORM, not the database.** A raw
   `UPDATE audit_logs` from `sqlite3` or `psql` succeeds. Production wants
   a `BEFORE UPDATE` trigger, a revoked UPDATE grant, or append-only
   storage.
3. **No token revocation list.** Deactivating an account works immediately
   because the user row is re-read on every request, but an individual
   token cannot be revoked before expiry. Short expiry is the mitigation.
4. **No rate limiting** on `/api/chat` or `/api/admin/auth/login`. An open
   endpoint calling a paid API is a billing incident waiting to happen, and
   an unthrottled login is a password-guessing surface.
5. **No CSRF protection**, which is fine for bearer-token clients but would
   not be if tokens ever move to cookies.
6. **`audit_logs.params_json` stores raw parameters** with no redaction. The
   moment a tool handles PII, that PII lands in the audit trail.
7. **Session tokens are unauthenticated bearer tokens.** 32 bytes of
   `secrets.token_urlsafe` is unguessable, but anyone holding one owns that
   conversation.

**Functional**

8. **Execution is at-most-once, not exactly-once.** A crash between the
   business commit and the audit write leaves an executed action with no
   `EXECUTION` audit row. It is detected and reported, never fabricated.
   Full detail and the assumptions involved: [`docs/RECOVERY.md`](docs/RECOVERY.md).
9. **Recovery assumes tools have no side effects outside the transaction.**
   True today. False the moment a tool calls an external booking API, and
   at that point `app/governance/recovery.py` must change before the tool
   ships.
10. **The customer is not notified when their action is approved.** The
   conversation returns to `active`, but there is no push or polling
   endpoint yet, so the customer has to send another message to learn the
   outcome.
11. **Pending requests never expire.** A request approved three weeks late
   still executes, subject to the re-checks. A TTL and an `EXPIRED` status
   belong in the state machine.
12. **Risk levels are static per tool.** Cancelling a £10 appointment and a
    £10,000 one are both HIGH. Real systems score risk on parameters too.
13. **Single agent identity.** The schema supports many; the app seeds one.
14. **Context trimming is by message count, not token budget.**

## Next

Milestone 3: RAG over uploaded documents, the remaining tools
(`check_availability`, `book_appointment`, `get_customer_details`,
`escalate_to_human`), and the React admin dashboard.
