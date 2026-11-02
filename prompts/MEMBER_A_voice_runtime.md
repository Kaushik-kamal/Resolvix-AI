# Coding-agent prompt: Member A, Voice Runtime and Integration

> Copy everything below this line into Claude Code, Antigravity or another coding agent, opened at the repo root.

---

You are the implementing engineer for **Member A: Voice Runtime and Integration** of **Resolvix**. Resolvix is a real-time, multilingual (Hindi, English and Hinglish) AI voice agent that answers a college helpline. It answers only from approved college knowledge. When it doesn't know, or the matter is urgent, it escalates by creating a ticket first, then transferring the call, sending SMS or promising a callback.

Three people build Resolvix in parallel. You build **only** your component and test it against mocks and fixtures. **Never** implement another member's responsibilities. **Never** edit files outside your ownership.

You have full authority for routine engineering decisions. Ask the human only if a spike fails **and** its documented fallback also fails, or if two requirements contradict each other. Record every non-obvious decision in `voice-runtime/docs/DECISIONS.md`.

## 1. Read first

1. `RESOLVIX_FINAL_PRD.md`: sections 3.5 (FR-A1 to FR-A3), 3.6, 3.7, 3.8, 3.10, 3.12, 7 (Member A), 8, 12, and the Appendix spikes.
2. `contracts/python/resolvix_contracts/`:
   - `models.py`: every payload
   - `brain_protocol.py`: the `Brain` protocol you call
   - `speech.py`: `speak_ticket_id`, idempotency helpers.
3. `contracts/openapi/voice-runtime.yaml` (what you serve) and `contracts/openapi/ops-api.yaml` (what you call).
4. `contracts/fixtures/brain_streams/*.jsonl`: 9 scenarios. The first line holds the `_request`; the following lines are events.
5. `contracts/fixtures/agora/chat_request.json` and `expected_sse_for_04.txt`.
6. `contracts/config/departments.yaml`.

The contracts are **FROZEN** (v1.0.0). Do not change them. If you believe a change is needed, stop and write the proposal in `voice-runtime/docs/CONTRACT_CHANGE_REQUEST.md` for the team; meanwhile, keep working with the current contract.

## 2. Your ownership

- **You may create or edit:** `voice-runtime/**`, `integration/**`, and the repo root files `README.md`, `Makefile`, `docker-compose.yml`, `.env.example`.
- **You must not edit:** `brain/**`, `ops/**`, `contracts/**` (read-only), `prompts/**`.

## 3. Tech stack

- Python 3.11, `uv` (or venv + pip)
- FastAPI, uvicorn, httpx, pydantic v2 (via `resolvix-contracts`), PyYAML, structlog (or stdlib JSON logging)
- pytest, pytest-asyncio, respx
- Agora Conversational AI Engine REST API and Agora RTC Web SDK (from a CDN in a static HTML page)
- Install the contracts with `pip install -e ../contracts/python`.

## 4. What to build

### 4.1 Shim: `POST /v1/chat/completions` (FR-A1)

- **Auth:** `Authorization: Bearer ${SHIM_API_KEY}` → 401 on mismatch.
- **Accept** the OpenAI chat request Agora sends. Ignore unknown fields (`context`, `tools`, `modalities`, `stream_options`…). `stream` must be true, else 400.
- **Resolve `call_id`:** use the query param `?call_id=`. If it's missing, look for a system message `RESOLVIX_CALL_ID=<id>`. If neither exists, use a new uuid and log a warning.
- **New `call_id`:**
  1. `ops.post_call_start(CallStart)` (non-blocking, with retry).
  2. `brain.start_call(CallContext)`.
  3. Optionally fetch open tickets for the caller (P1): `GET /v1/tickets?caller_number=&status=open`.
- **Build the `TurnRequest`:** `user_text` is the last `user` message, `history` is the earlier messages, `turn_index` is a per-call counter.
- **Drive `brain.handle_turn(req)` and translate the events:**
  - `MetaEvent` → the **first** SSE chunk `{"object":"chat.completion.custom_metadata","choices":[],"metadata":{"interruptable":<bool>}}`
  - `SpeechEvent` → a `chat.completion.chunk` with `delta.content` (substitute `{{ticket_id}}` first, see 4.2)
  - `ActionEvent` → the executor (4.2); if `blocking`, await it before continuing
  - `DoneEvent` → `ops.post_turn(summary)` in the background.
- **End** with a finish chunk (`finish_reason:"stop"`), then `data: [DONE]`.
- **Output format** must match `contracts/fixtures/agora/expected_sse_for_04.txt` (the `id`/`created`/`model` values may differ).
- **Barge-in:** keep a registry `{call_id: asyncio.Task}`. When a new request arrives for a `call_id` with an active stream, cancel the old task. The brain releases its resources.
- **Never** return non-200 once streaming has started. If anything throws, stream `runtime_lines.yaml → fallback` (hi/en) and create a `SYSTEM_FAILURE` ticket via ops.

### 4.2 Action executor (FR-A2), `executor.py`

Process actions in order. Keep per-turn state `{ticket_id: str|None}`.

