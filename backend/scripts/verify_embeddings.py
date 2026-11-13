"""Verify the real embedding model works on YOUR machine.

    python -m scripts.verify_embeddings

This could not be run in the environment where the code was written --
huggingface.co was blocked there -- so run it once locally before relying
on semantic retrieval. The first run downloads about 90 MB.

Expected: each question retrieves the passage that ANSWERS it, even though
it shares few words with it. That is the difference between the real model
and the offline hashing fallback.
"""
import sys

QUESTIONS = [
    ("what happens if I call off at the last minute",
     "Appointments must be cancelled at least 24 hours in advance."),
    ("how long until I get my money back",
     "Refunds are issued within 14 working days."),
    ("where do I leave the car",
     "Free parking is available in the rear car park."),
]


def main() -> int:
    try:
        from app.rag.embeddings import SentenceTransformerEmbeddings
    except ImportError:
        print("sentence-transformers is not installed. pip install -r requirements.txt")
        return 1

    passages = [expected for _, expected in QUESTIONS]
    print("Loading sentence-transformers/all-MiniLM-L6-v2 (first run downloads ~90 MB)...")
    try:
        embedder = SentenceTransformerEmbeddings()
        vectors = embedder.embed_documents(passages)
    except Exception as exc:
        print(f"FAILED to load the model: {type(exc).__name__}: {exc}")
        print("If this is a network error, check access to huggingface.co.")
        return 1

    from app.rag.store import InMemoryVectorStore

    store = InMemoryVectorStore()
    store.upsert(
        ids=[f"p{i}" for i in range(len(passages))],
        embeddings=vectors,
        metadatas=[{"document_id": 1, "chunk_id": i} for i in range(len(passages))],
    )

    print(f"Model loaded. Dimension = {embedder.dimension}\n")
    failures = 0
    for question, expected in QUESTIONS:
        hit = store.query(embedder.embed_query(question), k=1)[0]
        got = passages[int(hit.vector_id[1:])]
        ok = got == expected
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {question!r}\n      -> {got}  ({hit.score:.3f})")

    print()
    if failures:
        print(f"{failures} of {len(QUESTIONS)} paraphrase lookups missed.")
        return 1
    print("All paraphrase lookups matched. Semantic retrieval is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
