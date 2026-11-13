"""Governance engine: the four checks that must never regress."""
import json

import pytest

from app.governance.engine import GovernanceEngine
from app.governance.kill_switch import set_agent_status
from app.models import AuditLog
from app.models.enums import (
    AgentStatus, ApprovalStatus, AppointmentStatus, Outcome, Permission,
    PermissionResult, RiskLevel,
)
from tests.conftest import grant


def last_audit(db) -> AuditLog:
    return db.query(AuditLog).order_by(AuditLog.id.desc()).first()


# --------------------------------------------------------------------------
def test_permitted_low_risk_tool_executes_and_is_audited(db, agent):
    engine = GovernanceEngine(db, agent_id=agent.id)
    result = engine.execute("search_services", {})

    assert result.outcome is Outcome.EXECUTED
    assert result.data["count"] == 4
    assert any(s["name"] == "Compliance Review" for s in result.data["services"])

    entry = last_audit(db)
    assert entry.tool_name == "search_services"
    assert entry.outcome is Outcome.EXECUTED
    assert entry.permission_result is PermissionResult.PASS
    assert entry.risk_level is RiskLevel.LOW
    assert entry.approval_status is ApprovalStatus.NOT_REQUIRED


def test_missing_permission_blocks_and_does_not_mutate_data(db, agent, booked_appointment):
    """The seeded agent has no CANCEL_APPOINTMENT permission.

    This is the test that proves the engine is not decorative: afterwards the
    appointment must still be BOOKED.
    """
    engine = GovernanceEngine(db, agent_id=agent.id)
    result = engine.execute(
        "cancel_appointment", {"appointment_id": booked_appointment.id}
    )

    assert result.outcome is Outcome.BLOCKED
    assert not result.allowed

    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED
    assert booked_appointment.cancelled_at is None

    entry = last_audit(db)
    assert entry.permission_result is PermissionResult.FAIL
    assert entry.outcome is Outcome.BLOCKED
    assert "CANCEL_APPOINTMENT" in entry.error_message


def test_high_risk_with_permission_still_withholds_execution(db, agent, booked_appointment):
    """Permission alone is not enough for a HIGH-risk action."""
    grant(db, agent, Permission.CANCEL_APPOINTMENT)

    engine = GovernanceEngine(db, agent_id=agent.id)
    result = engine.execute(
        "cancel_appointment", {"appointment_id": booked_appointment.id}
    )

    assert result.outcome is Outcome.PENDING_APPROVAL

    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED

    entry = last_audit(db)
    assert entry.permission_result is PermissionResult.PASS
    assert entry.approval_status is ApprovalStatus.PENDING
    assert entry.risk_level is RiskLevel.HIGH


def test_unknown_tool_is_blocked_and_audited(db, agent):
    engine = GovernanceEngine(db, agent_id=agent.id)
    result = engine.execute("delete_all_customers", {"confirm": True})

    assert result.outcome is Outcome.BLOCKED
    entry = last_audit(db)
    assert entry.tool_name == "delete_all_customers"
    assert "Unknown tool" in entry.error_message
    # Parameters of a rejected call are still recorded.
    assert json.loads(entry.params_json) == {"confirm": True}


def test_emergency_stop_blocks_even_a_permitted_tool(db, agent):
    engine = GovernanceEngine(db, agent_id=agent.id)
    assert engine.execute("search_services", {}).outcome is Outcome.EXECUTED

    set_agent_status(db, agent.id, AgentStatus.DISABLED)

    result = engine.execute("search_services", {})
    assert result.outcome is Outcome.BLOCKED
    entry = last_audit(db)
    assert "disabled" in entry.error_message.lower()


def test_invalid_parameters_are_rejected_before_execution(db, agent):
    grant(db, agent, Permission.CANCEL_APPOINTMENT)
    engine = GovernanceEngine(db, agent_id=agent.id)
    # appointment_id is required and must be an int.
    result = engine.execute("cancel_appointment", {"appointment_id": "not-a-number"})
    assert result.outcome is Outcome.BLOCKED
    assert "Invalid parameters" in last_audit(db).error_message


def test_audit_rows_cannot_be_modified(db, agent):
    from app.governance.audit import AuditImmutabilityError

    engine = GovernanceEngine(db, agent_id=agent.id)
    engine.execute("search_services", {})
    entry = last_audit(db)

    entry.outcome = Outcome.EXECUTED
    entry.error_message = "tampered"
    with pytest.raises(AuditImmutabilityError):
        db.commit()
    db.rollback()