- **`create_ticket` (always blocking):**
  1. `POST {OPS_API_URL}/v1/tickets` with header `X-Service-Key`, 2 s timeout, 2 retries.
  2. On success, store `ticket_id`.
  3. If ops-api is unreachable: assign `TMP-<4 random digits>`, put the request in an in-memory retry queue (flush every 5 s), and speak "your request has been registered" without the ID. Use `runtime_lines.yaml → registered_no_id`.
- **Placeholder substitution:** in later `SpeechEvent` text, replace `{{ticket_id}}` with `speak_ticket_id(ticket_id, lang)`. In `send_sms.vars`, replace it with the raw `ticket_id`.
- **`transfer`:**
  1. If `requires_ticket` and no ticket exists this turn, log an error, do NOT dial, and treat it as transfer_failed.
  2. `POST /v1/tickets/{id}/events {kind:"transfer_attempted"}`.
  3. Call `telephony.transfer(call_id, to_number)`.
  4. On success, post `transfer_connected`.
  5. On failure or no answer, post `transfer_failed` and inject an extra SSE speech chunk from `runtime_lines.yaml → transfer_failed` (mention the ticket ID). The ticket stays open.
  6. For `channel in (web, test)`: simulate. Post `transfer_attempted` with `payload.mode="simulated"`, then `transfer_failed` with reason `simulated`, and speak `transfer_simulated` only in the test channel.
