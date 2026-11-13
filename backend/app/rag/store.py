"""Vector stores.

The vector store holds embeddings, ids and light metadata ONLY. Chunk text
lives in SQLite, which is the source of truth. Two consequences worth
stating:

* the index is always rebuildable from the database, which matters on a
  host with an ephemeral disk (Render's free tier wipes it on redeploy);
* a retrieval result is always re-read from SQLite before being shown, so
  a stale or tampered vector store cannot change what text is quoted.
"""
import math
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class SearchHit:
    vector_id: str
    score: float
    metadata: dict[str, Any]


@runtime_checkable
class VectorStore(Protocol):
    def upsert(
        self, ids: list[str], embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None: ...
    def query(self, embedding: list[float], *, k: int) -> list[SearchHit]: ...
    def delete_document(self, document_id: int) -> None: ...
    def count(self) -> int: ...


class InMemoryVectorStore:
    """Cosine similarity over a dict. Used in tests and as a fallback."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}
        self._meta: dict[str, dict[str, Any]] = {}

    def upsert(self, ids, embeddings, metadatas) -> None:
        for vid, emb, meta in zip(ids, embeddings, metadatas, strict=True):
            self._vectors[vid] = list(emb)
            self._meta[vid] = dict(meta)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def query(self, embedding, *, k: int) -> list[SearchHit]:
        scored = [
            SearchHit(vid, self._cosine(embedding, vec), self._meta.get(vid, {}))
            for vid, vec in self._vectors.items()
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    def delete_document(self, document_id: int) -> None:
        doomed = [
            vid for vid, meta in self._meta.items()
            if meta.get("document_id") == document_id
        ]
        for vid in doomed:
            self._vectors.pop(vid, None)
            self._meta.pop(vid, None)

    def count(self) -> int:
        return len(self._vectors)


class ChromaVectorStore:
    """Persistent ChromaDB collection on local disk."""

    def __init__(self, path: str, collection_name: str = "nexadesk_documents"):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self._client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        # Chroma would otherwise install its own embedding function and
        # silently re-embed; we always pass vectors explicitly.
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )

    def upsert(self, ids, embeddings, metadatas) -> None:
        if not ids:
            return
        self._collection.upsert(
            ids=ids, embeddings=embeddings, metadatas=metadatas
        )

    def query(self, embedding, *, k: int) -> list[SearchHit]:
        if self._collection.count() == 0:
            return []
        res = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(k, self._collection.count()),
            include=["metadatas", "distances"],
        )
        hits: list[SearchHit] = []
        for vid, dist, meta in zip(
            res["ids"][0], res["distances"][0], res["metadatas"][0], strict=False
        ):
            # Chroma returns cosine DISTANCE; convert to similarity.
            hits.append(SearchHit(vid, 1.0 - float(dist), dict(meta or {})))
        return hits

    def delete_document(self, document_id: int) -> None:
        self._collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return self._collection.count()
