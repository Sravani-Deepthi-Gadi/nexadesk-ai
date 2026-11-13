"""Milestone 2: approval workflow, auth, and the guarantees around them."""
import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm
from app.db.session import get_db
from app.governance import approvals as approval_service
from app.governance.action_requests import (
    ActionRequestConflict, compute_params_hash,
)
from app.governance.approvals import approve_and_execute, execute_approved, reject
from app.governance.kill_switch import set_agent_status
from app.main import app
from app.models import ActionRequest, AuditLog
from app.models.enums import (
    ActionRequestStatus, AgentStatus, AppointmentStatus, AuditEventType,
    Outcome, Permission,
)
from app.security.tokens import create_access_token
from tests.conftest import FakeLLM, auth, grant, token_for


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_llm] = lambda: FakeLLM([])
    yield TestClient(app)
    app.dependency_overrides.clear()


# ==========================================================================
# 1. Pending approval creation
# ==========================================================================
def test_high_risk_action_creates_pending_request(db, pending_request, booked_appointment):
    assert pending_request.status is ActionRequestStatus.PENDING
    assert pending_request.tool_name == "cancel_appointment"
    assert json.loads(pending_request.params_json)["appointment_id"] == booked_appointment.id
    assert pending_request.tool_use_id == "tu_cancel_1"
    assert len(pending_request.params_hash) == 64

    # Nothing has happened to the appointment.
    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_pending_request_is_listed_for_admin(client, db, admin_user, pending_request):
    resp = client.get("/api/admin/approvals/pending", headers=auth(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == pending_request.id
    assert body[0]["status"] == "pending"
    assert body[0]["params_hash"] == pending_request.params_hash


# ==========================================================================
# 2. Successful approval -> execution
# ==========================================================================
def test_approval_executes_the_action(client, db, admin_user, pending_request, booked_appointment):
    resp = client.post(
        f"/api/admin/approvals/{pending_request.id}/approve",
        json={"params_hash": pending_request.params_hash, "note": "Customer confirmed"},
        headers=auth(admin_user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["request"]["status"] == "executed"
    assert body["execution_outcome"] == "executed"
    assert body["request"]["decided_by_admin_id"] == admin_user.id
    assert body["request"]["result"]["status"] == "cancelled"

    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.CANCELLED
    assert booked_appointment.cancelled_at is not None


# ==========================================================================
# 3. Rejection -> never executes
# ==========================================================================
def test_rejection_never_executes(client, db, admin_user, pending_request, booked_appointment):
    resp = client.post(
        f"/api/admin/approvals/{pending_request.id}/reject",
        json={"params_hash": pending_request.params_hash, "note": "Outside policy"},
        headers=auth(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["request"]["status"] == "rejected"
    assert resp.json()["execution_outcome"] is None

    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_rejected_request_cannot_be_executed_afterwards(db, admin_user, pending_request, booked_appointment):
    reject(db, pending_request, admin=admin_user,
           expected_params_hash=pending_request.params_hash, note="no")

    # There is no API route to execute directly; call the service to prove
    # that even internal misuse cannot run a rejected action.
    with pytest.raises(ActionRequestConflict):
        execute_approved(db, pending_request.id)

    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_rejected_request_cannot_then_be_approved(db, admin_user, pending_request):
    reject(db, pending_request, admin=admin_user,
           expected_params_hash=pending_request.params_hash)
    db.expire_all()
    row = db.get(ActionRequest, pending_request.id)
    with pytest.raises(ActionRequestConflict):
        approve_and_execute(
            db, row, admin=admin_user, expected_params_hash=row.params_hash
        )


# ==========================================================================
# 4. Unauthorised admin access
# ==========================================================================
def test_no_token_is_rejected(client, pending_request):
    assert client.get("/api/admin/approvals/pending").status_code == 401
    resp = client.post(
        f"/api/admin/approvals/{pending_request.id}/approve",
        json={"params_hash": pending_request.params_hash},
    )
    assert resp.status_code == 401


def test_viewer_may_read_but_not_decide(client, db, viewer_user, pending_request, booked_appointment):
    assert client.get(
        "/api/admin/approvals/pending", headers=auth(viewer_user)
    ).status_code == 200

    resp = client.post(
        f"/api/admin/approvals/{pending_request.id}/approve",
        json={"params_hash": pending_request.params_hash},
        headers=auth(viewer_user),
    )
    assert resp.status_code == 403

    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_deactivated_admin_token_stops_working(client, db, admin_user, pending_request):
    header = auth(admin_user)
    assert client.get("/api/admin/approvals/pending", headers=header).status_code == 200

    admin_user.is_active = False
    db.commit()

    # Same still-valid token, but the user row is re-checked on every request.
    assert client.get("/api/admin/approvals/pending", headers=header).status_code == 401


def test_role_escalation_in_token_is_ignored(client, db, viewer_user, pending_request):
    """A forged-but-correctly-signed token claiming admin must not work."""
    from app.config import get_settings

    token = create_access_token(
        subject_id=viewer_user.id, email=viewer_user.email, role="admin",
        secret=get_settings().jwt_secret, expires_minutes=60,
    )
    resp = client.post(
        f"/api/admin/approvals/{pending_request.id}/approve",
        json={"params_hash": pending_request.params_hash},
        headers={"Authorization": f"Bearer {token}"},
    )
    # The role is re-read from the database, not taken from the token.
    assert resp.status_code == 403


# ==========================================================================
# 5. Invalid JWT
# ==========================================================================
@pytest.mark.parametrize("token", ["not-a-jwt", "", "a.b.c"])
def test_malformed_tokens_are_rejected(client, token):
    resp = client.get(
        "/api/admin/approvals/pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


def test_token_signed_with_another_secret_is_rejected(client, admin_user):
    forged = create_access_token(
        subject_id=admin_user.id, email=admin_user.email, role="admin",
        secret="an-entirely-different-secret-value-xxxxx", expires_minutes=60,
    )
    resp = client.get(
        "/api/admin/approvals/pending",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401


def test_expired_token_is_rejected(client, admin_user):
    expired = token_for(admin_user, expires_minutes=-5)
    resp = client.get(
        "/api/admin/approvals/pending",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401


def test_login_issues_a_working_token(client, db, admin_user):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": admin_user.email, "password": "correct-horse-battery"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert resp.json()["role"] == "admin"

    me = client.get("/api/admin/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == admin_user.email


def test_login_with_wrong_password_is_rejected(client, admin_user):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": admin_user.email, "password": "wrong"},
    )
    assert resp.status_code == 401


def test_login_does_not_reveal_whether_an_email_exists(client, admin_user):
    unknown = client.post(
        "/api/admin/auth/login",
        json={"email": "nobody@nexacare.co", "password": "whatever"},
    )
    wrong_pw = client.post(
        "/api/admin/auth/login",
        json={"email": admin_user.email, "password": "whatever"},
    )
    assert unknown.status_code == wrong_pw.status_code == 401
    assert unknown.json()["detail"] == wrong_pw.json()["detail"]


# ==========================================================================
# 6. Modified action parameters
# ==========================================================================
def test_approval_with_stale_params_hash_is_refused(client, db, admin_user, pending_request, booked_appointment):
    resp = client.post(
        f"/api/admin/approvals/{pending_request.id}/approve",
        json={"params_hash": "0" * 64},
        headers=auth(admin_user),
    )
    assert resp.status_code == 409

    db.expire_all()
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.PENDING
    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_params_tampered_after_approval_are_not_executed(db, admin_user, pending_request, booked_appointment):
    """Someone edits params_json in the database between approval and execution."""
    from app.governance.action_requests import mark_approved

    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)

    db.expire_all()
    row = db.get(ActionRequest, pending_request.id)
    row.params_json = json.dumps({"appointment_id": 9999, "reason": "tampered"})
    db.commit()

    result = execute_approved(db, row.id)

    assert result.outcome is Outcome.BLOCKED
    assert "could not be verified" in result.message
    db.expire_all()
    assert db.get(ActionRequest, row.id).status is ActionRequestStatus.FAILED
    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_params_hash_detects_any_value_change():
    base = compute_params_hash("cancel_appointment", {"appointment_id": 1, "reason": "x"})
    assert base != compute_params_hash("cancel_appointment", {"appointment_id": 2, "reason": "x"})
    assert base != compute_params_hash("book_appointment", {"appointment_id": 1, "reason": "x"})
    # Key order must not matter.
    assert base == compute_params_hash("cancel_appointment", {"reason": "x", "appointment_id": 1})


# ==========================================================================
# 7 & 8. Duplicate approval and duplicate execution
# ==========================================================================
def test_duplicate_approval_is_refused(client, db, admin_user, pending_request):
    payload = {"params_hash": pending_request.params_hash}
    first = client.post(
        f"/api/admin/approvals/{pending_request.id}/approve",
        json=payload, headers=auth(admin_user),
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/admin/approvals/{pending_request.id}/approve",
        json=payload, headers=auth(admin_user),
    )
    assert second.status_code == 409
    assert "executed" in second.json()["detail"]


def test_duplicate_execution_is_impossible(db, admin_user, pending_request, booked_appointment):
    approve_and_execute(
        db, pending_request, admin=admin_user,
        expected_params_hash=pending_request.params_hash,
    )

    db.expire_all()
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.EXECUTED

    # A second execution attempt cannot claim an already-executed request.
    with pytest.raises(ActionRequestConflict):
        execute_approved(db, pending_request.id)

    # And the appointment was cancelled exactly once.
    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.CANCELLED
    cancellations = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type == AuditEventType.EXECUTION,
            AuditLog.outcome == Outcome.EXECUTED,
            AuditLog.action_request_id == pending_request.id,
        ).count()
    )
    assert cancellations == 1


def test_approval_after_rejection_loses_the_race(db, admin_user, pending_request):
    """Simulates two admins deciding at the same moment: first write wins."""
    from app.governance.action_requests import mark_approved, mark_rejected

    mark_rejected(db, pending_request.id, admin_user_id=admin_user.id)
    with pytest.raises(ActionRequestConflict):
        mark_approved(db, pending_request.id, admin_user_id=admin_user.id)


# ==========================================================================
# 9. Approval is not a bypass of governance
# ==========================================================================
def test_emergency_stop_after_approval_blocks_execution(db, agent, admin_user, pending_request, booked_appointment):
    from app.governance.action_requests import mark_approved

    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)
    set_agent_status(db, agent.id, AgentStatus.DISABLED)

    result = execute_approved(db, pending_request.id)

    assert result.outcome is Outcome.BLOCKED
    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_permission_revoked_after_approval_blocks_execution(db, agent, admin_user, pending_request, booked_appointment):
    from app.governance.action_requests import mark_approved
    from app.models import AgentPermission

    mark_approved(db, pending_request.id, admin_user_id=admin_user.id)

    perm = (
        db.query(AgentPermission)
        .filter(
            AgentPermission.agent_id == agent.id,
            AgentPermission.permission == Permission.CANCEL_APPOINTMENT,
        ).one()
    )
    perm.granted = False
    db.commit()

    result = execute_approved(db, pending_request.id)
    assert result.outcome is Outcome.BLOCKED
    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


# ==========================================================================
# 10. Audit logging across the whole lifecycle
# ==========================================================================
def test_full_lifecycle_produces_three_linked_audit_rows(db, admin_user, pending_request):
    approve_and_execute(
        db, pending_request, admin=admin_user,
        expected_params_hash=pending_request.params_hash, note="ok",
    )

    rows = (
        db.query(AuditLog)
        .filter(AuditLog.action_request_id == pending_request.id)
        .order_by(AuditLog.id)
        .all()
    )
    assert [r.event_type for r in rows] == [
        AuditEventType.TOOL_INVOCATION,
        AuditEventType.APPROVAL_DECISION,
        AuditEventType.EXECUTION,
    ]
    assert rows[0].outcome is Outcome.PENDING_APPROVAL
    assert rows[0].admin_user_id is None          # the agent proposed it
    assert rows[1].outcome is Outcome.APPROVED
    assert rows[1].admin_user_id == admin_user.id  # a human decided it
    assert rows[2].outcome is Outcome.EXECUTED


def test_rejection_is_audited(db, admin_user, pending_request):
    reject(
        db, pending_request, admin=admin_user,
        expected_params_hash=pending_request.params_hash, note="against policy",
    )
    row = (
        db.query(AuditLog)
        .filter(
            AuditLog.action_request_id == pending_request.id,
            AuditLog.event_type == AuditEventType.APPROVAL_DECISION,
        ).one()
    )
    assert row.outcome is Outcome.REJECTED
    assert row.admin_user_id == admin_user.id
    assert row.error_message == "against policy"


def test_audit_endpoint_filters_by_action_request(client, db, admin_user, pending_request):
    approve_and_execute(
        db, pending_request, admin=admin_user,
        expected_params_hash=pending_request.params_hash,
    )
    resp = client.get(
        f"/api/admin/audit?action_request_id={pending_request.id}",
        headers=auth(admin_user),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_audit_rows_remain_append_only_after_approval(db, admin_user, pending_request):
    from app.governance.audit import AuditImmutabilityError

    approve_and_execute(
        db, pending_request, admin=admin_user,
        expected_params_hash=pending_request.params_hash,
    )
    row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    row.error_message = "tampered"
    with pytest.raises(AuditImmutabilityError):
        db.commit()
    db.rollback()


# ==========================================================================
# 11. Hash verification is mandatory (hardening pass)
# ==========================================================================
def test_approve_without_hash_is_a_type_error(db, admin_user, pending_request, booked_appointment):
    """No internal path can skip verification: the argument has no default."""
    with pytest.raises(TypeError, match="expected_params_hash"):
        approve_and_execute(db, pending_request, admin=admin_user)  # type: ignore[call-arg]

    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


def test_reject_without_hash_is_a_type_error(db, admin_user, pending_request):
    with pytest.raises(TypeError, match="expected_params_hash"):
        reject(db, pending_request, admin=admin_user)  # type: ignore[call-arg]


@pytest.mark.parametrize("bad_hash", ["", "   ", "0" * 64, "short"])
def test_approve_with_bad_hash_is_refused(db, admin_user, pending_request, booked_appointment, bad_hash):
    with pytest.raises(approval_service.ParamsHashMismatch):
        approve_and_execute(
            db, pending_request, admin=admin_user, expected_params_hash=bad_hash
        )

    db.expire_all()
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.PENDING
    db.refresh(booked_appointment)
    assert booked_appointment.status is AppointmentStatus.BOOKED


@pytest.mark.parametrize("bad_hash", ["", "0" * 64])
def test_reject_with_bad_hash_is_refused(db, admin_user, pending_request, bad_hash):
    with pytest.raises(approval_service.ParamsHashMismatch):
        reject(db, pending_request, admin=admin_user, expected_params_hash=bad_hash)

    db.expire_all()
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.PENDING


def test_reject_endpoint_with_stale_hash_returns_409(client, db, admin_user, pending_request):
    resp = client.post(
        f"/api/admin/approvals/{pending_request.id}/reject",
        json={"params_hash": "f" * 64}, headers=auth(admin_user),
    )
    assert resp.status_code == 409
    db.expire_all()
    assert db.get(ActionRequest, pending_request.id).status is ActionRequestStatus.PENDING


def test_hash_of_another_request_does_not_authorise_this_one(db, agent, admin_user, booked_appointment):
    """A valid hash is not a master key -- it must be THIS request's hash."""
    from app.governance.engine import GovernanceEngine

    grant(db, agent, Permission.CANCEL_APPOINTMENT)
    engine = GovernanceEngine(db, agent_id=agent.id)
    first = db.get(
        ActionRequest,
        engine.execute(
            "cancel_appointment",
            {"appointment_id": booked_appointment.id, "reason": "one"},
        ).action_request_id,
    )
    second = db.get(
        ActionRequest,
        engine.execute(
            "cancel_appointment",
            {"appointment_id": booked_appointment.id, "reason": "two"},
        ).action_request_id,
    )
    assert first.params_hash != second.params_hash

    with pytest.raises(approval_service.ParamsHashMismatch):
        approve_and_execute(
            db, second, admin=admin_user, expected_params_hash=first.params_hash
        )