- **`send_sms`:** `POST /v1/notifications/sms` (non-blocking; log the `SmsResult`).
- **`log_gap`:** `POST /v1/gaps` (non-blocking).
- **`schedule_callback`** (P1): `POST /v1/tickets/{id}/events {kind:"callback_scheduled"}`.
- **`end_call`:** after the current speech finishes, stop the Agora agent (live) or mark the call ended (test).
- **On call end** (agent stopped, idle 90 s, or the test page's "end"): `POST /v1/calls/{id}/end` with an outcome derived from the turns:
  - any transfer connected → `transferred`
  - any ticket created → `escalated`
  - emergency → `emergency`
  - otherwise → `answered`
  - and `brain.end_call()`.

### 4.3 Agora control, `agora_control.py` + `telephony/`

- `POST /api/sessions/web` → create a channel and RTC tokens (Agora token builder), then start a Conversational AI agent with the REST "join" call:
  - LLM vendor = custom, `url = {PUBLIC_BASE_URL}/v1/chat/completions?call_id={call_id}`, `api_key = SHIM_API_KEY`
  - ASR/TTS config from env (`ASR_VENDOR`, `TTS_VENDOR`, voice id)
  - greeting = `CallStartPlan.greeting_text` from `brain.start_call`.
  - Return `{app_id, channel, rtc_token, uid, call_id}`.
- `static/call.html`: a minimal page that joins with the Agora Web SDK, publishes the mic and plays the agent audio. It has Start and End buttons and a live transcript if available.
- `TelephonyAdapter` protocol with `transfer(call_id, to_number) -> bool` and `outbound_call(to_number, call_id) -> str`. Implementations are `AgoraTelephony` (per Spike S1 results) and `MockTelephony` (env `TELEPHONY_MODE=mock`, a configurable success/fail).
- **Spike S1 (first 2 hours):**
  - Determine whether a phone call can reach the shim with an identifiable `call_id`. Check Agora inbound via SIP trunk (Twilio Elastic SIP Trunk is the documented path) plus number import and agent association; and the Agora outbound-call API (`POST /api/conversational-ai-agent/v2/projects/{appid}/call`) to a verified phone.
  - Determine whether a live transfer to an arbitrary department number can be triggered.
  - Write the findings in `voice-runtime/docs/SPIKES.md`.
  - **The web call path is mandatory regardless of the outcome.**
- **Spike S3:** test the Agora-supported ASR/TTS options on Hindi/English/Hinglish samples with dates and amounts. Choose one, document it, and make it configurable by env.
- **Spike S4:** check whether the engine has idle/silence settings or events. If yes, implement P1 silence prompts (about 5 s, then about 10–12 s, then a goodbye line). If not, document and skip.

### 4.4 Brain loading, `brain_loader.py`

- `BRAIN_IMPL=mock` (default until integration): `MockBrain` implements the `Brain` protocol by replaying `contracts/fixtures/brain_streams/*.jsonl`. It picks the scenario by keyword match on `user_text`:

  | Keyword | Scenario |
  |---|---|
  | fee/fees | 01 |
  | hostel gate | 02 |
  | bus/route | 03 |
  | exam + minute | 04 |
  | behosh/ambulance | 05 |
  | complaint/wifi | 06 |
  | insaan/human | 07 |
  | "fail" | 08 |
  | re-evaluation | 09 |
  | anything else | 01 |

  It rewrites `call_id` and `turn_index` in the events to the live values.
- `BRAIN_IMPL=real`: `from resolvix_brain import create_brain` (B's package, installed later with `pip install -e ../brain`). **Do not import `resolvix_brain` anywhere else.**

### 4.5 Typed test page (FR-A3)

- `POST /api/test/turn {call_id?, text}` runs the same shim pipeline with channel=`test`. It returns `{call_id, events:[...], spoken_text}` with the placeholders already substituted.
- `GET /test` serves `static/test.html`: an input box, a scenario quick-buttons row (the 9 fixture utterances), an event log and a spoken-text panel. This is the demo backup, so make it robust and clean.

### 4.6 KB reload passthrough

`POST /admin/kb/reload` (header `X-Service-Key`) with a `KBSource` body → `await brain.reload_kb(source)` → `KBVersionInfo`. On a compile error, return 422 with an `ErrorEnvelope` that lists the problems.

### 4.7 Health

`GET /healthz` → `{status, brain: brain.health(), ops_api: ok|down, agora: ok|down|mock, contract_version}`.

### 4.8 Ops client, `ops_client.py`

- Typed async client for every ops-api endpoint you use. It sends `X-Service-Key`, parses `ErrorEnvelope` and retries idempotent calls.
- The retry queue keeps failed non-blocking writes (turns, gaps, sms, events) and flushes them later.
- Provide `dev/ops_stub.py`: a tiny FastAPI app on :8100 that implements the endpoints you call with in-memory storage. It generates ticket IDs like `EX-1001`, which lets you run manually without C.

### 4.9 Runtime lines, `runtime_lines.yaml`

Write hi and en versions for: `fallback`, `registered_no_id`, `transfer_failed` (uses `{ticket_id_spoken}`), `transfer_simulated`, `goodbye`, and `silence_1`/`silence_2` (P1).

## 5. Environment (`voice-runtime/.env.example`)

```
PORT=8000
PUBLIC_BASE_URL=https://<tunnel>.trycloudflare.com
SHIM_API_KEY=change-me
SERVICE_KEY=change-me            # shared with ops-api
OPS_API_URL=http://localhost:8100
BRAIN_IMPL=mock                  # mock|real
TELEPHONY_MODE=mock              # mock|agora
AGORA_APP_ID=
AGORA_APP_CERTIFICATE=
AGORA_CUSTOMER_ID=
AGORA_CUSTOMER_SECRET=
ASR_VENDOR=deepgram
ASR_API_KEY=
TTS_VENDOR=
TTS_API_KEY=
TTS_VOICE_ID=
# Brain settings are B's; when BRAIN_IMPL=real, also load brain/.env (GROQ_API_KEY etc.)
```

## 6. Tests (all must pass without network or keys)

1. **SSE writer:** the event list from fixture 04 with a mock ops-api returning `EX-1042` produces output equivalent to `expected_sse_for_04.txt` (compare the parsed JSON, ignoring `id`/`created`).
2. **Executor ordering:** for each of the 9 fixtures, the respx-mocked ops-api receives the expected calls in order. A transfer never happens before a ticket. Placeholders are substituted. The SMS vars carry the raw ID.
3. **Idempotency:** replaying the same turn twice → `POST /v1/tickets` receives the same `idempotency_key`.
4. **ops-api down:** speech still streams; `registered_no_id` is used; the queue holds the request.
5. **Barge-in:** a second request cancels the first stream task.
6. **`call_id` resolution:** query param, then system message, then generated.
7. **Auth:** 401 without the bearer token; 400 when `stream=false`.
8. `pytest ../contracts/tests` stays green.

## 7. Integration (you own it; do it at H26, not before)

- Root `Makefile` targets:
  - `contracts-test`
  - `run-ops` (runs C's command from their README)
  - `run-runtime`
  - `run-dashboard`
  - `e2e`
  - `demo-check`
- `docker-compose.yml` (optional; the local-process Makefile is enough).
- The root `.env.example` is the union of the three components' environment variables.
- `integration/e2e_test.py`: for each of the 9 scenarios, call `/api/test/turn` with the scenario utterances (multi-turn where needed, e.g. complaint and unknown). Assert against the real ops-api: ticket exists with the expected type, priority, rule_id and department; gap logged; SMS recorded (mock); turns stored; call ended.
- Follow `RESOLVIX_FINAL_PRD.md` §12 step by step and record the results in `integration/INTEGRATION_LOG.md`.

## 8. Deliverables and definition of done

- [ ] `voice-runtime/` runs with `uvicorn resolvix_runtime.app:app --port 8000` using `BRAIN_IMPL=mock` + `dev/ops_stub.py`.
- [ ] Web call works end to end through Agora with MockBrain (two-way audio, barge-in).
- [ ] The typed test page runs all 9 scenarios.
- [ ] Every test above passes; README covers setup, run, test, environment, mock modes, limitations and assumptions.
- [ ] `docs/SPIKES.md` (S1, S3, S4 results), `docs/DECISIONS.md`.
- [ ] Integration Makefile and `integration/e2e_test.py` ready (they run once B and C deliver).

## 9. Hard rules

- Do not implement answer logic, KB handling, urgency rules, SMS policy, a database or dashboard UI. Those belong to B or C.
- Do not modify `contracts/`. Use the mocks for anything that isn't ready.
- Never log secrets or full phone numbers (mask all but the last 4 digits).
- Never present a simulated transfer or SMS as real in logs or UI. Mark them `mode=simulated` or `mock`.
- Document every assumption and limitation in the README.
