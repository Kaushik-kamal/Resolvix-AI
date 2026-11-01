# Resolvix Ops (Member C): Ops API, SMS service, Staff Dashboard

```
ops/
  api/        FastAPI + SQLite service (calls, tickets, SSE, SMS, gaps, knowledge base, auth)   -> api/README.md
  dashboard/  React + Vite staff dashboard (live board, tickets, calls, gaps, KB, rules)        -> dashboard/README.md, COMPONENTS.md
  docs/       MEMBER_C_PRD.md (spec), DECISIONS.md, SSE_EVENTS.md, AGENT_PLAN.md, REVIEW.md, integration/
```

The contract lives in `../contracts` (frozen; this project never edits it): `openapi/ops-api.yaml`, the `resolvix_contracts`
Python models, `fixtures/`, `config/`.

## Setup on Windows (PowerShell)

Needs Python 3.11 (`py -V:Astral/CPython3.11` or any 3.11), Node 20+ and npm. Always run Python with `-X utf8`
(the config files contain Devanagari).

```powershell
cd ops/api
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ../../contracts/python
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env        # then set SERVICE_KEY, SESSION_SECRET (32+ chars) and SEED_PASSWORD

cd ../dashboard
npm install
copy .env.example .env        # optional: leave VITE_OPS_API_URL empty in development (the dev server proxies /v1)
```

## Run

```powershell
# terminal 1: API on :8100 (creates data/resolvix.db and the 4 seed users on first start)
cd ops/api
.\.venv\Scripts\python.exe -X utf8 dev\seed.py                 # KB entries (12 approved + 1 draft "bus route"), users; idempotent
.\.venv\Scripts\python.exe -X utf8 -m uvicorn resolvix_ops.app:app --port 8100 --loop asyncio --workers 1

# terminal 2: dashboard on :5173
cd ops/dashboard
npm run dev

# terminal 3: fill the system with realistic traffic (acts as the voice runtime; 9 scenarios from contracts/fixtures/brain_streams)
cd ops/api
.\.venv\Scripts\python.exe -X utf8 dev\simulate_calls.py --speed 5
```

Use a single uvicorn worker: the SSE hub and the login limiter live in process memory.

### Seed users

| Email | Role | Department |
|---|---|---|
| `admin@demo` | admin (everything, KB approve/archive/publish) | all |
| `exam@demo` | staff | exam_cell |
| `accounts@demo` | staff | accounts |
| `hostel@demo` | staff | hostel |

The password for all of them is `SEED_PASSWORD` from `ops/api/.env`. Staff only see their own department (see Assumptions).

## Environment

