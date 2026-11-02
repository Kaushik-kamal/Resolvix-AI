# Coding-agent prompt: Member C, Ops API, SMS and Staff Dashboard

> Copy everything below this line into Claude Code, Antigravity or another coding agent, opened at the repo root.

---

You are the implementing engineer for **Member C: Ops API, SMS service and Staff Dashboard** of **Resolvix**. Resolvix is a real-time, multilingual AI voice agent that answers a college helpline. It answers only from approved knowledge, and it escalates unknown or urgent calls as **tickets** (ticket first, then transfer, SMS or callback).

You own:
- **the system of record:** calls, turns, tickets, events, SMS, knowledge gaps and KB entries
- **the SMS policy**
- **the dashboard** staff and admins use to work tickets, see knowledge gaps and publish knowledge-base updates.

Member A's voice runtime calls your API over HTTP. Member B's brain consumes your KB export. You don't need either of them running: you build against the contracts and drive your UI with a simulator.

You have full authority for routine engineering decisions. Ask the human only if two requirements contradict each other. Record decisions in `ops/docs/DECISIONS.md`.

## 1. Read first

1. `RESOLVIX_FINAL_PRD.md`: sections 3.3 (journeys J5, J6), 3.5 (FR-C1 to FR-C3), 3.8, 3.10, 3.11, 3.12, 7 (Member C).
2. **`contracts/openapi/ops-api.yaml`: implement it exactly** (paths, status codes, idempotency, `ErrorEnvelope`).
3. `contracts/python/resolvix_contracts/models.py` (use these Pydantic models directly for request and response bodies).
4. `contracts/fixtures/ops/*.json` (example payloads) and `contracts/fixtures/brain_streams/*.jsonl` (which drive your simulator).
5. `contracts/config/departments.yaml` (ticket prefixes, numbers), `urgency_rules.yaml` (read-only view), `sms_templates.yaml` (you own its content).

The contracts are **FROZEN** (v1.0.0). Don't edit `contracts/python/**`, `openapi/**` or `fixtures/**`. If a change is needed, write `ops/docs/CONTRACT_CHANGE_REQUEST.md` and keep working with the current contract.

## 2. Your ownership

- **You may create or edit:** `ops/**` (`ops/api/**`, `ops/dashboard/**`, `ops/docs/**`), and the content of `contracts/config/sms_templates.yaml`.
- **You must not edit:** `voice-runtime/**`, `brain/**`, `contracts/python/**`, `contracts/openapi/**`, `contracts/fixtures/**`, `departments.yaml`, `urgency_rules.yaml`, `prompts/**`.

## 3. Tech stack

- **API:**
  - Python 3.11, FastAPI, uvicorn, SQLAlchemy 2 (sync or async), SQLite (`ops/data/resolvix.db`)
  - `sse-starlette` (or a manual `StreamingResponse`), `passlib[bcrypt]` or `itsdangerous` for sessions
  - `twilio` (live SMS), PyYAML, pytest, httpx (TestClient).
  - Install the contracts with `pip install -e ../../contracts/python`.
  - Use `create_all` (Alembic is optional).
- **Dashboard:** React 18 + Vite + TypeScript + Tailwind CSS + TanStack Query + React Router; `EventSource` for SSE; Vitest for light tests. Generate the TS types from `contracts/jsonschema/*.json` (`json-schema-to-typescript`) into `src/api/types.ts`, and do not hand-edit them.
- Colour palette: brown/sand/slate (`#5E4330` header, `#7A5A40`, `#CBA982` accents, `#A97B49`, `#6F8592`, `#525A63`, background `#F4EFEA`). Priority colours: P1 `#B5603F`, P2 `#A97B49`, P3 `#6F8592`, P4 `#9CA9B1`.

## 4. What to build: API (`ops/api/resolvix_ops/`)

### 4.1 Database tables

