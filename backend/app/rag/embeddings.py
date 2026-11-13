"""Embedding providers.

Anthropic does not offer an embedding model, so this is a local model:
``sentence-transformers/all-MiniLM-L6-v2``. It is free, runs on CPU, needs
no extra account, and is more than good enough for a few business
documents. The provider is an interface so a hosted model (Voyage AI, say)
can be dropped in without touching the retriever.

``HashingEmbeddings`` is the test provider: deterministic, dependency-free,
and based on lexical overlap. It is NOT semantic -- it cannot match
"what does it cost" to "pricing" -- so retrieval-quality claims proven with
it are weaker than with the real model. Tests say which they use.
"""
import hashlib
import math
import re
from typing import Protocol, runtime_checkable

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbeddings:
    """Local all-MiniLM-L6-v2 (384 dimensions).

    The model is loaded lazily and once: construction is cheap, the first
    embed call pays for loading (and, on a cold machine, downloading).
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.name = model_name
        self.dimension = 384
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.name)
            self.dimension = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return [list(map(float, v)) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbeddings:
    """Deterministic hashed bag-of-words. For tests and offline fallback.

    Lexical, not semantic. Included so the suite never depends on a model
    download, and so the pipeline can be exercised on a machine without
    PyTorch.
    """

    def __init__(self, dimension: int = 256):
        self.name = f"hashing-{dimension}"
        self.dimension = dimension

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = _TOKEN.findall(text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def get_embedding_provider(provider: str, model_name: str = DEFAULT_MODEL) -> EmbeddingProvider:
    if provider == "sentence-transformers":
        return SentenceTransformerEmbeddings(model_name)
    if provider == "hashing":
        return HashingEmbeddings()
    raise ValueError(f"Unknown embedding provider: {provider}")
