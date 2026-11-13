# NexaDesk AI

An AI business concierge with an enterprise agent governance layer, built
for the Napster AI Solutions Architect Intern process.

```
backend/      FastAPI, SQLAlchemy, ChromaDB, Claude    170 tests
frontend/     React, TypeScript, Vite, Tailwind v4
screenshots/  captured from the running application
```

## The idea in one sentence

> The LLM never executes anything. It only emits a request. A deterministic
> governance engine is the sole caller of every tool implementation.

Everything else follows from that. Permissions live in the database, not
the prompt. Risk is a property of the tool, not something the model reports
about itself. High-risk actions are withheld until a named human approves
the exact parameters. Every path — including every refusal — writes an
append-only audit row.

The strongest evidence is `backend/tests/test_prompt_injection.py`, where a
model scripted to **fully obey** a poisoned document still cannot cancel an
appointment.

## Quick start (Windows PowerShell)

```powershell
# --- backend ---
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
notepad .env          # ANTHROPIC_API_KEY and a JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET

alembic upgrade head
python -m scripts.create_admin
python -m scripts.verify_embeddings     # confirms the real model works
uvicorn app.main:app --reload

# --- frontend (second terminal) ---
cd frontend
npm install
npm run dev           # http://localhost:5173
```

Customer chat at `/`, staff console at `/admin`.

## Documentation

| Document | Covers |
|---|---|
| [`backend/README.md`](backend/README.md) | Architecture, the governance invariant, test matrix, limitations |
| [`backend/docs/API.md`](backend/docs/API.md) | Every endpoint, request and response |
| [`backend/docs/RECOVERY.md`](backend/docs/RECOVERY.md) | Execution guarantees and crash recovery |
| [`backend/docs/RAG.md`](backend/docs/RAG.md) | Ingestion, retrieval, untrusted document content |
| [`frontend/README.md`](frontend/README.md) | Routes, auth handling, accessibility, bundle |

## Demo script

1. Sign in at `/admin` and show the **Overview** — live counts, not fixtures.
2. **Knowledge Base** → inspect `Terms of Service`. It has a flagged
   passage; open it and read the injected instructions.
3. Go to `/` and ask about the cancellation policy. The answer is cited.
4. Ask to cancel the appointment. The reply says it needs staff approval.
5. **Approvals** → review the request. Show the exact parameters and the
   SHA-256 your decision is bound to. Approve it.
6. **Audit Logs** → filter by the action request. Three rows: the agent
   proposed, a named human decided, the system executed.
7. **Agent Controls** → emergency stop. Return to the chat and show the
   next tool call being refused.

Point at the injected document again and note that the agent read it and
still could not act. That is the product.
