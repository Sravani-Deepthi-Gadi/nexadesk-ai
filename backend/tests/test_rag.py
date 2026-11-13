"""Ingestion, chunking, retrieval and citation.

All of these use the offline HashingEmbeddings provider, which matches on
LEXICAL overlap. That is enough to prove the pipeline, the ranking order,
the citation metadata and the SQLite-is-source-of-truth property. It is NOT
evidence about how well all-MiniLM-L6-v2 handles paraphrase.
"""
import pytest

from app.models import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.rag.ingest import (
    DuplicateDocument, delete_document, ingest_document, reindex_document,
)
from app.rag.loader import ExtractionError, UnsupportedDocument
from app.rag.retriever import retrieve
from tests.conftest import MALICIOUS_TEXT, POLICY_TEXT, make_pdf


# ==========================================================================
# Ingestion
# ==========================================================================
def test_txt_ingestion_creates_indexed_document(db, rag, ingest):
    doc = ingest(POLICY_TEXT.encode(), filename="policies.txt", title="Policies")

    assert doc.status is DocumentStatus.INDEXED
    assert doc.chunk_count > 0
    assert doc.title == "Policies"
    assert db.query(DocumentChunk).filter(
        DocumentChunk.document_id == doc.id
    ).count() == doc.chunk_count
    assert rag.store.count() == doc.chunk_count


def test_pdf_ingestion_records_page_numbers(db, rag, ingest):
    pdf = make_pdf([
        "NexaCare Cancellation Policy",
        "Cancel at least 24 hours before your appointment.",
        "A late cancellation fee of 25 pounds applies.",
    ])
    doc = ingest(pdf, filename="policy.pdf", content_type="application/pdf")

    assert doc.status is DocumentStatus.INDEXED
    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).all()
    assert chunks
    assert all(c.page_number == 1 for c in chunks)
    assert "24 hours" in " ".join(c.text for c in chunks)


def test_long_document_is_split_into_several_chunks(db, rag, ingest):
    body = "\n\n".join(
        f"Section {i}. " + ("NexaCare provides advisory services. " * 15)
        for i in range(6)
    )
    doc = ingest(body.encode(), filename="long.txt")
    assert doc.chunk_count > 1

    indexes = [
        c.chunk_index
        for c in db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index).all()
    ]
    assert indexes == list(range(len(indexes)))   # contiguous, zero-based


def test_duplicate_upload_is_rejected_by_hash(db, rag, ingest):
    ingest(POLICY_TEXT.encode(), filename="policies.txt")
    with pytest.raises(DuplicateDocument):
        ingest(POLICY_TEXT.encode(), filename="renamed-but-identical.txt")
    assert db.query(Document).count() == 1


def test_unsupported_file_type_is_rejected(db, rag, ingest):
    with pytest.raises(UnsupportedDocument):
        ingest(b"\x00\x01binary", filename="logo.png", content_type="image/png")


def test_empty_file_is_rejected(db, rag, ingest):
    with pytest.raises(ExtractionError):
        ingest(b"", filename="empty.txt")


def test_pdf_with_no_text_layer_fails_clearly(db, rag):
    """A scanned PDF should say it needs OCR, not index silently as empty."""
    from app.rag.ingest import ingest_document

    blank = make_pdf([])
    with pytest.raises(ExtractionError, match="OCR|No text"):
        ingest_document(
            db, data=blank, filename="scan.pdf", content_type="application/pdf",
            embeddings=rag.embeddings, store=rag.store,
        )
    doc = db.query(Document).one()
    assert doc.status is DocumentStatus.FAILED
    assert doc.error_message


# ==========================================================================
# Retrieval and citations
# ==========================================================================
def test_retrieval_finds_the_relevant_passage(db, rag, ingest):
    ingest(POLICY_TEXT.encode(), filename="policies.txt", title="Policies")

    hits = retrieve(db, "cancellation fee", embeddings=rag.embeddings, store=rag.store)

    assert hits
    assert "cancell" in hits[0].text.lower()


