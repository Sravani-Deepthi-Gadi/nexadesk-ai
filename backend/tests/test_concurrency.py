"""Real concurrency tests against a file-backed SQLite database.

The other tests exercise the conflict path sequentially, which proves the
state machine rejects a second decision. These tests prove the stronger
claim: when N threads race on the SAME request at the SAME time, exactly
one wins. That is a property of the atomic conditional UPDATE, and it is
the part a read-then-write implementation would get wrong while still
passing every sequential test.
"""
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.seed import seed
from app.governance.action_requests import (
    ActionRequestConflict, create_action_request, mark_approved, mark_rejected,
)
from app.governance.approvals import execute_approved
from app.models import (
    ActionRequest, AdminUser, AgentPermission, Appointment, Base, Customer,
    Service,
)
from app.models.enums import (
    ActionRequestStatus, AdminRole, AppointmentStatus, Permission, RiskLevel,
)
from app.security.password import hash_password

THREADS = 8


@pytest.fixture
def file_db():
    """A file-backed database so separate threads see the same data."""
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp) / 'concurrency.db'}"
        engine = create_engine(
            url, connect_args={"check_same_thread": False}, future=True
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        setup = Session()
        agent = seed(setup)
        setup.add(
            AgentPermission(
                agent_id=agent.id,
                permission=Permission.CANCEL_APPOINTMENT,
                granted=True,
            )
        )
        admin = AdminUser(
            email="race@nexacare.co",
            password_hash=hash_password("racing-is-fine"),
            role=AdminRole.ADMIN, is_active=True,
        )
        customer = Customer(name="Race Tester", email="race-c@nexacare.co")
        setup.add_all([admin, customer])
        setup.flush()

        service = setup.query(Service).first()
        starts = datetime.now(timezone.utc) + timedelta(days=1)
        appt = Appointment(
            customer_id=customer.id, service_id=service.id,
            starts_at=starts,
            ends_at=starts + timedelta(minutes=service.duration_minutes),
            status=AppointmentStatus.BOOKED, created_by_agent_id=agent.id,
        )
        setup.add(appt)
        setup.commit()

        request = create_action_request(
            setup,
            agent_id=agent.id, conversation_id=None,
            tool_name="cancel_appointment",
            params={"appointment_id": appt.id, "reason": "race"},
            risk_level=RiskLevel.HIGH,
        )
        ids = {
            "request_id": request.id,
            "admin_id": admin.id,
            "appointment_id": appt.id,
        }
        setup.close()

        yield Session, ids
        engine.dispose()


def _run_in_threads(fn, count: int) -> tuple[int, int]:
    """Returns (successes, conflicts)."""
    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(lambda i: fn(), range(count)))
    return results.count("ok"), results.count("conflict")


def test_concurrent_approvals_only_one_wins(file_db):
    Session, ids = file_db

    def attempt() -> str:
        db = Session()
        try:
            mark_approved(db, ids["request_id"], admin_user_id=ids["admin_id"])
            return "ok"
        except ActionRequestConflict:
            return "conflict"
        finally:
            db.close()

    ok, conflicts = _run_in_threads(attempt, THREADS)
    assert ok == 1, f"expected exactly one approval to win, got {ok}"
    assert conflicts == THREADS - 1

    check = Session()
    assert check.get(ActionRequest, ids["request_id"]).status is ActionRequestStatus.APPROVED
    check.close()


def test_concurrent_approve_and_reject_only_one_decision_sticks(file_db):
    Session, ids = file_db

    def attempt(i: int) -> str:
        db = Session()
        try:
            fn = mark_approved if i % 2 == 0 else mark_rejected
            fn(db, ids["request_id"], admin_user_id=ids["admin_id"])
            return "ok"
        except ActionRequestConflict:
            return "conflict"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        results = list(pool.map(attempt, range(THREADS)))

    assert results.count("ok") == 1

    check = Session()
    status = check.get(ActionRequest, ids["request_id"]).status
    assert status in (ActionRequestStatus.APPROVED, ActionRequestStatus.REJECTED)
    check.close()


def test_concurrent_execution_runs_the_action_exactly_once(file_db):
    Session, ids = file_db

    setup = Session()
    mark_approved(setup, ids["request_id"], admin_user_id=ids["admin_id"])
    setup.close()

    def attempt() -> str:
        db = Session()
        try:
            execute_approved(db, ids["request_id"])
            return "ok"
        except ActionRequestConflict:
            return "conflict"
        finally:
            db.close()

    ok, conflicts = _run_in_threads(attempt, THREADS)
    assert ok == 1, f"expected exactly one execution to win, got {ok}"
    assert conflicts == THREADS - 1

    check = Session()
    appt = check.get(Appointment, ids["appointment_id"])
    assert appt.status is AppointmentStatus.CANCELLED
    assert check.get(ActionRequest, ids["request_id"]).status is ActionRequestStatus.EXECUTED
    check.close()
