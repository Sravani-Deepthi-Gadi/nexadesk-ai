"""Test fixtures.

The suite runs against an in-memory SQLite database and a scripted fake LLM.
No API key, no network, no cost, and the same result every run.
"""
import os

# Must be set before app.config caches its Settings instance.
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-outside-tests-0123456789")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("ADMIN_EMAIL", "")
os.environ.setdefault("ADMIN_PASSWORD", "")

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.llm.base import LLMResponse
from app.config import get_settings
from app.db.seed import seed
from app.models import (
    ActionRequest, AdminUser, Agent, AgentPermission, Appointment, Base,
    Customer, Service,
)
from app.models.enums import AdminRole, AppointmentStatus, Permission
from app.security.password import hash_password
from app.security.tokens import create_access_token

get_settings.cache_clear()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def agent(db) -> Agent:
    """The seeded concierge: may read and book, may NOT cancel."""
    return seed(db)


@pytest.fixture
def booked_appointment(db, agent) -> Appointment:
    customer = Customer(name="Asha Rao", email="asha@example.com")
    db.add(customer)
    db.flush()
    service = db.query(Service).first()
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    appt = Appointment(
        customer_id=customer.id,
        service_id=service.id,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=service.duration_minutes),
        status=AppointmentStatus.BOOKED,
        created_by_agent_id=agent.id,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


def grant(db, agent: Agent, permission: Permission) -> None:
    db.add(AgentPermission(agent_id=agent.id, permission=permission, granted=True))
    db.commit()


class FakeLLM:
    """Replays a scripted list of LLMResponse objects, in order.

    Lets the suite assert on the orchestrator's behaviour -- including what
    it does when a tool call comes back blocked -- without the
    nondeterminism of a real model.
    """

    def __init__(self, script: list[LLMResponse]):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def create(self, *, system, messages, tools, max_tokens) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if not self.script:
            return LLMResponse(
                stop_reason="end_turn",
                content=[{"type": "text", "text": "(no more scripted responses)"}],
            )
        return self.script.pop(0)


def tool_use_response(tool_use_id: str, name: str, payload: dict) -> LLMResponse:
    return LLMResponse(
        stop_reason="tool_use",
        content=[{"type": "tool_use", "id": tool_use_id, "name": name, "input": payload}],
    )


def text_response(text: str) -> LLMResponse:
    return LLMResponse(stop_reason="end_turn", content=[{"type": "text", "text": text}])


# --------------------------------------------------------------------------
# Milestone 2 fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def admin_user(db) -> AdminUser:
    user = AdminUser(
        email="admin@nexacare.co",
        password_hash=hash_password("correct-horse-battery"),
        role=AdminRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def viewer_user(db) -> AdminUser:
    user = AdminUser(
        email="viewer@nexacare.co",
        password_hash=hash_password("read-only-please"),
        role=AdminRole.VIEWER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def token_for(user: AdminUser, *, expires_minutes: int = 60) -> str:
    settings = get_settings()
    return create_access_token(
        subject_id=user.id, email=user.email, role=user.role.value,
        secret=settings.jwt_secret, expires_minutes=expires_minutes,
    )


def auth(user: AdminUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user)}"}


@pytest.fixture
def pending_request(db, agent, booked_appointment) -> ActionRequest:
    """A real withheld cancel_appointment request.

    Permission is granted first, so the action is withheld because it is
    HIGH risk -- not because the agent lacked the permission.
    """
    from app.governance.engine import GovernanceEngine

    grant(db, agent, Permission.CANCEL_APPOINTMENT)
    engine = GovernanceEngine(db, agent_id=agent.id)
    result = engine.execute(
        "cancel_appointment",
        {"appointment_id": booked_appointment.id, "reason": "schedule clash"},
        tool_use_id="tu_cancel_1",
    )
    assert result.action_request_id is not None
    return db.get(ActionRequest, result.action_request_id)
