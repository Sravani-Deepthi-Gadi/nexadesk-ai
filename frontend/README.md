# NexaDesk AI — Frontend (Milestone 3B)

React + TypeScript + Vite + Tailwind CSS v4 + Lucide + Recharts.

Every screen is wired to the real backend. There is no mock data anywhere
in the application: if the API is down, the UI says so rather than
rendering placeholders.

## Setup (Windows PowerShell)

```powershell
cd frontend
npm install
Copy-Item .env.example .env   # optional; the dev proxy works without it
npm run dev                   # http://localhost:5173
```

The backend must be running on `http://127.0.0.1:8000`. In development
Vite proxies `/api` to it, so the browser makes same-origin requests and no
backend host is compiled into the bundle.

```powershell
npm run build      # type-check + production build
npm run preview    # serve the build on :4173, proxying /api
```

For a deployed frontend, set `VITE_API_BASE_URL` to the API's public URL.
**Never put a secret in a `.env` here** — everything in a frontend build is
visible to every visitor. The only value this app needs is a URL.

## Routes

| Route | Access |
|---|---|
| `/` | Public customer chat |
| `/login` | Admin sign-in |
| `/admin` | Overview — KPIs, 7-day chart, risk split, recent activity |
| `/admin/conversations` | Transcripts and escalations |
| `/admin/knowledge` | Upload, inspect, reindex, delete documents |
| `/admin/approvals` | Review, approve and reject withheld actions |
| `/admin/agent` | Emergency stop and permissions |
| `/admin/audit` | Filterable audit trail |

## How authentication is handled

The JWT lives in `localStorage` under one key and is attached by
`src/lib/api.ts` alone. Three things follow from that:

- **The token is verified, not trusted.** On load the app calls
  `/auth/me`; a revoked or expired token never produces a UI that looks
  signed in.
- **Role comes from the server.** It is read from the `/auth/me` response,
  never decoded from the JWT body — that is client-side data and proves
  nothing. Hiding a button is a courtesy; the backend re-checks the role on
  every request, which is what actually stops a viewer from acting.
- **Any 401 ends the session.** The client clears the token and the app
  redirects to a login page that explains the session expired, rather than
  bouncing silently.

### Known limitation

`localStorage` is readable by any script on the origin, so a cross-site
scripting bug would expose the token. The safer pattern is a `HttpOnly`
cookie plus CSRF protection, which needs backend changes. Tokens are
short-lived (60 minutes by default) and deactivating an account takes
effect immediately, which limits the window but does not close it.

## Guardrails in the UI

- **Viewers cannot act.** Upload, delete, reindex, approve, reject,
  emergency stop and permission toggles are hidden or disabled, and the UI
  says why rather than silently omitting them.
- **Confirmation before anything irreversible.** Approving an action,
  deleting a document, engaging the emergency stop and granting a
  high-risk permission each require a second, explicit step.
- **The parameter hash is shown before approval.** The exact parameters and
  the full SHA-256 are displayed, and that hash is sent back with the
  decision. If the stored request changed in between, the backend returns
  409 and the decision is refused.

## Accessibility

Semantic landmarks and heading order; labels on every input (visually
hidden where the design has no room); `role="dialog"` with `aria-modal`,
focus moved on open and Escape to close; `role="switch"` with
`aria-checked` on permission toggles; live regions for toasts and loading
states; visible focus rings throughout; `prefers-reduced-motion` honoured.

Not done: a full screen-reader pass, and no automated axe run in CI.

## Bundle

Code-split so the public chat does not download the admin area:

```
index          292 kB (93 kB gzip)   shared app + chat
Overview       393 kB (112 kB gzip)  lazy — includes Recharts
other admin     4–10 kB each         lazy
```

Recharts dominates the Overview chunk. A lighter charting library, or
hand-rolled SVG, would cut it substantially if that mattered.
