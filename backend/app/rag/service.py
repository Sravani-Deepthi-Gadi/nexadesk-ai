"""Process-wide RAG dependencies.

A single settable bundle rather than a lru_cache, so tests can swap in the
offline providers with one call instead of fighting a cache.
"""
from dataclasses import dataclass

from app.config import get_settings
from app.rag.embeddings import EmbeddingProvider, get_embedding_provider
from app.rag.store import ChromaVectorStore, InMemoryVectorStore, VectorStore


@dataclass
class RagBundle:
    embeddings: EmbeddingProvider
    store: VectorStore


_bundle: RagBundle | None = None


def build_from_settings() -> RagBundle:
    settings = get_settings()
    embeddings = get_embedding_provider(
        settings.embedding_provider, settings.embedding_model
    )
    if settings.vector_store == "chroma":
        store: VectorStore = ChromaVectorStore(settings.chroma_path)
    elif settings.vector_store == "memory":
        store = InMemoryVectorStore()
    else:
        raise ValueError(f"Unknown vector store: {settings.vector_store}")
    return RagBundle(embeddings=embeddings, store=store)


def get_rag() -> RagBundle:
    global _bundle
    if _bundle is None:
        _bundle = build_from_settings()
    return _bundle


def set_rag(bundle: RagBundle) -> None:
    global _bundle
    _bundle = bundle


def reset_rag() -> None:
    global _bundle
    _bundle = None
