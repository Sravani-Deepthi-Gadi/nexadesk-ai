# Execution guarantees, crash recovery and audit consistency

## The claim, stated precisely

Execution of an approved action is **at-most-once, with bounded recovery.**

It is **not** exactly-once, and nothing in this codebase should be read as
claiming that it is. Exactly-once across a database and a separate audit
write requires two-phase commit, which this system does not have.

What *is* guaranteed:

| Property | Guaranteed? | Mechanism |
|---|---|---|
| An approved action never runs twice | **Yes** | `APPROVED → EXECUTING` is an atomic conditional UPDATE; only one caller wins |
| A rejected action never runs | **Yes** | `REJECTED` is terminal; no transition leads out of it |
| A crash never leaves a half-applied business change | **Yes** | The business change and `EXECUTING → EXECUTED` commit together |
| After a crash we can tell whether the action happened | **Yes** | See the decidability argument below |
| Interrupted work is retried | **Yes, up to 3 attempts** | `run_recovery()` returns stranded requests to `APPROVED` |
| Every executed action has an audit row | **No** | One residual window, detected but not closed |

## Transaction boundaries

```
commit 1   claim_for_execution        APPROVED -> EXECUTING
                                      (+ execution_started_at, attempts += 1)

commit 2   ── ATOMIC UNIT ───────────────────────────────────────
           spec.impl(db, params)      business change, flush() only
           mark_executed(commit=False) EXECUTING -> EXECUTED
           db.commit()                 both, or neither
           ───────────────────────────────────────────────────────

commit 3   write_audit                 EXECUTION row
```

Tool implementations **must not commit**. They flush, so their work is
visible inside the caller's transaction, and the engine commits.
`tests/test_import_boundary.py::test_tool_implementations_never_commit`
parses `app/tools/` and fails the build if a tool calls `.commit()`.

## Why recovery is decidable

Because the business change and the status transition are one commit:

- **Crash before commit 2** → neither landed. The row is still `EXECUTING`
  and the appointment was never cancelled.
- **Crash after commit 2** → both landed. The row says `EXECUTED`.

Therefore a row found in `EXECUTING` after a restart **proves the action
did not happen**, and can safely be returned to `APPROVED` and retried.
That inference is the entire basis of `app/governance/recovery.py`.

### The assumption this rests on

**Tool implementations have no side effects outside the database
transaction.** No external API calls, no emails, no card charges.

The "never commit" half is enforced mechanically. The "no external side
effects" half is a design rule that no test can check. The moment a tool
calls a real booking system, the inference above becomes false: a request
stranded in `EXECUTING` might have already booked the remote slot, and
retrying it would double-book.

**If you add such a tool, this module must change first.** That tool needs
an idempotency key sent to the remote system, so the retry is deduplicated
there rather than here.

## The window that cannot be closed

Between commit 2 and commit 3, an action has genuinely executed but has no
`EXECUTION` audit row. A crash there produces a real gap in the trail.

`find_unaudited_executions()` detects it: `EXECUTED` requests with no
matching audit row. `run_recovery()` reports them in `report.unaudited`,
and the app logs a warning at startup when the list is non-empty.

**It deliberately does not write the missing row.** Reconstructing audit
evidence after the fact produces a record asserting that something was
observed when nobody observed it. A gap an operator can see is better than
a plausible fabrication. `test_reconciliation_reports_but_never_fabricates_audit_rows`
pins that behaviour.

## Audit consistency under failure

| Failure point | Business change | Request status | Audit |
|---|---|---|---|
| Tool raises | Rolled back | `FAILED` | `EXECUTION` / `error` ✓ |
| Pre-check refuses (tampered params, kill switch, revoked permission) | None | `FAILED` | `EXECUTION` / `blocked` ✓ |
| Crash during commit 2 | Rolled back | `EXECUTING` → recovered to `APPROVED` | Recovery row written on sweep ✓ |
| Crash between commits 2 and 3 | **Applied** | `EXECUTED` | **Missing** — detected by reconciliation |
| Crash after commit 3 | Applied | `EXECUTED` | Complete ✓ |
| Audit write itself fails on an error path | Rolled back | `FAILED` | Missing; the error propagates to the caller |

Failure-path audit rows are written **after** `db.rollback()`, on purpose.
Writing them before would mean the rollback discarded the very record of
the failure.

Approval decisions are safe in a different way: `mark_approved` commits
before the audit write, so a crash between them leaves an approved request
with no `APPROVAL_DECISION` row — but the request still carries
`decided_by_admin_id` and `decided_at`, so the decision and its author are
never lost, only the trail entry.

## Known remaining limitations

1. **`STRANDED_AFTER_SECONDS` is a guess** (300s). Set below the slowest
   legitimate tool execution, recovery will fight a worker that is still
   running and retry a live action. There is no heartbeat or worker lease;
   with real background workers you want one.
2. **No distributed locking.** Two application instances running
   `run_recovery()` simultaneously are safe — the transitions are atomic and
   the loser gets a conflict — but both will do the scan.
3. **Recovery does not re-execute.** Recovered requests sit in `APPROVED`
   until something executes them. That is deliberate (a restart should
   never silently re-run a human-approved action) but it means recovery is
   not fully automatic.
4. **`MAX_EXECUTION_ATTEMPTS` abandonment is terminal.** A request
   abandoned after three interrupted attempts becomes `FAILED` and needs a
   fresh request; there is no "unabandon" path.
5. **`db.rollback()` on the shared session** discards any other uncommitted
   work on that session. Safe today because each request gets its own
   session, but it is a landmine if sessions are ever shared across
   concurrent work.
