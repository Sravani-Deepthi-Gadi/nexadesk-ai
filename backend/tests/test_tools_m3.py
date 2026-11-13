"""The four new tools: availability, booking, customer details, escalation."""
from datetime import datetime, timedelta, timezone

import pytest

from app.governance.engine import GovernanceEngine
from app.models import Appointment, Conversation, Customer, Escalation
from app.models.enums import (
    AppointmentStatus, ConversationState, Outcome, Permission, RiskLevel,
)
from app.models import Service
from tests.conftest import grant


def _next_weekday(days_ahead: int = 1) -> datetime:
    d = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    while d.weekday() > 4:          # seeded hours are Mon-Fri
        d += timedelta(days=1)
    return d


@pytest.fixture
def convo(db) -> Conversation:
    c = Conversation(session_token="sess-tools-" + "x" * 20)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def engine_for(db, agent, convo=None) -> GovernanceEngine:
    return GovernanceEngine(
        db, agent_id=agent.id,
        conversation_id=convo.id if convo else None,
    )


# ==========================================================================
# check_availability
# ==========================================================================
def test_check_availability_returns_slots_on_a_working_day(db, agent):
    service = db.query(Service).first()
    day = _next_weekday().date().isoformat()

    result = engine_for(db, agent).execute(
        "check_availability", {"service_id": service.id, "date": day}
    )

    assert result.outcome is Outcome.EXECUTED
    assert result.data["count"] > 0
    assert all(s.endswith("+00:00") for s in result.data["slots"])


def test_check_availability_reports_closed_days(db, agent):
    service = db.query(Service).first()
    d = datetime.now(timezone.utc) + timedelta(days=1)
    while d.weekday() != 6:         # Sunday
        d += timedelta(days=1)

    result = engine_for(db, agent).execute(
        "check_availability", {"service_id": service.id, "date": d.date().isoformat()}
    )
    assert result.data["slots"] == []
    assert "closed" in result.data["note"].lower()


def test_check_availability_rejects_past_dates(db, agent):
    service = db.query(Service).first()
    past = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()

    result = engine_for(db, agent).execute(
        "check_availability", {"service_id": service.id, "date": past}
    )
    assert result.outcome is Outcome.ERROR
    assert "past" in result.message.lower()


def test_check_availability_is_low_risk_and_needs_its_permission(db, agent):
    from app.models import AgentPermission

    perm = db.query(AgentPermission).filter(
        AgentPermission.agent_id == agent.id,
        AgentPermission.permission == Permission.CHECK_AVAILABILITY,
    ).one()
    perm.granted = False
    db.commit()

    service = db.query(Service).first()
    result = engine_for(db, agent).execute(
        "check_availability",
        {"service_id": service.id, "date": _next_weekday().date().isoformat()},
    )
    assert result.outcome is Outcome.BLOCKED


# ==========================================================================
# book_appointment
# ==========================================================================
def test_booking_creates_appointment_and_links_the_customer(db, agent, convo):
    service = db.query(Service).first()
    engine = engine_for(db, agent, convo)
    slot = engine.execute(
        "check_availability",
        {"service_id": service.id, "date": _next_weekday().date().isoformat()},
    ).data["slots"][0]

    result = engine.execute("book_appointment", {
        "service_id": service.id, "starts_at": slot,
        "customer_name": "Asha Rao", "customer_email": "Asha@Example.com",
    })

    assert result.outcome is Outcome.EXECUTED
    assert result.risk_level is RiskLevel.MEDIUM   # MEDIUM: no approval needed
    appt = db.get(Appointment, result.data["appointment_id"])
    assert appt.status is AppointmentStatus.BOOKED

    customer = db.get(Customer, appt.customer_id)
    assert customer.email == "asha@example.com"    # normalised

    db.refresh(convo)
    assert convo.customer_id == customer.id        # bound for isolation


def test_double_booking_the_same_slot_is_refused(db, agent, convo):
    service = db.query(Service).first()
    engine = engine_for(db, agent, convo)
    slot = engine.execute(
        "check_availability",
        {"service_id": service.id, "date": _next_weekday().date().isoformat()},
    ).data["slots"][0]

    base = {"service_id": service.id, "starts_at": slot,
            "customer_name": "A", "customer_email": "a@example.com"}
    assert engine.execute("book_appointment", base).outcome is Outcome.EXECUTED

    second = engine.execute("book_appointment", {
        **base, "customer_name": "B", "customer_email": "b@example.com"
    })
    assert second.outcome is Outcome.ERROR
    assert "taken" in second.message.lower()
    assert db.query(Appointment).count() == 1


def test_booking_outside_business_hours_is_refused(db, agent, convo):
    service = db.query(Service).first()
    midnight = _next_weekday().replace(
        hour=3, minute=0, second=0, microsecond=0
    ).isoformat()

    result = engine_for(db, agent, convo).execute("book_appointment", {
        "service_id": service.id, "starts_at": midnight,
        "customer_name": "A", "customer_email": "a@example.com",
    })
    assert result.outcome is Outcome.ERROR
    assert "business hours" in result.message.lower()


