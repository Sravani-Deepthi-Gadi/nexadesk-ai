"""Admin knowledge-base management: upload, list, inspect, reindex, delete."""
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, require_admin
from app.db.session import get_db
from app.models import AdminUser, Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.rag.ingest import (
    DocumentTooLarge, DuplicateDocument, delete_document, ingest_document,
    reindex_document,
)
from app.rag.loader import MAX_UPLOAD_BYTES, ExtractionError, UnsupportedDocument
from app.rag.service import get_rag

router = APIRouter(prefix="/api/admin/documents", tags=["admin:documents"])


class DocumentOut(BaseModel):
    id: int
    filename: str
    title: str
    content_type: str
    size_bytes: int
    status: str
    chunk_count: int
    suspicious_chunk_count: int
    error_message: str | None
    uploaded_at: str
    uploaded_by_admin_id: int | None

    @classmethod
    def from_row(cls, row: Document) -> "DocumentOut":
        return cls(
            id=row.id, filename=row.filename, title=row.title,
            content_type=row.content_type, size_bytes=row.size_bytes,
            status=row.status.value, chunk_count=row.chunk_count,
            suspicious_chunk_count=row.suspicious_chunk_count,
            error_message=row.error_message,
            uploaded_at=row.uploaded_at.isoformat(),
            uploaded_by_admin_id=row.uploaded_by_admin_id,
        )


class ChunkOut(BaseModel):
    id: int
    chunk_index: int
    page_number: int | None
    char_count: int
    is_suspicious: bool
    text: str


def _get_or_404(db: Session, document_id: int) -> Document:
    row = db.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return row


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> DocumentOut:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    rag = get_rag()
    try:
        result = ingest_document(
            db, data=data,
            filename=file.filename or "upload",
            content_type=file.content_type or "",
            embeddings=rag.embeddings, store=rag.store,
            title=title, uploaded_by_admin_id=admin.id,
        )
    except DuplicateDocument as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Already indexed as document {exc.existing.id}.",
        ) from None
    except UnsupportedDocument as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from None
    except (ExtractionError, DocumentTooLarge) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None

    return DocumentOut.from_row(result.document)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    document_status: DocumentStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[DocumentOut]:
    query = db.query(Document)
    if document_status is not None:
        query = query.filter(Document.status == document_status)
    return [
        DocumentOut.from_row(r)
        for r in query.order_by(Document.uploaded_at.desc()).all()
    ]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> DocumentOut:
    return DocumentOut.from_row(_get_or_404(db, document_id))


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def list_chunks(
    document_id: int,
    suspicious_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[ChunkOut]:
    """Inspect what was actually indexed.

    `suspicious_only=true` shows the passages that tripped the injection
    heuristics -- the point of the flag is that a human can look.
    """
    _get_or_404(db, document_id)
    query = db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id)
    if suspicious_only:
        query = query.filter(DocumentChunk.is_suspicious.is_(True))
    return [
        ChunkOut(
            id=c.id, chunk_index=c.chunk_index, page_number=c.page_number,
            char_count=c.char_count, is_suspicious=c.is_suspicious, text=c.text,
        )
        for c in query.order_by(DocumentChunk.chunk_index).all()
    ]


@router.post("/{document_id}/reindex", response_model=DocumentOut)
def reindex(
    document_id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
) -> DocumentOut:
    """Rebuild this document's vectors from the chunk text in the database.

    Needed after a host wipes the vector store -- the text is still in
    SQLite, so nothing has to be re-uploaded.
    """
    row = _get_or_404(db, document_id)
    rag = get_rag()
    reindex_document(db, row, embeddings=rag.embeddings, store=rag.store)
    db.refresh(row)
    return DocumentOut.from_row(row)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    document_id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
) -> None:
    row = _get_or_404(db, document_id)
    delete_document(db, row, store=get_rag().store)
