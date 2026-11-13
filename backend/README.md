# NexaDesk AI — Backend (Milestone 1)

An AI business concierge with an enterprise agent governance layer.

**Milestone 1 scope:** the vertical slice. One customer message travels all
the way from the API, through the agent loop, through the governance engine,
into a tool, and out to an audit log — and is correctly refused when it
should be.

RAG, the approval queue UI, the remaining tools and the React frontend
arrive in later milestones.

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
Python's `ast` module and fails the build if any of them imports `app.tools`.
A permission check the agent could skip by importing a function directly
would be theatre.

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
notepad .env        # paste your ANTHROPIC_API_KEY
```

> **An Anthropic (Claude.ai) subscription is not API access.** You need
> prepaid credits at `console.anthropic.com`. $5 covers all of development
> on `claude-haiku-5-5` ($0.10 / $0.50 per million tokens) plus a demo
> recording on `claude-sonnet-5-5` ($2 / $10).

### Run the tests (no API key needed)

```powershell
python -m pytest -q
```

The suite runs against in-memory SQLite with a scripted fake LLM: no
network, no cost, deterministic.

### Run the server

```powershell
uvicorn app.main:app --reload
```

- Health check: http://127.0.0.1:8000/api/health
- Interactive API docs: http://127.0.0.1:8000/docs

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
| `test_sessions_are_isolated` | One customer cannot read another's history |
| `test_blocked_tool_is_reported_to_the_model_not_executed` | The model is told, and still cannot act |

## Known gaps (deliberate, not forgotten)

- **Approval queue** — HIGH-risk actions are blocked and audited as
  `pending_approval`, but there is no `action_requests` row or admin
  endpoint yet. Milestone 2.
- **Admin authentication** — no auth on admin routes yet, because there are
  no admin routes yet. Milestone 2 adds JWT + role checks before the first
  one ships.
- **RAG** — Milestone 3.
- **Context trimming** is by message count, not token budget.