def test_retrieval_ranks_the_right_document_first(db, rag, ingest):
    ingest(b"Parking is free in the rear car park for all clients.",
           filename="parking.txt", title="Parking")
    ingest(b"Refunds are issued within 14 working days of a request.",
           filename="refunds.txt", title="Refunds")

    hits = retrieve(db, "refunds working days", embeddings=rag.embeddings, store=rag.store)
    assert hits[0].document_title == "Refunds"


def test_every_passage_carries_a_citation(db, rag, ingest):
    ingest(POLICY_TEXT.encode(), filename="policies.txt", title="Company Policies")
    hits = retrieve(db, "refund policy", embeddings=rag.embeddings, store=rag.store)

    assert hits
    for hit in hits:
        assert hit.citation
        assert "Company Policies" in hit.citation
        assert hit.document_id and hit.chunk_id
        assert 0.0 <= hit.score <= 1.0


def test_pdf_citation_includes_the_page_number(db, rag, ingest):
    pdf = make_pdf(["Refunds are issued within 14 working days."])
    ingest(pdf, filename="refunds.pdf", content_type="application/pdf", title="Refunds")

    hits = retrieve(db, "refunds working days", embeddings=rag.embeddings, store=rag.store)
    assert hits
    assert hits[0].citation == "Refunds (p. 1)"


def test_irrelevant_query_returns_nothing_rather_than_noise(db, rag, ingest):
    """Returning nothing beats a weak match the model will paraphrase into
    an invented policy."""
    ingest(b"Parking is free in the rear car park.", filename="parking.txt")

    hits = retrieve(
        db, "quantum chromodynamics lattice gauge",
        embeddings=rag.embeddings, store=rag.store,
    )
    assert hits == []


def test_empty_query_returns_nothing(db, rag, ingest):
    ingest(POLICY_TEXT.encode(), filename="p.txt")
    assert retrieve(db, "   ", embeddings=rag.embeddings, store=rag.store) == []


def test_quoted_text_comes_from_the_database_not_the_index(db, rag, ingest):
    """A stale or tampered vector store cannot change what text is quoted."""
    doc = ingest(POLICY_TEXT.encode(), filename="policies.txt", title="Policies")

    chunk = db.query(DocumentChunk).filter(
        DocumentChunk.document_id == doc.id
    ).first()
    chunk.text = "CORRECTED: cancellation requires 48 hours notice."
    db.commit()

    hits = retrieve(db, "cancellation notice hours",
                    embeddings=rag.embeddings, store=rag.store)
    texts = [h.text for h in hits]
    assert any("CORRECTED" in t for t in texts)


def test_orphaned_vector_is_skipped(db, rag, ingest):
    """Index references a chunk that no longer exists: database wins."""
    doc = ingest(POLICY_TEXT.encode(), filename="policies.txt")
    chunk = db.query(DocumentChunk).filter(
        DocumentChunk.document_id == doc.id
    ).first()
    db.delete(chunk)
    db.commit()

    hits = retrieve(db, "cancellation", embeddings=rag.embeddings, store=rag.store)
    assert all(h.chunk_id != chunk.id for h in hits)


# ==========================================================================
# Rebuild and delete
# ==========================================================================
def test_reindex_rebuilds_vectors_from_the_database(db, rag, ingest):
    """This is what survives an ephemeral filesystem wiping the index."""
    doc = ingest(POLICY_TEXT.encode(), filename="policies.txt")
    expected = rag.store.count()

    rag.store._vectors.clear()
    rag.store._meta.clear()
    assert rag.store.count() == 0
    assert retrieve(db, "cancellation", embeddings=rag.embeddings, store=rag.store) == []

    rebuilt = reindex_document(db, doc, embeddings=rag.embeddings, store=rag.store)

    assert rebuilt == expected
    assert rag.store.count() == expected
    assert retrieve(db, "cancellation fee", embeddings=rag.embeddings, store=rag.store)


