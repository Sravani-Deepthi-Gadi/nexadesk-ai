"""End-to-end tests for POST /api/chat, using the fake LLM."""
import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, Conversation, Message
from app.models.enums import Outcome
from tests.conftest import FakeLLM, text_response, tool_use_response


def make_client(db, llm):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


def test_tool_backed_answer_round_trip(db, agent):
    """Model asks for search_services, governance allows it, model replies."""
    llm = FakeLLM([
        tool_use_response("tu_1", "search_services", {}),
        text_response("We offer consultations, advisory sessions and reviews."),
    ])
    client = make_client(db, llm)

    resp = client.post("/api/chat", json={"message": "what do you offer?"})
    assert resp.status_code == 200
    body = resp.json()

    assert "consultations" in body["reply"]
    assert len(body["tool_calls"]) == 1
    call = body["tool_calls"][0]
    assert call["tool"] == "search_services"
    assert call["outcome"] == "executed"
    assert call["risk_level"] == "LOW"
    assert call["audit_log_id"] is not None
    # A LOW-risk call needs no approval, so it has no action request.
    assert call["action_request_id"] is None

    # The second call to the model must have carried the tool result back.
    second_call_messages = llm.calls[1]["messages"]
    blocks = second_call_messages[-1]["content"]
    assert blocks[0]["type"] == "tool_result"
    assert json.loads(blocks[0]["content"])["count"] == 4

    app.dependency_overrides.clear()


def test_blocked_tool_is_reported_to_the_model_not_executed(db, agent, booked_appointment):
    llm = FakeLLM([
        tool_use_response("tu_1", "cancel_appointment",
                          {"appointment_id": booked_appointment.id}),
        text_response("I can't cancel that myself -- I'll pass it to staff."),
    ])
    client = make_client(db, llm)

    resp = client.post("/api/chat", json={"message": "cancel my booking"})
    body = resp.json()

    assert body["tool_calls"][0]["outcome"] == "blocked"
    db.refresh(booked_appointment)
    assert booked_appointment.status.value == "booked"

    # The model was told it was blocked.
    returned = json.loads(llm.calls[1]["messages"][-1]["content"][0]["content"])
    assert returned["status"] == "blocked"

    app.dependency_overrides.clear()


def test_sessions_are_isolated(db, agent):
    llm = FakeLLM([
        text_response("Noted, Asha."),
        text_response("I don't have a name for you yet."),
    ])
    client = make_client(db, llm)

    first = client.post("/api/chat", json={"message": "My name is Asha."}).json()
    token_a = first["session_token"]

    second = client.post("/api/chat", json={"message": "What is my name?"}).json()
    token_b = second["session_token"]

    assert token_a != token_b
    assert first["conversation_id"] != second["conversation_id"]

    # The second conversation's history must contain only its own messages.
    msgs_b = (
        db.query(Message)
        .filter(Message.conversation_id == second["conversation_id"])
        .all()
    )
    assert all("Asha" not in m.content for m in msgs_b)
    assert db.query(Conversation).count() == 2

    app.dependency_overrides.clear()


def test_continuing_a_session_preserves_history(db, agent):
    llm = FakeLLM([text_response("Hello."), text_response("You said hi.")])
    client = make_client(db, llm)

    first = client.post("/api/chat", json={"message": "hi"}).json()
    token = first["session_token"]
    client.post("/api/chat", json={"message": "what did I say?", "session_token": token})

    # Second model call should have seen the earlier turns.
    assert len(llm.calls[1]["messages"]) >= 3
    assert db.query(Conversation).count() == 1

    app.dependency_overrides.clear()


def test_every_tool_call_leaves_an_audit_row(db, agent):
    llm = FakeLLM([
        tool_use_response("tu_1", "search_services", {"query": "review"}),
        text_response("Here are the reviews we offer."),
    ])
    client = make_client(db, llm)
    before = db.query(AuditLog).count()

    body = client.post("/api/chat", json={"message": "reviews?"}).json()

    assert db.query(AuditLog).count() == before + 1
    entry = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert entry.conversation_id == body["conversation_id"]
    assert entry.outcome is Outcome.EXECUTED
    assert json.loads(entry.params_json) == {"query": "review"}

    app.dependency_overrides.clear()
