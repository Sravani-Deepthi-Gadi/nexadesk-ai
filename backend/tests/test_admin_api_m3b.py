"""Endpoints added for the dashboard: metrics, agent controls, conversations."""
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm
from app.db.session import get_db
from app.main import app
from app.models import Agent, AgentPermission, AuditLog, Conversation
from app.models.enums import AgentStatus, AuditEventType, Permission
from tests.conftest import FakeLLM, auth, text_response, tool_use_response


@pytest.fixture
def client(db, agent, rag):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_llm] = lambda: FakeLLM([])
    yield TestClient(app)
    app.dependency_overrides.clear()


def _with_llm(db, llm):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


# ==========================================================================
# Metrics
# ==========================================================================
def test_overview_requires_authentication(client):
    assert client.get("/api/admin/metrics/overview").status_code == 401


def test_overview_reports_real_counts(db, agent, admin_user, rag):
    llm = FakeLLM([
        tool_use_response("tu_1", "search_services", {}),
        text_response("Here are our services."),
    ])
    client = _with_llm(db, llm)
    client.post("/api/chat", json={"message": "what do you offer?"})

    body = client.get("/api/admin/metrics/overview", headers=auth(admin_user)).json()

    assert body["total_conversations"] == 1
    assert body["total_tool_calls"] == 1
    assert body["successful_actions"] >= 1
    assert body["agent_status"] == "active"
    assert body["agent_name"] == agent.name
    assert {s["risk_level"] for s in body["risk_distribution"]} == {"LOW", "MEDIUM", "HIGH"}
    assert len(body["tool_calls_last_7_days"]) == 7
    assert body["recent_activity"]
    app.dependency_overrides.clear()


def test_overview_counts_pending_approvals(client, admin_user, pending_request):
    body = client.get("/api/admin/metrics/overview", headers=auth(admin_user)).json()
    assert body["pending_approvals"] == 1


def test_overview_works_on_an_empty_system(client, admin_user):
    body = client.get("/api/admin/metrics/overview", headers=auth(admin_user)).json()
    assert body["total_conversations"] == 0
    assert body["total_tool_calls"] == 0
    assert len(body["tool_calls_last_7_days"]) == 7


# ==========================================================================
# Agent controls
# ==========================================================================
def test_get_agent_lists_every_permission(client, admin_user, agent):
    body = client.get("/api/admin/agent", headers=auth(admin_user)).json()
    assert body["status"] == "active"
    assert len(body["permissions"]) == len(Permission)

    granted = {p["permission"] for p in body["permissions"] if p["granted"]}
    assert "CREATE_APPOINTMENT" in granted
    assert "CANCEL_APPOINTMENT" not in granted
    assert all(p["description"] for p in body["permissions"])


def test_viewer_cannot_use_the_emergency_stop(client, viewer_user, db, agent):
    resp = client.post(
        "/api/admin/agent/status", json={"status": "disabled"},
        headers=auth(viewer_user),
    )
    assert resp.status_code == 403
    db.refresh(agent)
    assert agent.status is AgentStatus.ACTIVE


