"""Failure injection: what survives an interrupted execution.

These tests exist to make a precise claim testable: execution is
**at-most-once with bounded recovery**, not exactly-once.

Three distinct failure modes are simulated:

  A. the tool raises              -> except clause runs, rollback, FAILED
  B. the process dies mid-flight  -> no except clause runs at all
  C. the process dies after the business commit, before the audit write

Mode B is the one that matters, and it cannot be simulated by raising an
exception, because raising still runs our error handling. It is simulated
by constructing the exact database state a dead process would leave behind.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.governance import recovery
from app.governance.action_requests import mark_approved
from app.governance.approvals import execute_approved
from app.governance.recovery import (
    MAX_EXECUTION_ATTEMPTS, find_stranded_requests, find_unaudited_executions,
    run_recovery,
)
from app.models import ActionRequest, Appointment, AuditLog
from app.models.enums import (
    ActionRequestStatus, AppointmentStatus, AuditEventType, Outcome,
)
from app.tools.appointments import ToolExecutionError
from app.tools.registry import TOOL_REGISTRY, ToolSpec


def _patch_impl(monkeypatch, fn):
    spec = TOOL_REGISTRY["cancel_appointment"]
    monkeypatch.setitem(
        TOOL_REGISTRY, "cancel_appointment",
        ToolSpec(definition=spec.definition, impl=fn),
    )


def _strand(db, request_id: int, *, seconds_ago: int = 600, attempts: int = 1) -> None:
    """Reproduce the state a crashed process leaves behind.

    EXECUTING, claimed a while back, and -- crucially -- the business change
    NOT committed, because the engine performs both in one transaction.
    """
    row = db.get(ActionRequest, request_id)
    row.status = ActionRequestStatus.EXECUTING
    row.execution_started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    row.execution_attempts = attempts
    db.commit()


# ==========================================================================
# Mode A: the tool raises after mutating
# ==========================================================================
def test_tool_failure_rolls_back_the_business_change(db, admin_user, pending_request, booked_appointment, monkeypatch):
    def mutate_then_fail(session, params):
        appt = session.get(Appointment, params.appointment_id)
        appt.status = AppointmentStatus.CANCELLED   # partial work
        session.flush()
        raise ToolExecutionError("downstream calendar rejected the change")

    _patch_impl(monkeypatch, mutate_then_fail)
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)

    result = execute_approved(db, pending_request.id)

    assert result.outcome is Outcome.ERROR
    db.expire_all()
    assert db.get(Appointment, booked_appointment.id).status is AppointmentStatus.BOOKED
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.FAILED


def test_tool_failure_is_still_audited(db, admin_user, pending_request, monkeypatch):
    def boom(session, params):
        raise ToolExecutionError("nope")

    _patch_impl(monkeypatch, boom)
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    execute_approved(db, pending_request.id)

    row = (
        db.query(AuditLog)
        .filter(
            AuditLog.action_request_id == pending_request.id,
            AuditLog.event_type == AuditEventType.EXECUTION,
        ).one()
    )
    assert row.outcome is Outcome.ERROR
    assert "nope" in row.error_message


# ==========================================================================
# Mode B: the process dies mid-flight
# ==========================================================================
def test_interrupted_execution_leaves_no_business_change(db, admin_user, pending_request, booked_appointment, monkeypatch):
    """A failure between the tool's flush and the commit must change nothing.

    This is the property the single-transaction design buys. If the tool
    committed on its own, the appointment would already be cancelled here.
    """
    def explode_before_commit(session, request_id, result, *, commit=True):
        raise RuntimeError("process interrupted before commit")

    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    monkeypatch.setattr(
        "app.governance.engine.mark_executed", explode_before_commit
    )

    result = execute_approved(db, pending_request.id)

    assert result.outcome is Outcome.ERROR
    db.expire_all()
    assert db.get(Appointment, booked_appointment.id).status is AppointmentStatus.BOOKED


def test_stranded_request_is_found(db, admin_user, pending_request):
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    _strand(db, pending_request.id)

    stranded = find_stranded_requests(db)
    assert [r.id for r in stranded] == [pending_request.id]


def test_recently_claimed_request_is_left_alone(db, admin_user, pending_request):
    """Recovery must not fight a worker that is still running."""
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    _strand(db, pending_request.id, seconds_ago=5)

    assert find_stranded_requests(db) == []
    report = run_recovery(db)
    assert report.recovered == []


def test_recovery_returns_stranded_request_to_approved(db, admin_user, pending_request, booked_appointment):
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    _strand(db, pending_request.id)

    report = run_recovery(db)

    assert report.recovered == [pending_request.id]
    db.expire_all()
    row = db.get(ActionRequest, pending_request.id)
    assert row.status is ActionRequestStatus.APPROVED
    assert row.execution_started_at is None
    # Recovery does not re-run the action by itself.
    assert db.get(Appointment, booked_appointment.id).status is AppointmentStatus.BOOKED


def test_recovered_request_executes_exactly_once(db, admin_user, pending_request, booked_appointment):
    """The headline claim: interrupted, recovered, retried, performed once."""
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    _strand(db, pending_request.id)
    run_recovery(db)

    result = execute_approved(db, pending_request.id)
    assert result.outcome is Outcome.EXECUTED

    db.expire_all()
    assert db.get(Appointment, booked_appointment.id).status is AppointmentStatus.CANCELLED
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.EXECUTED

    executions = (
        db.query(AuditLog)
        .filter(
            AuditLog.action_request_id == pending_request.id,
            AuditLog.event_type == AuditEventType.EXECUTION,
            AuditLog.outcome == Outcome.EXECUTED,
        ).count()
    )
    assert executions == 1


def test_repeatedly_interrupted_request_is_abandoned_not_retried_forever(db, admin_user, pending_request, booked_appointment):
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    _strand(db, pending_request.id, attempts=MAX_EXECUTION_ATTEMPTS)

    report = run_recovery(db)

    assert report.abandoned == [pending_request.id]
    assert report.recovered == []
    db.expire_all()
    row = db.get(ActionRequest, pending_request.id)
    assert row.status is ActionRequestStatus.FAILED
    assert "human review" in row.error_message
    assert db.get(Appointment, booked_appointment.id).status is AppointmentStatus.BOOKED


def test_recovery_is_audited(db, admin_user, pending_request):
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    _strand(db, pending_request.id)
    run_recovery(db)

    row = (
        db.query(AuditLog)
        .filter(
            AuditLog.action_request_id == pending_request.id,
            AuditLog.event_type == AuditEventType.EXECUTION,
        ).one()
    )
    assert "interrupted" in row.error_message


def test_recovery_sweep_is_idempotent(db, admin_user, pending_request):
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    _strand(db, pending_request.id)

    first = run_recovery(db)
    second = run_recovery(db)

    assert first.recovered == [pending_request.id]
    assert second.recovered == []


# ==========================================================================
# Mode C: crash after the business commit, before the audit write
# ==========================================================================
def test_execution_without_audit_row_is_detected(db, admin_user, pending_request, booked_appointment, monkeypatch):
    """The window that cannot be closed. It must at least be visible."""
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)

    real_audit = recovery.write_audit

    def die_after_commit(*args, **kwargs):
        if kwargs.get("event_type") is AuditEventType.EXECUTION:
            raise RuntimeError("process died before the audit row was written")
        return real_audit(*args, **kwargs)

    monkeypatch.setattr("app.governance.engine.write_audit", die_after_commit)

    with pytest.raises(RuntimeError):
        execute_approved(db, pending_request.id)

    db.expire_all()
    # The business change and the status transition committed together.
    assert db.get(Appointment, booked_appointment.id).status is AppointmentStatus.CANCELLED
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.EXECUTED

    # But there is no EXECUTION audit row, and reconciliation says so.
    unaudited = find_unaudited_executions(db)
    assert [r.id for r in unaudited] == [pending_request.id]
    assert run_recovery(db).unaudited == [pending_request.id]


def test_reconciliation_reports_but_never_fabricates_audit_rows(db, admin_user, pending_request, monkeypatch):
    """Inventing the missing row would record an observation nobody made."""
    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)

    real_audit = recovery.write_audit

    def die_after_commit(*args, **kwargs):
        if kwargs.get("event_type") is AuditEventType.EXECUTION:
            raise RuntimeError("died")
        return real_audit(*args, **kwargs)

    monkeypatch.setattr("app.governance.engine.write_audit", die_after_commit)
    with pytest.raises(RuntimeError):
        execute_approved(db, pending_request.id)

    before = db.query(AuditLog).count()
    find_unaudited_executions(db)
    find_unaudited_executions(db)
    assert db.query(AuditLog).count() == before


def test_clean_system_reports_nothing_to_recover(db, admin_user, pending_request, booked_appointment):
    from app.governance.approvals import approve_and_execute

    approve_and_execute(
        db, pending_request, admin=admin_user,
        expected_params_hash=pending_request.params_hash,
    )
    report = run_recovery(db)
    assert report.is_clean