- `calls`
- `turns` (unique on `call_id`, `turn_index`; stores the TurnSummary JSON)
- `tickets` (unique on `idempotency_key`; plus a `ticket_seq` table or counter)
- `ticket_events`
- `sms_messages` (unique on `idempotency_key`)
- `gaps`, `gap_clusters`
- `kb_entries` (id PK, status, JSON body, updated_at, updated_by, `flagged` bool)
- `kb_publishes` (kb_version, info JSON, actor, at)
- `users`
- `audit_log` (actor, action, entity, entity_id, details JSON, at).

### 4.2 Endpoints (every path in `ops-api.yaml`)

- **Calls:**
  - `POST /v1/calls`: idempotent on `call_id`; emits SSE `call.started`.
  - `POST /v1/calls/{id}/turns`: idempotent on (`call_id`, `turn_index`); emits `call.turn`.
  - `POST /v1/calls/{id}/end`: emits `call.ended`.
  - `GET /v1/calls`, `GET /v1/calls/{id}`. Viewing a call detail writes an `audit_log` row `transcript_viewed`.
- **Tickets:**
  - `POST /v1/tickets`: idempotent on `idempotency_key` (201 `{ticket_id, created:true}`, or 200 `{…, created:false}`).
  - **Ticket ID** = the department's `ticket_prefix` from `departments.yaml` + `-` + a **global** sequence starting at 1001 (`EX-1001`, `HS-1002`, …). Unknown department → 422.
  - Emits `ticket.created`, plus `alert.p1` when priority is P1.
  - `GET /v1/tickets` filters by status/department/priority/caller_number; sort P1→P4, then newest first.
  - `GET /v1/tickets/{id}`.
  - `PATCH /v1/tickets/{id}`: status, assignee, note (appended to `notes`), resolution. It writes audit + `ticket_events` (`status_changed`, `note_added`) and emits `ticket.updated`. **When the status changes**, queue exactly one `status_change` SMS (consent `transactional`) to `callback_number`, but only if the ticket has both a `call_id` (it came from a call) and a `callback_number`. The dedupe key is `"{ticket_id}:status:{new_status}"`.
  - `POST /v1/tickets/{id}/events`, `GET …/events`.
- **SMS:** `POST /v1/notifications/sms` → `SmsResult` (§5).
- **Gaps:**
  - `POST /v1/gaps` → store, assign a cluster (§4.3), emit `gap.created`.
  - `GET /v1/gaps/clusters`, `PATCH /v1/gaps/clusters/{id}`.
- **KB:**
  - `GET /v1/kb/entries?status=`; `POST /v1/kb/entries` (create or update; edits become `draft`; validate with `KBEntry`).
  - `POST /v1/kb/import` (multipart JSONL; per-line errors returned; **injection scan**: flag any entry matching `ignore (all|previous) instructions|system prompt|you are now|disregard|act as`, set it to `draft` + `flagged=true`).
  - `POST /v1/kb/entries/{id}/status` (approve/archive; audited).
  - `GET /v1/kb/export` → `KBExport` with **approved and currently valid** entries only (`Asia/Kolkata` date).
  - `POST /v1/kb/publish`:
    - `RUNTIME_MODE=live`: POST `{RUNTIME_URL}/admin/kb/reload` with `KBSource{kind:"url", location:"{OPS_PUBLIC_URL}/v1/kb/export"}` and header `X-Service-Key`, then return A's `KBVersionInfo`. A 422 from A → return 422 with the problems; A unreachable → 502 `upstream_error`.
    - `RUNTIME_MODE=mock`: return `contracts/fixtures/ops/kb_version_info.json` with a fresh timestamp.
    - Store the result in `kb_publishes`; audit it.
- **Config:** `GET /v1/departments` (load and validate `departments.yaml` with `DepartmentsConfig`); `GET /v1/urgency-rules` (YAML → JSON).
- **Stream:** `GET /v1/stream`, an SSE hub broadcasting named events with JSON data. Send a heartbeat comment every 15 s.
- **Auth:**
  - Service calls (A) send `X-Service-Key: ${SERVICE_KEY}`.
  - Dashboard: `POST /v1/auth/login` sets an httpOnly `resolvix_session` cookie (signed).
  - Users are seeded from `ops/api/seed_users.yaml`: `admin@demo` (admin), `exam@demo`, `accounts@demo`, `hostel@demo` (staff, with department). Passwords come from env `SEED_PASSWORD`.
  - Every `/v1/*` endpoint accepts either the service key or a valid session.
  - Roles: admin = everything; staff = tickets/calls/gaps (department scoping is P1); KB publish = admin only.
