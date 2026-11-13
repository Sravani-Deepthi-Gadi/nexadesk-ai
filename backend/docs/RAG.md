# Knowledge base: ingestion, retrieval and untrusted content

## Pipeline

```
upload -> extract -> chunk -> SQLite -> embed -> vector store
                                 ^                    |
                                 |                    v
                            source of truth      derived index
```

SQLite is written **before** the vector store and holds the chunk text.
The index holds embeddings, ids and light metadata only. Two consequences:

* `POST /api/admin/documents/{id}/reindex` rebuilds the index from the
  database, so a host that wipes the disk (Render's free tier does this on
  every redeploy) costs you a reindex, not a re-upload.
* A retrieval hit is always re-read from SQLite before being quoted. A
  stale or tampered index cannot change what text the model sees.

## Components

| Concern | Production | Tests / offline |
|---|---|---|
| Embeddings | `SentenceTransformerEmbeddings` — local all-MiniLM-L6-v2, 384 dims | `HashingEmbeddings` — deterministic, lexical |
| Vector store | `ChromaVectorStore` — persistent, cosine | `InMemoryVectorStore` |

Anthropic does not publish an embedding model, so this is local and free —
no second API key, no per-token cost. Swap in a hosted provider (Voyage AI)
by implementing `EmbeddingProvider`.

**`HashingEmbeddings` is lexical, not semantic.** It matches
"cancellation" to "cancellation", not "what if I call off late" to the
cancellation policy. Tests using it prove the pipeline, ranking, citations
and isolation — they are not evidence about the real model's paraphrase
quality. Run `python -m scripts.verify_embeddings` to check that locally.

Chunking is paragraph-aware: 1000 characters with 150 of overlap. The
overlap matters — a policy sentence split across a boundary would
otherwise be retrievable by neither half.

Retrieval returns nothing below a cosine similarity of `0.15`. An empty
result the model can report beats a weak match it will paraphrase into an
invented policy.

## Untrusted document content

**The honest version:** text filtering against prompt injection is a
mitigation, not a control. A sufficiently clever injection will eventually
beat any pattern list.

Four layers, in increasing order of how much they actually buy:

1. **Retrieved text never enters the system prompt.** It arrives as a tool
   *result*, structurally positioned as data.
2. **Envelope integrity.** Each passage is wrapped in `<<<DOCUMENT_EXCERPT>>>`
   markers, and those markers are stripped from the content first — so a
   document cannot close its own envelope and continue as if it were the
   system.
3. **Structural neutralisation.** Line-initial `Human:` / `Assistant:` /
   `System:` lose their colon; `<system>`-style tags become inert text. The
   words survive as prose; the structure does not. Applied at *retrieval*,
   so the stored chunk stays faithful to the uploaded file and an
   administrator reads back what they actually uploaded.
4. **The governance engine.** This is the layer that holds.

Layers 1–3 reduce the chance the model is fooled. Layer 4 makes being
fooled survivable: a compromised model can only *propose* a tool call, and
permission, risk and human approval still stand between the proposal and
the database.

`tests/test_prompt_injection.py` proves it the hard way — the fake model is
scripted to obey a poisoned document **completely**, with
`CANCEL_APPOINTMENT` granted so permission is not what saves us. The
appointment is still `BOOKED` afterwards, because cancellation is HIGH risk.

Suspicious passages are flagged at ingest (`suspicious_chunk_count`) and
readable at `GET /api/admin/documents/{id}/chunks?suspicious_only=true`.
That flag is a prompt for human review, never an allow/deny decision.

## Customer data isolation

`get_customer_details` takes **no parameters**. The customer is resolved
from the conversation the tool is running inside, via `ToolContext`, which
the *engine* constructs — never the model.

The agent cannot express a request for someone else's record, so no prompt
and no poisoned document can talk it into one. Isolation is structural
rather than a rule the model is asked to follow. The same principle governs
`GET /api/chat/status`, which is scoped by session token alone with no
conversation id parameter.

## Limitations

1. **Semantic retrieval quality is unverified in CI.** The suite runs on
   the lexical fallback. Verify the real model with
   `python -m scripts.verify_embeddings`.
2. **No OCR.** A scanned PDF is rejected with an explanation rather than
   indexed as empty.
3. **No reranking.** Top-k by cosine similarity only. A cross-encoder
   reranker would improve precision on larger corpora.
4. **The `0.15` threshold is a guess**, tuned against the lexical provider.
   It should be re-tuned once the real model is in use.
5. **Chunking is character-based, not token-based.** Fine for these
   documents; a token-aware splitter is better for mixed scripts.
6. **Ingestion is synchronous.** A large PDF blocks the upload request. It
   belongs on a background worker.
7. **Injection heuristics are English-only** and pattern-based. They will
   miss novel phrasing and other languages. Layer 4 is what you rely on.
8. **No per-document access control.** Every indexed document is visible to
   every customer conversation.
