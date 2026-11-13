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
