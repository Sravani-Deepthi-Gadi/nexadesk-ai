"""Crash recovery and audit reconciliation.

WHAT GUARANTEE DO WE ACTUALLY HAVE?

Execution is **at-most-once, with bounded recovery**. It is NOT exactly-once,
and this module does not pretend otherwise.

The engine commits the business change and the EXECUTING -> EXECUTED
transition in a single transaction. Everything follows from that:

    crash before that commit  ->  no business change, row still EXECUTING
    crash after that commit   ->  business change done, row says EXECUTED

So a row found in EXECUTING after a restart PROVES the action did not
happen, and can be safely returned to APPROVED and retried.

THE ASSUMPTION THAT CARRIES ALL OF THIS: tool implementations have no
side effects outside the database transaction. They flush, they never
commit, and they do not call external APIs, send email or charge cards.
tests/test_import_boundary.py enforces the "never commit" half mechanically.
The "no external side effects" half is a design rule, and the moment a tool
calls a real booking system it is false -- at which point retrying a
stranded request could double-book, and that tool needs an idempotency key
carried to the remote system instead. Do not add such a tool without
revisiting this module.

THE WINDOW THAT CANNOT BE CLOSED: between the business commit and the
EXECUTION audit write. A crash there leaves a genuinely executed action
with no EXECUTION audit row. Closing it needs two-phase commit across the
audit store. `find_unaudited_executions` DETECTS it. It deliberately does
not write the missing row: reconstructing audit evidence after the fact
produces a record that says something was observed when it was not.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.governance.action_requests import ActionRequestConflict, _transition
from app.governance.audit import write_audit
from app.models import ActionRequest, AuditLog
from app.models.enums import (
    ActionRequestStatus, ApprovalStatus, AuditEventType, Outcome,
)

#: A request claimed longer ago than this with no outcome is presumed
#: stranded by a crash. Must comfortably exceed the slowest legitimate
#: tool execution, or recovery will fight a worker that is still running.
STRANDED_AFTER_SECONDS = 300

#: Give up and park for a human after this many attempts. A request that
#: reliably kills the process should not be retried forever.
MAX_EXECUTION_ATTEMPTS = 3


@dataclass
class RecoveryReport:
    recovered: list[int]
    abandoned: list[int]
    unaudited: list[int]

    @property
    def is_clean(self) -> bool:
        return not (self.recovered or self.abandoned or self.unaudited)


def find_stranded_requests(
    db: Session, *, older_than_seconds: int = STRANDED_AFTER_SECONDS
) -> list[ActionRequest]:
    """Requests stuck in EXECUTING, i.e. claimed but never finished."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    rows = (
        db.query(ActionRequest)
        .filter(ActionRequest.status == ActionRequestStatus.EXECUTING)
        .all()
    )
    out = []
    for row in rows:
        started = row.execution_started_at
        if started is None:
            out.append(row)
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if started <= cutoff:
            out.append(row)
    return out


def find_unaudited_executions(db: Session) -> list[ActionRequest]:
    """EXECUTED requests with no EXECUTION audit row.

    The residual crash window. Reported, never silently repaired.
    """
    audited = {
        r.action_request_id
        for r in db.query(AuditLog)
        .filter(
            AuditLog.event_type == AuditEventType.EXECUTION,
            AuditLog.outcome == Outcome.EXECUTED,
        ).all()
        if r.action_request_id is not None
    }
    return [
        row
        for row in db.query(ActionRequest)
        .filter(ActionRequest.status == ActionRequestStatus.EXECUTED).all()
        if row.id not in audited
    ]


def recover_stranded_request(db: Session, request: ActionRequest) -> str:
    """Return one stranded request to APPROVED, or park it as FAILED.

    Returns "recovered" or "abandoned". Safe because EXECUTING implies the
    business transaction never committed -- see the module docstring for
    the assumption this rests on.
    """
    if request.execution_attempts >= MAX_EXECUTION_ATTEMPTS:
        try:
            _transition(
                db, request.id,
                expected_from=ActionRequestStatus.EXECUTING,
                to=ActionRequestStatus.FAILED,
                executed_at=datetime.now(timezone.utc),
                error_message=(
                    f"Abandoned after {request.execution_attempts} interrupted "
                    "attempts. Needs human review."
                ),
            )
        except ActionRequestConflict:
            return "abandoned"
        outcome, verb = Outcome.ERROR, "abandoned"
    else:
        try:
            _transition(
                db, request.id,
                expected_from=ActionRequestStatus.EXECUTING,
                to=ActionRequestStatus.APPROVED,
                execution_started_at=None,
            )
        except ActionRequestConflict:
            return "recovered"
        outcome, verb = Outcome.PENDING_APPROVAL, "recovered"

    write_audit(
        db,
        agent_id=request.agent_id,
        conversation_id=request.conversation_id,
        tool_name=request.tool_name,
        params=None,
        risk_level=request.risk_level,
        permission_result=None,
        approval_status=ApprovalStatus.APPROVED,
        outcome=outcome,
        error_message=(
            f"Execution interrupted; request {verb} "
            f"(attempt {request.execution_attempts})."
        ),
        event_type=AuditEventType.EXECUTION,
        action_request_id=request.id,
    )
    return verb


def run_recovery(
    db: Session, *, older_than_seconds: int = STRANDED_AFTER_SECONDS
) -> RecoveryReport:
    """Sweep for interrupted work. Call on startup and on a schedule.

    Recovered requests return to APPROVED; they are not auto-executed here,
    so a human-approved action is never re-run by a background sweep
    without something explicitly choosing to.
    """
    recovered: list[int] = []
    abandoned: list[int] = []

    for request in find_stranded_requests(db, older_than_seconds=older_than_seconds):
        attempts = request.execution_attempts
        request_id = request.id
        if recover_stranded_request(db, request) == "recovered":
            recovered.append(request_id)
        else:
            abandoned.append(request_id)
        del attempts

    return RecoveryReport(
        recovered=recovered,
        abandoned=abandoned,
        unaudited=[r.id for r in find_unaudited_executions(db)],
    )
