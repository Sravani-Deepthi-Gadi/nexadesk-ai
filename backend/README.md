# NexaDesk AI — Backend (Milestone 3A)

An AI business concierge with an enterprise agent governance layer.

**Milestone 1:** the vertical slice — a message travels from the API,
through the agent loop, through the governance engine, into a tool, and out
to an audit log; and is correctly refused when it should be.

**Milestone 2:** the human approval workflow — withheld actions become
reviewable records, an authenticated human rules on them, and only then
does anything run. Plus JWT auth, role-based authorisation, and an audit
trail that covers decisions as well as invocations.

**Milestone 3A:** the knowledge base and the full tool set — PDF/TXT
ingestion, local embeddings, persistent ChromaDB, cited retrieval, the four
remaining tools, and conversation status so a customer learns the outcome
of a withheld action.

The React frontend arrives in Milestone 3B.

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

**Actual result: 143 passed.**

### Run the server

```powershell
uvicorn app.main:app --reload
```

- Health check: http://127.0.0.1:8000/api/health
- Interactive API docs: http://127.0.0.1:8000/docs
- Full API reference: [`docs/API.md`](docs/API.md)
- Execution guarantees and crash recovery: [`docs/RECOVERY.md`](docs/RECOVERY.md)
- Knowledge base and untrusted content: [`docs/RAG.md`](docs/RAG.md)

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

The concierge agent is granted `READ_BUSINESS_DATA`,
`READ_CUSTOMER_DATA`, `CHECK_AVAILABILITY`, `CREATE_APPOINTMENT` and
`ESCALATE_TO_HUMAN`. Business hours are Monday–Friday, 09:00–17:00 UTC.

Note what is **absent**: `CANCEL_APPOINTMENT` and `MODIFY_CUSTOMER_DATA`.
That absence is what the headline test exercises.

### Tools

| Tool | Permission | Risk | Approval |
|---|---|---|---|
| `search_services` | READ_BUSINESS_DATA | LOW | no |
| `search_knowledge_base` | READ_BUSINESS_DATA | LOW | no |
| `check_availability` | CHECK_AVAILABILITY | LOW | no |
| `book_appointment` | CREATE_APPOINTMENT | MEDIUM | no |
| `get_customer_details` | READ_CUSTOMER_DATA | MEDIUM | no |
| `escalate_to_human` | ESCALATE_TO_HUMAN | LOW | no |
| `cancel_appointment` | CANCEL_APPOINTMENT | HIGH | **yes** |

### Verify the real embedding model

The test suite runs on an offline lexical embedding provider so it never
needs a model download. Confirm the real one works on your machine:

```powershell
python -m scripts.verify_embeddings
```

First run downloads ~90 MB. It should report that each paraphrased
question retrieves the passage answering it.

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

These are real. None is hidden behind a passing test.

**Verification gaps**

1. **Semantic retrieval quality is not verified in CI.** The sandbox this
   was built in blocks `huggingface.co`, so all-MiniLM-L6-v2 could not be
   downloaded. The suite runs on `HashingEmbeddings`, which is **lexical,
   not semantic**: it proves the pipeline, ranking, citations and isolation,
   not paraphrase quality. Run `python -m scripts.verify_embeddings` locally.
   ChromaDB persistence *is* verified — `tests/test_chroma_persistence.py`
   uses the real store.

**Security**

2. **Prompt-injection filtering is a mitigation, not a control.** Pattern
   matching will miss novel phrasing and non-English payloads. The control
   is the governance engine; see [`docs/RAG.md`](docs/RAG.md).
3. **`params_hash` does not stop an attacker with database write access.**
   A real fix is an HMAC keyed with a secret the database does not hold.
4. **Audit append-only is enforced in the ORM, not the database.** A raw
   `UPDATE audit_logs` from `sqlite3` succeeds. Production wants a trigger
   or a revoked UPDATE grant.
5. **No rate limiting** on `/api/chat`, `/api/chat/status` or
   `/api/admin/auth/login`.
6. **No token revocation list.** Deactivating an account is immediate, but
   an individual token lives until expiry.
7. **`audit_logs.params_json` stores raw parameters** with no redaction —
   and `book_appointment` parameters contain a customer name and email, so
   PII is now in the audit trail.
8. **No per-document access control.** Every indexed document is reachable
   from every customer conversation.
9. **Session tokens are unauthenticated bearer tokens.** Unguessable, but
   whoever holds one owns that conversation.

**Execution**

10. **Execution is at-most-once, not exactly-once.** A crash between the
    business commit and the audit write leaves an executed action with no
    `EXECUTION` audit row — detected and reported, never fabricated. See
    [`docs/RECOVERY.md`](docs/RECOVERY.md).
11. **Recovery assumes tools have no side effects outside the
    transaction.** True today; false the moment a tool calls an external
    booking API.

**Functional**

12. **Customers learn outcomes by polling** `/api/chat/status`. There is no
    push notification, and the conversation is not automatically continued
    with the result.
13. **Ingestion is synchronous** — a large PDF blocks the upload request.
14. **No OCR**, so scanned PDFs are rejected rather than indexed.
15. **Business hours are a single UTC schedule** with no per-service
    calendars, holidays or staff resources. Two different services can be
    booked into the same slot only if the clock allows it; there is no
    notion of *who* delivers them.
16. **Pending requests never expire**, and risk levels are static per tool
    rather than scored on parameters.
17. **Context trimming is by message count, not token budget.**

## Next

Milestone 3B: the React customer chat interface and admin dashboard
(overview, conversations, knowledge base, permissions, approvals, audit
logs, agent controls).
