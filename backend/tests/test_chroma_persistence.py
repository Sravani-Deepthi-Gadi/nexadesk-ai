"""Persistent ChromaDB integration.

Uses the REAL ChromaVectorStore against a temporary directory, with the
offline embedding provider. The point is to prove persistence and
document-scoped deletion actually work against Chroma -- not against the
in-memory stand-in the rest of the suite uses.

Skipped if chromadb is not installed.
"""
import tempfile
from pathlib import Path

import pytest

chromadb = pytest.importorskip("chromadb")

from app.rag.embeddings import HashingEmbeddings  # noqa: E402
from app.rag.store import ChromaVectorStore  # noqa: E402

DOCS = [
    "Appointments must be cancelled at least 24 hours in advance.",
    "Refunds are issued within 14 working days.",
    "Free parking is available in the rear car park.",
]


@pytest.fixture
def chroma_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield str(Path(tmp) / "chroma")


def test_vectors_survive_reopening_the_store(chroma_dir):
    """The whole point of PersistentClient: a restart keeps the index."""
    emb = HashingEmbeddings()

    first = ChromaVectorStore(chroma_dir)
    first.upsert(
        ids=["doc1-chunk0", "doc1-chunk1", "doc2-chunk0"],
        embeddings=emb.embed_documents(DOCS),
        metadatas=[
            {"document_id": 1, "chunk_index": 0, "chunk_id": 10},
            {"document_id": 1, "chunk_index": 1, "chunk_id": 11},
            {"document_id": 2, "chunk_index": 0, "chunk_id": 20},
        ],
    )
    assert first.count() == 3
    del first

    reopened = ChromaVectorStore(chroma_dir)
    assert reopened.count() == 3

    hits = reopened.query(emb.embed_query("cancelled hours advance"), k=1)
    assert hits
    assert hits[0].vector_id == "doc1-chunk0"
    assert hits[0].metadata["chunk_id"] == 10


def test_similarity_scores_are_similarities_not_distances(chroma_dir):
    """Chroma returns cosine DISTANCE; the store must convert it, or the
    relevance threshold in the retriever would be inverted."""
    emb = HashingEmbeddings()
    store = ChromaVectorStore(chroma_dir)
    store.upsert(
        ids=["a", "b"],
        embeddings=emb.embed_documents(DOCS[:2]),
        metadatas=[{"document_id": 1}, {"document_id": 1}],
    )

    hits = store.query(emb.embed_query("refunds working days"), k=2)
    assert hits[0].vector_id == "b"
    assert hits[0].score > hits[1].score
    assert 0.0 <= hits[0].score <= 1.0


def test_deleting_one_document_leaves_the_others(chroma_dir):
    emb = HashingEmbeddings()
    store = ChromaVectorStore(chroma_dir)
    store.upsert(
        ids=["doc1-chunk0", "doc1-chunk1", "doc2-chunk0"],
        embeddings=emb.embed_documents(DOCS),
        metadatas=[
            {"document_id": 1}, {"document_id": 1}, {"document_id": 2},
        ],
    )

    store.delete_document(1)

    assert store.count() == 1
    hits = store.query(emb.embed_query("parking car park"), k=1)
    assert hits[0].vector_id == "doc2-chunk0"


def test_upsert_is_idempotent(chroma_dir):
    """Re-indexing the same document must not duplicate vectors."""
    emb = HashingEmbeddings()
    store = ChromaVectorStore(chroma_dir)
    payload = dict(
        ids=["doc1-chunk0"],
        embeddings=emb.embed_documents(DOCS[:1]),
        metadatas=[{"document_id": 1}],
    )
    store.upsert(**payload)
    store.upsert(**payload)
    assert store.count() == 1


def test_query_on_an_empty_collection_returns_nothing(chroma_dir):
    store = ChromaVectorStore(chroma_dir)
    assert store.count() == 0
    assert store.query(HashingEmbeddings().embed_query("anything"), k=4) == []