`ops/api/.env.example` (all settings can also be set as environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 8100 | server port (uvicorn `--port` is what actually binds) |
| `DATABASE_URL` | `sqlite:///./data/resolvix.db` | SQLite file (WAL, BEGIN IMMEDIATE) |
| `SERVICE_KEY` | (required) | `X-Service-Key` shared with the voice runtime |
| `SESSION_SECRET` | (required, 32+ chars) | signs the 12 h session cookie |
| `SEED_PASSWORD` | `DemoPassword123!` | password of the seed users |
| `OPS_PUBLIC_URL` | `http://localhost:8100` | public base URL: Twilio status callback and KB export location |
| `CORS_ORIGINS` | `http://localhost:5173` | allowed dashboard origins (cookies enabled) |
| `RUNTIME_MODE` / `RUNTIME_URL` | `mock` / `http://localhost:8000` | `live` makes KB publish call `{RUNTIME_URL}/admin/kb/reload` |
| `NOTIFY_MODE` | `mock` | `mock` or `twilio` (`live` = alias) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | empty | required when `NOTIFY_MODE=twilio` (startup fails fast otherwise) |
| `NOTIFY_ASYNC` | empty | empty: status SMS sent from a worker thread in twilio mode, in-request in mock mode |
| `SMS_SEND_TIMEOUT_S`, `SMS_POLL_ENABLED`, `SMS_POLL_DELAY_S` | 5, true, 10 | send timeout (one retry), delayed status poll when the callback URL is localhost |
| `LOGIN_RATE_LIMIT_PER_MIN` | 10 | login attempts per minute per IP (0 = off) |
| `KB_IMPORT_MAX_BYTES`, `KB_IMPORT_MAX_LINES`, `KB_PUBLISH_TIMEOUT_S` | 2 MB, 2000, 30 | KB limits |
| `STAFF_SCOPE_ENABLED` | true | department scoping for staff |
| `GAP_CLUSTER_STRATEGY` | `keywords` | `embedding` exists but has only run against mocked HTTP; it needs `EMBEDDING_API_KEY` (+ `EMBEDDING_API_URL`, `EMBEDDING_MODEL`), see BLOCKERS.md B1 |
| `DEPARTMENTS_FILE`, `URGENCY_RULES_FILE`, `SMS_TEMPLATES_FILE`, `TIMEZONE` | contracts/config paths, `Asia/Kolkata` | config files |

`ops/dashboard/.env.example`: `VITE_OPS_API_URL` (empty in dev; the Vite proxy forwards `/v1` and `/healthz`),
`VITE_PROXY_TARGET` (default `http://localhost:8100`), `VITE_RUNTIME_URL` (links to A's web-call and typed-test pages).

## Mock modes and the DLT note

- **SMS `mock`** (default): nothing is sent. Every SMS is recorded with `mode=mock`; the dashboard shows "SMS (mock)". Mock
  or test-sender messages are not production delivery and are never shown as delivered.
- **SMS `twilio`**: Twilio Messages REST API, 5 s timeout, one retry, then the record is `failed` and flagged. Delivery status
  arrives on `POST /v1/notifications/sms/status` (signature-verified) or through one status poll when `OPS_PUBLIC_URL` is
  localhost. Indian SMS needs a DLT-registered sender id and DLT-approved templates: the wording in
  `contracts/config/sms_templates.yaml` must match the registered templates before live sending. Live Twilio was not
  exercised (no credentials); only mocked HTTP.
- **KB publish `mock`** (`RUNTIME_MODE=mock`): returns a fixture-based KBVersionInfo with a visible "mock publish" warning and
  records it in the history; nothing reaches the voice runtime. `live` calls A and was only tested against mocked HTTP.

## Tests

```powershell
cd ops/api
.\.venv\Scripts\python.exe -X utf8 -m pytest -q                      # ops suite (temp databases, no network)
.\.venv\Scripts\python.exe -X utf8 -m pytest ../../contracts/tests -q
.\.venv\Scripts\python.exe -X utf8 dev\check_openapi_coverage.py     # 26/26 contract endpoints (+ allowlisted extras)
.\.venv\Scripts\python.exe -X utf8 dev\guard_forbidden.py compare    # frozen paths unchanged: must print OK
.\.venv\Scripts\python.exe -X utf8 dev\smoke.py                      # real uvicorn on a throwaway DB: auth, calls, tickets, SSE, SMS, gaps, KB
.\.venv\Scripts\python.exe -X utf8 dev\e2e_journeys.py               # journeys J5 and J6 over HTTP
cd ../dashboard
npm test ; npm run build
```

## Manual checklist for J5 and J6 (dashboard, with `simulate_calls.py` running)

J5, staff works a P1 ticket:
1. Log in as `exam@demo`. The live board shows the P1 ticket from the urgent-exam call (red banner, beep, card flash; the mute toggle works).
2. Open Tickets, click the P1 ticket: number is masked; click Reveal (audited); open the transcript.
3. Set status to In progress, Apply; then Resolved with a resolution and a note. The timeline shows status changes and, for tickets with a callback number, "SMS (mock)" entries.
4. Check the ticket events: exactly one status SMS per distinct new status.

J6, gap to published knowledge:
1. As `admin@demo` open Gaps, pick the largest cluster, "Draft KB entry": the editor opens prefilled.
2. Fill the answer and source, save (saved as draft). A text containing "ignore all previous instructions" is flagged and cannot be approved.
3. Approve the draft, then Publish: the result shows the version and the "mock publish" warning; the history lists it. `GET /v1/kb/export` contains the entry.
4. As `exam@demo`, the approve and Publish buttons are hidden.

## Access matrix (tests/test_access_matrix.py enforces it)

| | no credentials | staff session | admin session | service key |
|---|---|---|---|---|
| GET tickets, calls, gap clusters, KB entries/export/publishes, departments, urgency rules, stream | 401 | yes (own department) | yes | yes (all) |
| PATCH ticket, PATCH gap cluster | 401 | yes (own department) | yes | yes |
| reveal=true on ticket/call detail (audited) | 401 | yes | yes | yes |
| POST calls, turns, end, tickets, ticket events, SMS, gaps | 401 | 403 | yes | yes |
| POST KB entry (draft; staff cannot overwrite approved/archived) | 401 | yes | yes | 403 |
| KB approve/archive, import, publish | 401 | 403 | yes | 403 |
| login, healthz, Twilio status callback (signature checked) | public | | | |

## Assumptions

- The voice runtime (A) is stood in for by `dev/simulate_calls.py`; the real `/admin/kb/reload` of A was never called.
- One ops-api process, SQLite, single college (timezone `Asia/Kolkata`).
- A status-change SMS goes to the ticket's `callback_number` only when the ticket also has a `call_id`; one SMS per (ticket, new status).
- Department scoping: staff see their department's tickets, gap clusters and the calls that produced those tickets; clusters without a department and calls without a ticket are admin-only; call events are not streamed to staff.
- Every KB save or import is a draft; only an admin session approves or publishes.
- Numbers are masked everywhere (`+91•••••0002`); `reveal=true` is audited. The dashboard never evaluates urgency rules.

## Known limitations

- Live Twilio, live KB publish against A, and a real browser pass of every dashboard flow by a human have not been done.
- Embedding-based gap clustering exists behind a flag but was never run against a real API (BLOCKERS B1); no analytics panel, no retention job.
- Privacy: with `GAP_CLUSTER_STRATEGY=embedding` the caller question text (digit runs of 10+ redacted) is sent to the embedding API you configure; keyword clustering sends nothing outside.
- In-memory SSE hub and login limiter: single worker only; SSE has no replay (the dashboard refetches after reconnect).
- Reveal is allowed for every authenticated principal in scope; there is no per-user reveal policy.
- A crash between "queued" and the provider result leaves a queued SMS record that is not retried.
- PII checks for SMS are regex heuristics, listed in `api/README.md`.
- `ops-api.yaml` additions (all additive, listed in DECISIONS.md): `/v1/auth/me`, `/v1/auth/logout`, `/v1/kb/publishes`, `/v1/notifications/sms/status`, query params `active`, `reveal`, `GET /v1/gaps/clusters?status=`, and `last_turn` on call list items.

## Definition of done (PRD section 10)

| Item | Status |
|---|---|
| `uvicorn` and `npm run dev` work from this README on a clean machine | Verified on this machine from a deleted dev DB (seed, uvicorn, simulator, Vite index and proxy). Not tried on a second machine. |
| `seed.py && simulate_calls.py` fill the live board with calls, a P1 alert, tickets, mock SMS and gaps | API side verified: 9 calls ended, 6 tickets (2 P1, prefixes EM/EX/HD/HS/TR), 1 gap cluster, 13 KB entries, mock SMS records. The live board rendering was checked by the dashboard agents against live data, not by a human. |
| J5 and J6 end to end | Verified over HTTP by `dev/e2e_journeys.py` (all steps PASS). The UI click-through is the manual checklist above. |
| All tests green | Ops 451 passed / 2 skipped (the two A-to-B protocol fixtures), contracts 6/6, dashboard 199 Vitest tests, build clean. |
| README, DECISIONS.md | This file, `api/README.md` (SMS policy), `docs/DECISIONS.md`, `docs/SSE_EVENTS.md`. |