def test_deleting_a_document_removes_its_chunks_and_vectors(db, rag, ingest):
    doc = ingest(POLICY_TEXT.encode(), filename="policies.txt")
    doc_id = doc.id

    delete_document(db, doc, store=rag.store)

    assert db.get(Document, doc_id) is None
    assert db.query(DocumentChunk).filter(
        DocumentChunk.document_id == doc_id
    ).count() == 0
    assert rag.store.count() == 0
    assert retrieve(db, "cancellation", embeddings=rag.embeddings, store=rag.store) == []


# ==========================================================================
# Audit redaction (Milestone 3B hardening)
# ==========================================================================
def test_booking_pii_is_not_written_to_the_audit_log(db, agent, rag):
    """Redaction happens at WRITE time: the PII must not be in the row."""
    import json
    from datetime import datetime, timedelta, timezone

    from app.governance.engine import GovernanceEngine
    from app.models import AuditLog, Conversation, Service

    convo = Conversation(session_token="redact-sess-" + "q" * 20)
    db.add(convo)
    db.commit()

    service = db.query(Service).first()
    day = datetime.now(timezone.utc) + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)

    engine = GovernanceEngine(db, agent_id=agent.id, conversation_id=convo.id)
    slot = engine.execute(
        "check_availability",
        {"service_id": service.id, "date": day.date().isoformat()},
    ).data["slots"][0]
    engine.execute("book_appointment", {
        "service_id": service.id, "starts_at": slot,
        "customer_name": "Asha Rao", "customer_email": "asha@example.com",
    })

    row = (
        db.query(AuditLog)
        .filter(AuditLog.tool_name == "book_appointment")
        .order_by(AuditLog.id.desc()).first()
    )
    stored = json.loads(row.params_json)

    assert stored["customer_name"] == "[redacted]"
    assert stored["customer_email"] == "[redacted]"
    assert "Asha Rao" not in row.params_json
    assert "asha@example.com" not in row.params_json
    # Operationally useful fields survive.
    assert stored["service_id"] == service.id
    assert stored["starts_at"] == slot


def test_redaction_does_not_break_non_sensitive_params(db, agent):
    import json

    from app.governance.engine import GovernanceEngine
    from app.models import AuditLog

    GovernanceEngine(db, agent_id=agent.id).execute(
        "search_services", {"query": "review"}
    )
    row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert json.loads(row.params_json) == {"query": "review"}


def test_long_free_text_is_truncated_not_stored_whole(db, agent):
    import json

    from app.governance.engine import GovernanceEngine
    from app.models import AuditLog, Conversation

    convo = Conversation(session_token="trunc-sess-" + "r" * 20)
    db.add(convo)
    db.commit()

    long_summary = "x" * 900
    GovernanceEngine(db, agent_id=agent.id, conversation_id=convo.id).execute(
        "escalate_to_human", {"reason": "billing", "summary": long_summary}
    )
    row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    stored = json.loads(row.params_json)
    assert "truncated" in stored["summary"]
    assert len(stored["summary"]) < 300


def test_action_requests_keep_real_parameters_for_execution(db, agent, booked_appointment):
    """Redaction must NOT touch action_requests -- the approved action has
    to execute with the real values, and the hash is computed over them."""
    import json

    from app.governance.action_requests import compute_params_hash
    from app.governance.engine import GovernanceEngine
    from app.models import ActionRequest
    from app.models.enums import Permission
    from tests.conftest import grant

    grant(db, agent, Permission.CANCEL_APPOINTMENT)
    result = GovernanceEngine(db, agent_id=agent.id).execute(
        "cancel_appointment",
        {"appointment_id": booked_appointment.id, "reason": "real reason"},
    )
    row = db.get(ActionRequest, result.action_request_id)
    params = json.loads(row.params_json)

    assert params["appointment_id"] == booked_appointment.id
    assert row.params_hash == compute_params_hash("cancel_appointment", params)