- **Errors:** every error returns an `ErrorEnvelope` (map Pydantic validation errors to `validation_error`, plus `not_found`, `conflict`, `unauthorized`, `upstream_error`).
- `GET /healthz` → `{status, contract_version, notify_mode, runtime_mode}`.

### 4.3 Gap clustering (P0 simple, P1 better)

- **P0:** cluster key = (`department_guess` or "unknown") + the top 2 non-stopword keywords (Hindi and English stopword lists) of the normalised question. Label = the keywords, title-cased. Track count, examples (last 5) and last_seen.
- **P1** (fallback task): embedding-based clustering, behind the same interface.

## 5. SMS service (`resolvix_ops/sms/`)

**Policy** (`policy.py`). Checks in order; the first failure gives `status="suppressed"` with a reason:

1. `template_id` exists in `sms_templates.yaml`.
2. Consent is allowed for the template:

   | Template | Allowed consent |
   |---|---|
   | `ticket_created`, `status_change` | `transactional` |
   | `answer_copy` | `caller_requested` or `offer_accepted` |
   | `staff_alert` | `staff` |

3. The duplicate `idempotency_key` returns the original result (HTTP 200).
4. The `to_number` is E.164. For `staff_alert`, it must be one of `departments.yaml` `sms_alert_numbers` (any department, or emergency).
5. Vars render the template completely (no missing placeholders).
6. **No personal data:** reject vars containing marks, dues or amounts tied to a person, or a roll number together with a name (simple regex rules; document them).
7. Any URL in the rendered text must start with an `allowed_url_prefixes` entry.