def test_booking_in_the_past_is_refused(db, agent, convo):
    service = db.query(Service).first()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    result = engine_for(db, agent, convo).execute("book_appointment", {
        "service_id": service.id, "starts_at": past,
        "customer_name": "A", "customer_email": "a@example.com",
    })
    assert result.outcome is Outcome.ERROR


def test_booking_requires_create_appointment_permission(db, agent, convo):
    from app.models import AgentPermission

    perm = db.query(AgentPermission).filter(
        AgentPermission.agent_id == agent.id,
        AgentPermission.permission == Permission.CREATE_APPOINTMENT,
    ).one()
    perm.granted = False
    db.commit()

    service = db.query(Service).first()
    result = engine_for(db, agent, convo).execute("book_appointment", {
        "service_id": service.id,
        "starts_at": _next_weekday().replace(hour=10, minute=0, second=0,
                                             microsecond=0).isoformat(),
        "customer_name": "A", "customer_email": "a@example.com",
    })
    assert result.outcome is Outcome.BLOCKED
    assert db.query(Appointment).count() == 0


# ==========================================================================
# get_customer_details -- isolation
# ==========================================================================
def test_customer_details_returns_nothing_before_identification(db, agent, convo):
    result = engine_for(db, agent, convo).execute("get_customer_details", {})
    assert result.outcome is Outcome.EXECUTED
    assert result.data["identified"] is False


def test_customer_details_returns_only_this_conversations_customer(db, agent, convo):
    """The isolation test.

    Two customers exist. The conversation is bound to one. The tool takes
    no parameters, so there is no way to ask for the other -- extra keys
    are rejected before execution.
    """
    mine = Customer(name="Asha Rao", email="asha@example.com")
    theirs = Customer(name="Other Person", email="other@example.com")
    db.add_all([mine, theirs])
    db.flush()
    convo.customer_id = mine.id
    db.commit()

    engine = engine_for(db, agent, convo)
    result = engine.execute("get_customer_details", {})

    assert result.data["identified"] is True
    assert result.data["name"] == "Asha Rao"
    assert "Other Person" not in str(result.data)

    # Attempting to name the other customer does not work.
    attack = engine.execute("get_customer_details", {"customer_id": theirs.id})
    assert attack.data.get("name") != "Other Person"


def test_customer_details_lists_only_that_customers_appointments(db, agent, convo):
    service = db.query(Service).first()
    mine = Customer(name="Mine", email="mine@example.com")
    theirs = Customer(name="Theirs", email="theirs@example.com")
    db.add_all([mine, theirs])
    db.flush()
    start = _next_weekday().replace(hour=10, minute=0, second=0, microsecond=0)
    db.add_all([
        Appointment(customer_id=mine.id, service_id=service.id, starts_at=start,
                    ends_at=start + timedelta(minutes=30),
                    status=AppointmentStatus.BOOKED),
        Appointment(customer_id=theirs.id, service_id=service.id,
                    starts_at=start + timedelta(hours=2),
                    ends_at=start + timedelta(hours=2, minutes=30),
                    status=AppointmentStatus.BOOKED),
    ])
    convo.customer_id = mine.id
    db.commit()

    result = engine_for(db, agent, convo).execute("get_customer_details", {})
    assert result.data["appointment_count"] == 1


def test_customer_details_requires_read_customer_data(db, agent, convo):
    from app.models import AgentPermission

    perm = db.query(AgentPermission).filter(
        AgentPermission.agent_id == agent.id,
        AgentPermission.permission == Permission.READ_CUSTOMER_DATA,
    ).one()
    perm.granted = False
    db.commit()

    result = engine_for(db, agent, convo).execute("get_customer_details", {})
    assert result.outcome is Outcome.BLOCKED


# ==========================================================================
# escalate_to_human
# ==========================================================================
def test_escalation_creates_a_ticket_and_marks_the_conversation(db, agent, convo):
    result = engine_for(db, agent, convo).execute("escalate_to_human", {
        "reason": "billing dispute", "summary": "Customer disputes a charge.",
    })

    assert result.outcome is Outcome.EXECUTED
    row = db.get(Escalation, result.data["escalation_id"])
    assert row.reason == "billing dispute"
    assert row.conversation_id == convo.id

    db.refresh(convo)
    assert convo.state is ConversationState.ESCALATED


def test_escalation_requires_its_own_permission(db, agent, convo):
    from app.models import AgentPermission

    perm = db.query(AgentPermission).filter(
        AgentPermission.agent_id == agent.id,
        AgentPermission.permission == Permission.ESCALATE_TO_HUMAN,
    ).one()
    perm.granted = False
    db.commit()

    result = engine_for(db, agent, convo).execute(
        "escalate_to_human", {"reason": "anything"}
    )
    assert result.outcome is Outcome.BLOCKED
    assert db.query(Escalation).count() == 0


def test_every_tool_has_a_permission_and_a_risk_level():
    """No tool may ship ungoverned."""
    from app.schemas.tool_catalog import TOOL_CATALOG

    assert len(TOOL_CATALOG) == 7
    for name, defn in TOOL_CATALOG.items():
        assert defn.required_permission is not None, name
        assert defn.risk_level is not None, name
