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

## Architecture

```mermaid
flowchart TD
    C["Customer"] --> FE["React + TypeScript<br/>Vite · Tailwind"]
    A["Administrator"] --> FE
    FE -->|"REST, JWT for admin"| API["FastAPI"]

    API --> ORCH["Agent Orchestrator<br/><i>hand-written tool loop</i>"]
    ORCH <-->|"messages + tool schemas"| CLAUDE["Claude Messages API"]
    ORCH --> MEM[("Conversation<br/>memory")]

    ORCH -->|"tool_use block<br/><b>= data, not an action</b>"| GOV

    subgraph GOV["Governance Engine — sole caller of any tool"]
        direction TB
        K["1 · Kill switch"] --> T["2 · Tool exists?"]
        T --> V["3 · Schema validation"]
        V --> P["4 · Permission<br/><i>from the database</i>"]
        P --> R["5 · Risk classification"]
        R --> X["6 · Execute"]
    end

    R -->|"HIGH risk"| AR[("action_requests<br/>withheld")]
    AR --> ADMIN["Human approval<br/><i>bound to params_hash</i>"]
    ADMIN -->|"approved"| X

    X --> TOOLS["Tool implementations"]
    TOOLS --> DB[("SQLite<br/>SQLAlchemy")]

    GOV ==>|"every path, including refusals"| AUDIT[("audit_logs<br/>append-only")]

    ORCH -.->|"search_knowledge_base"| RAG
    subgraph RAG["Retrieval"]
        direction LR
        EMB["all-MiniLM-L6-v2<br/><i>local, 384-dim</i>"] --> CH[("ChromaDB<br/>vectors")]
        CH --> SRC[("SQLite<br/>chunk text = source of truth")]
    end

    style GOV fill:#f4f1fe,stroke:#5b4bdb,stroke-width:2px
    style AUDIT fill:#eef9f1,stroke:#2e9e5b
    style AR fill:#fef6ec,stroke:#d98324
    style CLAUDE fill:#f7f7f8,stroke:#888
```

**The one line that matters:** the orchestrator receives a `tool_use` block
from Claude and treats it as *data*. It has no import path to any tool
implementation — enforced by a test that parses every module under
`app/agent/` and fails the build if one imports `app.tools`. A permission
check the agent could skip by importing a function directly would be
theatre.

### Request path for a high-risk action

```mermaid
sequenceDiagram
    participant Cu as Customer
    participant Cl as Claude
    participant G as Governance Engine
    participant Ad as Administrator
    participant D as Database

    Cu->>Cl: "Cancel my appointment"
    Cl-->>G: tool_use: cancel_appointment(id=7)
    G->>G: kill switch · schema · permission
    G->>G: risk = HIGH → withhold
    G->>D: INSERT action_request + params_hash
    G-->>Cl: pending_approval
    Cl-->>Cu: "That needs staff approval"

    Ad->>G: GET /approvals/pending
    G-->>Ad: params + params_hash
    Ad->>G: POST approve {params_hash}
    G->>G: hash matches? re-check kill switch + permission
    G->>D: business change + EXECUTED in ONE commit
    G->>D: audit row
    Cu->>G: GET /chat/status
    G-->>Cu: "Done — this has been completed"
```

## Quick start (Windows PowerShell)

**If you just want it running:**

```powershell
.\setup.ps1                 # one time: venv, dependencies, .env, migrations, admin
cd backend; .\.venv\Scripts\Activate.ps1; python -m scripts.seed_demo; cd ..
.\start.ps1                 # starts both servers and opens the browser
```

Then see [`DEMO.md`](DEMO.md) for a 5-7 minute walkthrough script.

Everything works without an Anthropic API key **except the chat replying**.
To enable it, put your key in `backend\.env` as `ANTHROPIC_API_KEY=sk-ant-...`
and restart. Anthropic gives $5 of free credits for a verified phone number,
which is far more than this project needs.

<details>
<summary>Manual setup, step by step</summary>


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

</details>

Customer chat at `/`, staff console at `/admin`.

## Documentation

| Document | Covers |
|---|---|
| [`backend/README.md`](backend/README.md) | Architecture, the governance invariant, test matrix, limitations |
| [`backend/docs/API.md`](backend/docs/API.md) | Every endpoint, request and response |
| [`backend/docs/RECOVERY.md`](backend/docs/RECOVERY.md) | Execution guarantees and crash recovery |
| [`backend/docs/RAG.md`](backend/docs/RAG.md) | Ingestion, retrieval, untrusted document content |
| [`frontend/README.md`](frontend/README.md) | Routes, auth handling, accessibility, bundle |
| [`DEMO.md`](DEMO.md) | Recording script, timings, and interview questions |
