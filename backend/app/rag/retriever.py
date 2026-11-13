"""Semantic retrieval with source citations.

Two properties worth naming:

* **Text is re-read from SQLite.** The vector store returns ids and scores;
  the passage quoted back comes from the database. A stale or tampered
  index cannot change what text the model sees.
* **Every passage carries its citation and is wrapped as data.** The
  caller gets an envelope that identifies the source document and page,
  with content neutralised (see app/rag/sanitize.py).
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.rag.embeddings import EmbeddingProvider
from app.rag.sanitize import wrap_excerpt
from app.rag.store import VectorStore

DEFAULT_TOP_K = 4
#: Below this cosine similarity a passage is treated as not relevant.
#: Returning nothing is better than returning noise the model will
#: paraphrase into an invented policy.
MIN_SCORE = 0.15


@dataclass
class RetrievedPassage:
    chunk_id: int
    document_id: int
    document_title: str
    filename: str
    page_number: int | None
    score: float
    text: str
    is_suspicious: bool

    @property
    def citation(self) -> str:
        if self.page_number is not None:
            return f"{self.document_title} (p. {self.page_number})"
        return self.document_title

    def as_excerpt(self) -> str:
        return wrap_excerpt(self.text, source=self.citation, chunk_id=self.chunk_id)


def retrieve(
    db: Session,
    query: str,
    *,
    embeddings: EmbeddingProvider,
    store: VectorStore,
    k: int = DEFAULT_TOP_K,
    min_score: float = MIN_SCORE,
) -> list[RetrievedPassage]:
    if not query.strip():
        return []

    hits = store.query(embeddings.embed_query(query), k=k)
    passages: list[RetrievedPassage] = []

    for hit in hits:
        if hit.score < min_score:
            continue
        chunk_id = hit.metadata.get("chunk_id")
        chunk = (
            db.get(DocumentChunk, chunk_id)
            if chunk_id is not None
            else db.query(DocumentChunk)
            .filter(DocumentChunk.vector_id == hit.vector_id)
            .one_or_none()
        )
        if chunk is None:
            # Index references a chunk that no longer exists. Skip it; the
            # database wins. reindex_document() clears this up.
            continue
        document = db.get(Document, chunk.document_id)
        if document is None:
            continue
        passages.append(
            RetrievedPassage(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title or document.filename,
                filename=document.filename,
                page_number=chunk.page_number,
                score=round(float(hit.score), 4),
                text=chunk.text,
                is_suspicious=chunk.is_suspicious,
            )
        )
    return passages
