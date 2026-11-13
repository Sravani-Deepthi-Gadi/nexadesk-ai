"""Test fixtures.

The suite runs against an in-memory SQLite database and a scripted fake LLM.
No API key, no network, no cost, and the same result every run.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.llm.base import LLMResponse
from app.db.seed import seed
from app.models import Agent, AgentPermission, Appointment, Base, Customer, Service
from app.models.enums import AppointmentStatus, Permission


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