def test_emergency_stop_disables_the_agent_and_is_audited(client, admin_user, db, agent):
    resp = client.post(
        "/api/admin/agent/status",
        json={"status": "disabled", "reason": "suspicious activity"},
        headers=auth(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"

    db.refresh(agent)
    assert agent.status is AgentStatus.DISABLED

    row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row.tool_name == "agent_status_change"
    assert row.admin_user_id == admin_user.id
    assert "suspicious activity" in row.error_message


def test_disabled_agent_actually_blocks_tool_calls(db, agent, admin_user, rag):
    """The control has to do something, not just flip a flag."""
    client = _with_llm(db, FakeLLM([]))
    client.post(
        "/api/admin/agent/status", json={"status": "disabled"},
        headers=auth(admin_user),
    )
    app.dependency_overrides.clear()

    llm = FakeLLM([
        tool_use_response("tu_1", "search_services", {}),
        text_response("I'm currently disabled."),
    ])
    client = _with_llm(db, llm)
    body = client.post("/api/chat", json={"message": "services?"}).json()
    assert body["tool_calls"][0]["outcome"] == "blocked"
    app.dependency_overrides.clear()


def test_agent_can_be_re_enabled(client, admin_user, db, agent):
    client.post("/api/admin/agent/status", json={"status": "disabled"},
                headers=auth(admin_user))
    resp = client.post("/api/admin/agent/status", json={"status": "active"},
                       headers=auth(admin_user))
    assert resp.json()["status"] == "active"
    db.refresh(agent)
    assert agent.status is AgentStatus.ACTIVE


def test_viewer_cannot_change_permissions(client, viewer_user, db, agent):
    resp = client.put(
        "/api/admin/agent/permissions",
        json={"permission": "CANCEL_APPOINTMENT", "granted": True},
        headers=auth(viewer_user),
    )
    assert resp.status_code == 403
    assert db.query(AgentPermission).filter(
        AgentPermission.agent_id == agent.id,
        AgentPermission.permission == Permission.CANCEL_APPOINTMENT,
    ).one_or_none() is None


def test_granting_a_permission_takes_effect_and_is_audited(client, admin_user, db, agent):
    resp = client.put(
        "/api/admin/agent/permissions",
        json={"permission": "CANCEL_APPOINTMENT", "granted": True},
        headers=auth(admin_user),
    )
    assert resp.status_code == 200
    granted = {p["permission"] for p in resp.json()["permissions"] if p["granted"]}
    assert "CANCEL_APPOINTMENT" in granted

    from app.governance.permissions import agent_has_permission
    assert agent_has_permission(db, agent.id, Permission.CANCEL_APPOINTMENT)

    row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row.tool_name == "agent_permission_change"
    assert row.admin_user_id == admin_user.id
    assert "Granted CANCEL_APPOINTMENT" in row.error_message


def test_revoking_a_permission_takes_effect(client, admin_user, db, agent):
    client.put("/api/admin/agent/permissions",
               json={"permission": "CREATE_APPOINTMENT", "granted": False},
               headers=auth(admin_user))

    from app.governance.permissions import agent_has_permission
    assert not agent_has_permission(db, agent.id, Permission.CREATE_APPOINTMENT)


def test_unknown_permission_is_rejected(client, admin_user):
    resp = client.put(
        "/api/admin/agent/permissions",
        json={"permission": "BECOME_ROOT", "granted": True},
        headers=auth(admin_user),
    )
    assert resp.status_code == 422


# ==========================================================================
# Conversations
# ==========================================================================
def test_conversation_list_and_transcript(db, agent, admin_user, rag):
    llm = FakeLLM([
        tool_use_response("tu_1", "search_services", {}),
        text_response("We offer consultations."),
    ])
    client = _with_llm(db, llm)
    chat = client.post("/api/chat", json={"message": "what do you offer?"}).json()

    rows = client.get("/api/admin/conversations", headers=auth(admin_user)).json()
    assert len(rows) == 1
    assert rows[0]["message_count"] >= 3

    detail = client.get(
        f"/api/admin/conversations/{chat['conversation_id']}",
        headers=auth(admin_user),
    ).json()
    assert [m["role"] for m in detail["messages"]][0] == "user"
    assert any("search_services" in m["tool_calls"] for m in detail["messages"])
    app.dependency_overrides.clear()


def test_transcript_never_exposes_the_session_token(db, agent, admin_user, rag):
    """An admin reading a transcript must not be handed a credential that
    lets them act as that customer."""
    llm = FakeLLM([text_response("Hello.")])
    client = _with_llm(db, llm)
    chat = client.post("/api/chat", json={"message": "hi"}).json()

    detail = client.get(
        f"/api/admin/conversations/{chat['conversation_id']}",
        headers=auth(admin_user),
    )
    assert chat["session_token"] not in detail.text
    assert "session_token" not in detail.json()
    app.dependency_overrides.clear()


def test_missing_conversation_returns_404(client, admin_user):
    assert client.get(
        "/api/admin/conversations/9999", headers=auth(admin_user)
    ).status_code == 404


def test_escalations_are_listed(client, admin_user, db, agent):
    from app.governance.engine import GovernanceEngine

    convo = Conversation(session_token="esc-sess-" + "k" * 22)
    db.add(convo)
    db.commit()
    GovernanceEngine(db, agent_id=agent.id, conversation_id=convo.id).execute(
        "escalate_to_human", {"reason": "billing dispute", "summary": "needs a person"}
    )

    rows = client.get("/api/admin/escalations", headers=auth(admin_user)).json()
    assert len(rows) == 1
    assert rows[0]["reason"] == "billing dispute"
    assert rows[0]["status"] == "open"


# ==========================================================================
# Timestamp serialisation
# ==========================================================================
def test_timestamps_carry_an_explicit_utc_offset(client, admin_user, db, agent, pending_request):
    """SQLite stores naive datetimes. Emitting them without an offset makes
    browsers read them as local time, shifting every "x ago" in the UI by
    the viewer's timezone."""
    import re

    paths = [
        "/api/admin/approvals?status=pending",
        "/api/admin/audit",
        "/api/admin/agent",
        "/api/admin/metrics/overview",
    ]
    stamp = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
    naked = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\"")

    seen = 0
    for path in paths:
        text = client.get(path, headers=auth(admin_user)).text
        for _ in stamp.finditer(text):
            seen += 1
        assert not naked.search(text), f"{path} emitted a timestamp with no offset"
    assert seen > 0, "no timestamps were checked"


def test_iso_utc_assumes_naive_values_are_utc():
    from datetime import datetime, timezone

    from app.api.serialization import iso_utc

    naive = datetime(2026, 11, 12, 8, 30, 0)
    assert iso_utc(naive) == "2026-11-12T08:30:00+00:00"
    aware = datetime(2026, 11, 12, 8, 30, 0, tzinfo=timezone.utc)
    assert iso_utc(aware) == iso_utc(naive)
    assert iso_utc(None) is None


def test_missing_api_key_is_a_503_not_a_500(db, agent, rag, monkeypatch):
    """An unconfigured key is an operator problem, not a server fault."""
    from app.api import deps
    from app.config import get_settings

    deps._build_llm.cache_clear()
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "", raising=False)

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 503
        assert "ANTHROPIC_API_KEY" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        deps._build_llm.cache_clear()