**Modes:**
- `NOTIFY_MODE=mock` (default): store with `status="sent"`, `mode="mock"`, and show it on the dashboard as **"SMS (mock)"**.
- `NOTIFY_MODE=twilio`: send via the Twilio Messaging API (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`). Store `provider_id`. Track status via a status callback (`POST /v1/notifications/sms/status`, Twilio-signature verified) if `OPS_PUBLIC_URL` is reachable, else poll once after 10 s. One retry on failure, then `failed` + a dashboard flag.
- Indian SMS needs **DLT-registered sender and templates**. Document this in the README and never present test-sender messages as production.
- Every SMS writes a `ticket_events` row (`sms_sent`/`sms_failed`/`sms_suppressed`) when `ticket_id` is present.

## 6. Dashboard (`ops/dashboard/`)

| Route | Contents |
|---|---|
| `/login` | Email + password |
| `/` **Live board** | Left: active calls (masked number `+91•••••0002`, language, last turn path/tier, duration). Right: ticket columns P1 / P2 / P3 (newest first) with priority colour, department, age and SLA-ish timer. On `alert.p1`: a red banner + sound (with a mute toggle) + the new ticket flashes. Counts row: calls today, answered by AI, escalated, P1 open. |
| `/tickets` | Table: filters (status, department, priority), search; click → **drawer**: summary, **brief**, **priority_reason + rule_id**, collected fields, caller (masked; reveal = audited), transcript (loads the call detail; audited), events timeline (transfer attempts, SMS with mock/live badge), notes, status/assignee controls, "Create KB draft from resolution" (P1). |
| `/calls` | List + detail: turns with path, tier, kb_ids, validator_flags, latency_ms, cached_tokens. |
| `/gaps` | Clusters sorted by count: label, department, count, examples, status buttons (needs_document / answered / ignored), and "Draft KB entry" → opens the KB editor prefilled. |
| `/kb` | Entries table (status chips, department, valid_until with an expiry warning under 14 days, flagged badge), JSONL import, edit form (KBEntry fields), approve/archive, **Publish** button (admin) → shows the `KBVersionInfo` (version, entries, tokens, warnings) or the error list. Version history from `kb_publishes`. |
| `/rules` | Read-only: the urgency rules table and the departments (hours, numbers masked, topics). |

UX requirements:
- Every page has loading, empty and error states.
- SSE reconnects automatically.
- Desktop-first, but usable at 1280 px and on a projector.
- Data-dense and clean, not flashy.

## 7. Simulator and seed (essential for parallel development)

- `ops/api/dev/seed.py`:
  - load `contracts/kb/sample_kb.jsonl` as approved entries
  - add one **draft** "bus route" entry for the demo's self-healing moment
  - seed users.
- `ops/api/dev/simulate_calls.py [--speed 1.0]`: reads each `contracts/fixtures/brain_streams/*.jsonl` and, as A would:
  1. POST `/v1/calls`.
  2. For each action, call the right endpoint (tickets with the fixture's TicketCreate, events for transfers with `mode=simulated`, SMS, gaps), substituting `{{ticket_id}}` with the returned ID.
  3. POST the turn summary.
  4. End the call.

  This keeps the dashboard alive and shows realistic flows without A or B.

## 8. Environment (`ops/api/.env.example`, `ops/dashboard/.env.example`)

```
PORT=8100
DATABASE_URL=sqlite:///./data/resolvix.db
SERVICE_KEY=change-me                 # shared with voice-runtime
SESSION_SECRET=change-me
SEED_PASSWORD=demo1234
OPS_PUBLIC_URL=http://localhost:8100
RUNTIME_MODE=mock                     # mock|live
RUNTIME_URL=http://localhost:8000
NOTIFY_MODE=mock                      # mock|twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM=
DEPARTMENTS_FILE=../../contracts/config/departments.yaml
URGENCY_RULES_FILE=../../contracts/config/urgency_rules.yaml
SMS_TEMPLATES_FILE=../../contracts/config/sms_templates.yaml
TIMEZONE=Asia/Kolkata
# dashboard
VITE_OPS_API_URL=http://localhost:8100
VITE_RUNTIME_URL=http://localhost:8000     # links to the web-call and typed-test pages (served by A)
```

## 9. Tests

- **Contract tests:**
  - every fixture in `contracts/fixtures/ops/` posts or validates against the right endpoint
  - responses validate against the contract models
  - every OpenAPI path has at least one test.
- **Idempotency:** duplicate ticket → same ID, `created:false`; duplicate turn → 200; duplicate SMS → original result.
- **Ticket IDs:** prefix per department; a global sequence; unknown department → 422.
- **SMS policy:** one test per suppression reason; mock mode labelled; status change → exactly one SMS.
- **SSE:** creating a P1 ticket emits `ticket.created` and `alert.p1` within 1 s.
- **KB:** the import flags injections; export excludes draft, archived and expired entries; publish in mock and live modes (respx-mock A); admin-only publish.
- **Auth:** missing credentials → 401; staff can't publish.
- **Dashboard:** Vitest for the API client and a priority-sort helper; a manual checklist in the README for J5/J6.
- `pytest ../../contracts/tests` stays green.

## 10. Deliverables and definition of done

- [ ] `uvicorn resolvix_ops.app:app --port 8100` and `npm run dev` work from the README on a clean machine.
- [ ] `python dev/seed.py && python dev/simulate_calls.py` makes the live board show calls, a P1 alert, tickets, mock SMS and gaps.
- [ ] J5 (staff works a P1 ticket, status SMS recorded) and J6 (gap → draft entry → approve → Publish in mock mode) work end to end.
- [ ] All tests green; README (setup, run, seed users, environment, mock modes, DLT note, assumptions, known limitations); `docs/DECISIONS.md`.

## 11. Hard rules

- Do not implement answer logic, urgency rules, Agora or the voice runtime. Those belong to A or B. Display rules; never evaluate them.
- Don't modify the frozen contracts; the simulator stands in for A.
- Never show full phone numbers in lists (mask them); reveal is audited. Never log secrets.
- Never label mock or test-sender SMS as delivered production SMS.
- Document every assumption and limitation in the README.
