"""Admin document endpoints and the customer conversation-status endpoint."""
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm
from app.db.session import get_db
from app.main import app
from app.models import Conversation, Document
from tests.conftest import (
    FakeLLM, MALICIOUS_TEXT, POLICY_TEXT, auth, make_pdf,
)


@pytest.fixture
def client(db, rag):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_llm] = lambda: FakeLLM([])
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload(client, headers, data: bytes, name: str, ctype: str = "text/plain",
            title: str = ""):
    return client.post(
        "/api/admin/documents",
        files={"file": (name, data, ctype)},
        data={"title": title},
        headers=headers,
    )


# ==========================================================================
# Upload and authorisation
# ==========================================================================
def test_upload_requires_authentication(client):
    resp = _upload(client, {}, POLICY_TEXT.encode(), "policies.txt")
    assert resp.status_code == 401


def test_viewer_cannot_upload_but_can_list(client, viewer_user):
    assert _upload(
        client, auth(viewer_user), POLICY_TEXT.encode(), "p.txt"
    ).status_code == 403
    assert client.get(
        "/api/admin/documents", headers=auth(viewer_user)
    ).status_code == 200


def test_admin_upload_indexes_the_document(client, admin_user, db):
    resp = _upload(
        client, auth(admin_user), POLICY_TEXT.encode(), "policies.txt",
        title="Company Policies",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "indexed"
    assert body["chunk_count"] > 0
    assert body["title"] == "Company Policies"
    assert body["uploaded_by_admin_id"] == admin_user.id
    assert db.query(Document).count() == 1


def test_pdf_upload_works(client, admin_user):
    pdf = make_pdf(["Refunds are issued within 14 working days."])
    resp = _upload(client, auth(admin_user), pdf, "refunds.pdf", "application/pdf")
    assert resp.status_code == 201
    assert resp.json()["status"] == "indexed"


def test_duplicate_upload_returns_409(client, admin_user):
    _upload(client, auth(admin_user), POLICY_TEXT.encode(), "a.txt")
    dup = _upload(client, auth(admin_user), POLICY_TEXT.encode(), "b.txt")
    assert dup.status_code == 409


def test_unsupported_type_returns_415(client, admin_user):
    resp = _upload(
        client, auth(admin_user), b"\x89PNG\r\n", "logo.png", "image/png"
    )
    assert resp.status_code == 415


def test_scanned_pdf_returns_422_with_an_explanation(client, admin_user):
    resp = _upload(
        client, auth(admin_user), make_pdf([]), "scan.pdf", "application/pdf"
    )
    assert resp.status_code == 422
    assert "OCR" in resp.json()["detail"] or "No text" in resp.json()["detail"]


# ==========================================================================
# Inspection, reindex, delete
# ==========================================================================
def test_admin_can_inspect_flagged_chunks(client, admin_user):
    doc = _upload(
        client, auth(admin_user), MALICIOUS_TEXT.encode(), "terms.txt"
    ).json()
    assert doc["suspicious_chunk_count"] > 0

    flagged = client.get(
        f"/api/admin/documents/{doc['id']}/chunks?suspicious_only=true",
        headers=auth(admin_user),
    ).json()
    assert flagged
    assert all(c["is_suspicious"] for c in flagged)
    # The admin sees the original text, not a sanitised version.
    assert any("IGNORE ALL PREVIOUS" in c["text"] for c in flagged)


def test_reindex_rebuilds_the_vector_store(client, admin_user, rag):
    doc = _upload(client, auth(admin_user), POLICY_TEXT.encode(), "p.txt").json()
    rag.store._vectors.clear()
    rag.store._meta.clear()

    resp = client.post(
        f"/api/admin/documents/{doc['id']}/reindex", headers=auth(admin_user)
    )
    assert resp.status_code == 200
    assert rag.store.count() == doc["chunk_count"]


def test_delete_removes_document_and_vectors(client, admin_user, db, rag):
    doc = _upload(client, auth(admin_user), POLICY_TEXT.encode(), "p.txt").json()

    assert client.delete(
        f"/api/admin/documents/{doc['id']}", headers=auth(admin_user)
    ).status_code == 204
    assert db.query(Document).count() == 0
    assert rag.store.count() == 0


def test_viewer_cannot_delete(client, viewer_user, admin_user, db):
    doc = _upload(client, auth(admin_user), POLICY_TEXT.encode(), "p.txt").json()
    assert client.delete(
        f"/api/admin/documents/{doc['id']}", headers=auth(viewer_user)
    ).status_code == 403
    assert db.query(Document).count() == 1


# ==========================================================================
# Customer conversation status
# ==========================================================================
def test_status_requires_a_known_session(client):
    assert client.get(
        "/api/chat/status", params={"session_token": "n" * 40}
    ).status_code == 404


def test_status_reports_pending_then_resolved(client, db, agent, admin_user,
                                              pending_request, booked_appointment):
    convo = Conversation(session_token="status-session-" + "y" * 20)
    db.add(convo)
    db.commit()
    pending_request.conversation_id = convo.id
    db.commit()

    first = client.get(
        "/api/chat/status", params={"session_token": convo.session_token}
    ).json()
    assert len(first["pending_actions"]) == 1
    assert first["pending_actions"][0]["status"] == "pending"
    assert "staff" in first["pending_actions"][0]["message"].lower()

    from app.governance.approvals import approve_and_execute

    approve_and_execute(
        db, pending_request, admin=admin_user,
        expected_params_hash=pending_request.params_hash,
    )

    second = client.get(
        "/api/chat/status", params={"session_token": convo.session_token}
    ).json()
    assert second["pending_actions"] == []
    assert second["resolved_actions"][0]["status"] == "executed"
    assert "Done" in second["resolved_actions"][0]["message"]


def test_status_is_isolated_between_sessions(client, db, agent, pending_request):
    """One customer must not see another's approvals."""
    mine = Conversation(session_token="mine-session-" + "a" * 22)
    theirs = Conversation(session_token="their-session-" + "b" * 22)
    db.add_all([mine, theirs])
    db.commit()
    pending_request.conversation_id = mine.id
    db.commit()

    theirs_view = client.get(
        "/api/chat/status", params={"session_token": theirs.session_token}
    ).json()
    assert theirs_view["pending_actions"] == []
    assert theirs_view["resolved_actions"] == []


def test_status_never_leaks_the_admin_decision_note(client, db, admin_user,
                                                    pending_request):
    from app.governance.approvals import reject

    convo = Conversation(session_token="note-session-" + "c" * 22)
    db.add(convo)
    db.commit()
    pending_request.conversation_id = convo.id
    db.commit()

    reject(db, pending_request, admin=admin_user,
           expected_params_hash=pending_request.params_hash,
           note="INTERNAL: customer is disputing a charge, do not refund")

    body = client.get(
        "/api/chat/status", params={"session_token": convo.session_token}
    ).json()
    assert "INTERNAL" not in str(body)
    assert body["resolved_actions"][0]["status"] == "rejected"
