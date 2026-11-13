"""Document ingestion pipeline.

    bytes -> extract -> chunk -> persist to SQLite -> embed -> vector store

SQLite is written BEFORE the vector store, deliberately. Chunk text in the
database is the source of truth; the index is a derived artifact that can
be rebuilt with reindex_document(). If embedding fails, the document is
marked FAILED but its text survives for a retry.
"""
import hashlib
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.rag.chunker import chunk_pages
from app.rag.embeddings import EmbeddingProvider
from app.rag.loader import (
    MAX_UPLOAD_BYTES, ExtractionError, UnsupportedDocument, detect_kind,
    extract_pages,
)
from app.rag.sanitize import looks_suspicious
from app.rag.store import VectorStore


class DocumentTooLarge(Exception):
    pass


class DuplicateDocument(Exception):
    def __init__(self, existing: Document):
        self.existing = existing
        super().__init__(f"This file is already indexed as document {existing.id}.")


@dataclass
class IngestResult:
    document: Document
    chunks_created: int
    suspicious_chunks: int


def _vector_id(document_id: int, chunk_index: int) -> str:
    return f"doc{document_id}-chunk{chunk_index}"


def ingest_document(
    db: Session,
    *,
    data: bytes,
    filename: str,
    content_type: str,
    embeddings: EmbeddingProvider,
    store: VectorStore,
    title: str = "",
    uploaded_by_admin_id: int | None = None,
) -> IngestResult:
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentTooLarge(
            f"File is {len(data)} bytes; the limit is {MAX_UPLOAD_BYTES}."
        )
    if not data:
        raise ExtractionError("The uploaded file is empty.")

    detect_kind(filename, content_type)  # raises UnsupportedDocument early

    digest = hashlib.sha256(data).hexdigest()
    existing = db.query(Document).filter(Document.sha256 == digest).one_or_none()
    if existing is not None:
        raise DuplicateDocument(existing)

    document = Document(
        filename=filename,
        title=title or filename,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(data),
        sha256=digest,
        status=DocumentStatus.PENDING,
        uploaded_by_admin_id=uploaded_by_admin_id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        pages = extract_pages(data, filename=filename, content_type=content_type)
        chunks = chunk_pages(pages)
        if not chunks:
            raise ExtractionError("No usable text was found in the document.")

        suspicious = 0
        rows: list[DocumentChunk] = []
        for chunk in chunks:
            flagged = looks_suspicious(chunk.text)
            suspicious += int(flagged)
            rows.append(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    text=chunk.text,
                    char_count=len(chunk.text),
                    page_number=chunk.page_number,
                    vector_id=_vector_id(document.id, chunk.index),
                    is_suspicious=flagged,
                )
            )
        db.add_all(rows)
        document.chunk_count = len(rows)
        document.suspicious_chunk_count = suspicious
        db.commit()

        # Index only after the text is durably stored.
        _index_chunks(rows, embeddings=embeddings, store=store)

        document.status = DocumentStatus.INDEXED
        db.commit()
        db.refresh(document)
        return IngestResult(document, len(rows), suspicious)

    except (ExtractionError, UnsupportedDocument) as exc:
        db.rollback()
        document.status = DocumentStatus.FAILED
        document.error_message = str(exc)
        db.commit()
        raise
    except Exception as exc:
        db.rollback()
        document.status = DocumentStatus.FAILED
        document.error_message = f"{type(exc).__name__}: {exc}"
        db.commit()
        raise


def _index_chunks(
    rows: list[DocumentChunk], *, embeddings: EmbeddingProvider, store: VectorStore
) -> None:
    if not rows:
        return
    vectors = embeddings.embed_documents([r.text for r in rows])
    store.upsert(
        ids=[r.vector_id for r in rows],
        embeddings=vectors,
        metadatas=[
            {
                "document_id": r.document_id,
                "chunk_index": r.chunk_index,
                "chunk_id": r.id,
            }
            for r in rows
        ],
    )


def reindex_document(
    db: Session, document: Document, *, embeddings: EmbeddingProvider, store: VectorStore
) -> int:
    """Rebuild one document's vectors from the chunk text in SQLite.

    This is what makes an ephemeral filesystem survivable: the index is
    never the only copy.
    """
    store.delete_document(document.id)
    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    _index_chunks(rows, embeddings=embeddings, store=store)
    document.status = DocumentStatus.INDEXED
    db.commit()
    return len(rows)


def delete_document(
    db: Session, document: Document, *, store: VectorStore
) -> None:
    store.delete_document(document.id)
    db.delete(document)   # chunks cascade
    db.commit()
