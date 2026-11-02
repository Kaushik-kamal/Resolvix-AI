# Integration guide and examples (Brain <-> Member A, Brain <-> Member C)

Everything here is based on the frozen contracts v1.0.0. **What is tested and what is not:**

| Item | Status |
|---|---|
| Brain behaviour, event streams, ticket-first, placeholders, deferral, KB reload from a file and from a real local HTTP server | Tested (`tests/`, 339 tests) |
| `examples/runtime_sim.py` (a reference runtime + in-memory ops service written by Member B as an *illustration*) | Tested by 19 mocked-integration tests. It is **not** Member A's or C's code |
| The FastAPI glue snippets in A10 | **Untested**: FastAPI is not installed in the Brain environment and Member A's runtime does not exist here |
| Anything involving Agora, a real phone, the real ops-api or the dashboard | **Not run.** Nothing in this repository exercises them |

All sample payloads are in `docs/samples/` and were produced by the real Brain (regenerate with
`python examples/dump_payloads.py`).

---

# Part A: for Member A (voice-runtime)

You own `voice-runtime/**`, `integration/**` and the root files. **Nothing below requires editing `brain/`.** Copy what you
need from this guide; `brain/examples/runtime_sim.py` is a runnable reference for the patterns marked `PATTERN`.

## A1. Install

```powershell
# in YOUR runtime venv, from the repo root
pip install -e contracts/python
pip install -e brain            # pulls fastembed, onnxruntime, numpy, tiktoken, httpx, pyyaml (no FastAPI, no DB)
pip check                       # must say: No broken requirements found.
$env:PYTHONUTF8 = "1"
pytest contracts/tests -q       # 6 passed
```

The Brain's dependency ranges are in `brain/pyproject.toml`; if they clash with your FastAPI/uvicorn pins, tell Member B (the PRD
says the Brain's range wins unless it breaks you).

## A2. Initialisation

```python
from resolvix_brain import create_brain, BrainSettings
from resolvix_contracts import Brain

brain = create_brain(BrainSettings.from_env())   # cheap: loads YAML only; no model, no KB yet
assert isinstance(brain, Brain)
await brain.ready()                              # loads the embedding model + the default KB (KB_SOURCE); in live mode also sends one warm-up call so the provider caches the KB prefix
```

Configuration is read from environment variables and `brain/.env` (see `brain/.env.example`). Relevant ones:

| Variable | Meaning | Needed for |
|---|---|---|
| `LLM_MODE` | `live` or `mock` | mock = no key, no network |
| `GROQ_API_KEY` | Groq key (never commit) | live |
| `KB_SOURCE` | `file:<path>` or `url:http://localhost:8100/v1/kb/export` | the KB loaded by `ready()` |
| `DEPARTMENTS_FILE`, `URGENCY_RULES_FILE` | default to `../contracts/config/*.yaml` relative to `brain/` | routing, rules |
| `EMBED_MODE` | `fastembed` (production) or `lexical` (offline, degraded) | retrieval |
| `EMBED_CACHE_DIR` | where the ~470 MB e5 model is cached | first start only |

`ready()` is idempotent and `start_call` calls it, but **call it at startup**: the first load costs about 2 s with the model cached
and about 45 s the very first time it is downloaded. If the default KB fails to compile, `ready()` does not raise: `health()` reports
`status="degraded"` and `init_error`, and every non-safety turn then returns the safe fallback (ticket + "we will call you back").

`BRAIN_IMPL=real` loader (sketch for `brain_loader.py`):

```python
def load_brain(impl: str):
    if impl == "mock":
        return MockBrain()
    from resolvix_brain import create_brain, BrainSettings
    return create_brain(BrainSettings.from_env())
```

## A3. Startup and shutdown

```python
@asynccontextmanager
async def lifespan(app):
    app.state.brain = load_brain(os.environ.get("BRAIN_IMPL", "mock"))
    if hasattr(app.state.brain, "ready"):
        await app.state.brain.ready()          # fail fast on a missing model/KB: check brain.health()
    yield
    if hasattr(app.state.brain, "aclose"):
        await app.state.brain.aclose()         # closes the Groq HTTP client
```

- **Run ONE worker process.** Dialogue state (pending complaint, ticket confirmation, language, caller number) lives in the Brain
  instance's memory. `uvicorn --workers N` or any load balancer without call-sticky routing will split one call across two
  Brains and the second one will have no state. See `MEMBER_B_HANDOFF.md` ("session persistence").
- A runtime restart loses live calls' dialogue state. The Brain tolerates a `TurnRequest` for an unknown `call_id` (it creates a
  session and seeds the last 8 turns from `req.history`) but it cannot recover the caller number or a half-finished flow.
- `/healthz` should include `brain.health()`: `{status: ok|degraded, kb_version, llm: ok|down, contract_version, embedder, sessions, llm_mode, init_error}`.
  `degraded` is expected with `EMBED_MODE=lexical` or when the LLM is failing; do not take the runtime down on it.

## A4. Session management

| Call lifecycle | You do | Brain does |
|---|---|---|
| New call (first request for a `call_id`) | `plan = await brain.start_call(CallContext(call_id, channel, caller_number, started_at, open_tickets))` | creates the session, **pins the active KB version**, returns `CallStartPlan(kb_version, greeting_text, greeting_lang, interruptable=False)` |
| Greeting | speak `plan.greeting_text` (bilingual, includes the "call may be recorded" consent line) as the Agora agent greeting | none |
| Each caller utterance | `brain.handle_turn(TurnRequest(...))` | pipeline, events |
| Call ends (hang-up, idle 90 s, End button) | `await brain.end_call(call_id)` (then `POST /v1/calls/{id}/end`) | drops the session. Sessions also expire after 2 h |

Rules:
- Use **one Brain instance** for all calls and **monotonic `turn_index` per call** (1, 2, 3, ...). The Brain builds the ticket
  idempotency key from it (`{call_id}:{turn_index}:{TYPE}`): reusing an index for a different utterance would make ops treat a
  second ticket as a duplicate.
- Do not call `start_call` again for a live call (it replaces the session and loses state). `Caller` in the tests had that bug once.
- `TurnRequest.history` is **only a seed** when the Brain has no session turns yet. The Brain keeps its own history, so you may
  pass Agora's history or `[]`.
- Live calls keep the KB version they started with, even after a reload.

## A5. Turn processing and event translation

```python
req = TurnRequest(call_id=call_id, turn_index=n, user_text=text, history=[...], dtmf=None, received_at=now_ist)
agen = brain.handle_turn(req)
try:
    async for ev in agen:
        ...
finally:
    await agen.aclose()          # ALWAYS (see A7)
```

Guaranteed by the Brain (tested): exactly one `MetaEvent` first, any mix of `SpeechEvent`/`ActionEvent`, exactly one `DoneEvent` last;
never raises (internal errors become the fallback stream); every `create_ticket` is `blocking=True` and precedes any `transfer`
and any speech containing `{{ticket_id}}`.

| BrainEvent | Translate to |
|---|---|
| `MetaEvent` | first SSE chunk `chat.completion.custom_metadata` with `{"metadata": {"interruptable": ev.interruptable}}`. `ev.lang` is `hi`/`en`/`hinglish` (use it to choose the TTS voice if you can; it is also what you pass to `speak_ticket_id`) |
| `SpeechEvent` | `chat.completion.chunk` with `delta.content` after substituting `{{ticket_id}}` |
| `ActionEvent` | your executor (A6). If `blocking`, finish it before reading the next event |
| `DoneEvent` | `POST /v1/calls/{id}/turns` with `ev.summary` (background, idempotent on `(call_id, turn_index)`) |

`received_at` must be timezone-aware and should be the real time of the utterance: the Brain uses it for **office hours**
(transfer now or promise a callback) and for the date in the LLM prompt.

Expected SSE (see `docs/samples/sse_to_agora_example.json`, produced by the reference runtime, and
`contracts/fixtures/agora/expected_sse_for_04.txt`):

```
data: {"object":"chat.completion.custom_metadata","choices":[],"metadata":{"interruptable":false}, ...}

data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":"Ye urgent hai. Maine Examination Cell ke liye ticket E X, ek shoonya shoonya ek bana diya hai ..."},"finish_reason":null}], ...}

data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}], ...}

data: [DONE]
```

## A6. Speech generation and the action executor

**Speech text is final TTS text** except for `{{ticket_id}}`:
- Replace `{{ticket_id}}` with `speak_ticket_id(ticket_id, lang)` where `lang = "en" if meta.lang == "en" else "hi"`.
- Amounts, dates and times are already spoken-form ("95 hazaar rupaye", "30 November", "raat 10 baje"); do not re-format them.
- Hindi/Hinglish lines are **romanised** (matches the fixtures). If the caller's text arrives in Devanagari, the fixed lines and the
  emergency script come back in Devanagari. KB answers are spoken in the script they were written in. **Your TTS voice must read both
  Latin-script Hindi and Devanagari** (Spike S3).
- A turn can contain several `SpeechEvent`s (answer, then "anything else?"). Stream them in order; the Brain's `assistant_text` keeps
  the placeholder, so do not expect the final string to match what you spoke.

Executor rules (the contract lines that matter; `examples/runtime_sim.py::ReferenceRuntime._execute` implements them):

| Action | Rule |
|---|---|
| `create_ticket` | `POST /v1/tickets` (2 s timeout, 2 retries). Store the returned `ticket_id` **for this turn**. If ops is unreachable: local `TMP-xxxx`, queue for retry, and speak the "registered" line instead of the sentence that contained `{{ticket_id}}` |
| `transfer` | If `requires_ticket` and the turn has no ticket: **do not dial**. Post `transfer_attempted`, dial `to_number`, post `transfer_connected` or `transfer_failed`; on failure speak the `transfer_failed` line mentioning the ticket id. The ticket stays open. Web/test channels: simulate |
| `send_sms` | replace `{{ticket_id}}` in `vars` with the **raw** id (`EM-1001`, not the spoken form) and `POST /v1/notifications/sms`. Non-blocking |
| `log_gap` | `POST /v1/gaps` with `ticket_id` of the turn if any. Non-blocking |
| `end_call` | stop the agent after the current speech |

Transfer targets: `to_number` is already resolved by the Brain from `departments.yaml` (`transfer_numbers[0]`); dial the rest of the
department's list in order yourself if the first does not answer. Emergency: the Brain emits the fixed script, ticket, staff-alert
SMS to **each** emergency alert number, then the transfer.

## A7. Barge-in and cancellation (read this twice)

1. One active stream per call. A new request for the same `call_id` while a stream is running cancels the old task.
2. **Always `await agen.aclose()` in a `finally`.** Closing the generator is how the Brain learns exactly which events you received.
   It then records only the speech you actually got as the assistant turn.
3. If you close the generator **before** it handed you the actions (for example the caller talks over the emergency script), the
   Brain keeps the undelivered `create_ticket`/`send_sms`/`log_gap` and **re-emits them at the start of the next turn** (never a
   `transfer`). Tested: `test_barge_in_before_actions_are_delivered_defers_them_to_the_next_turn`.
4. **Once the Brain has yielded an action, it is yours.** If your task is cancelled while `create_ticket` is in flight, the Brain
   will not send it again. Wrap action execution in `asyncio.shield(...)` (or run it in a separate task that barge-in does not cancel).
   Tested: `test_barge_in_while_an_action_is_in_flight_does_not_lose_it`. Without the shield that test loses a P1 ticket.
5. Do not cancel a turn whose `MetaEvent.interruptable` is `False` (emergency, urgent, ticket/transfer turns). Let it finish.
6. Session state is committed when the first content event is yielded, so a cancel before any content leaves the session as if
   the turn never happened.

## A8. Caller identification

- The Brain learns the caller number **only** from `CallContext.caller_number` in `start_call` (E.164, e.g. `+919812345678`; `None`
  for web/test calls). It is never taken from speech for identification: a number the caller *says* is used only as a callback
  number, and only after the caller confirms it.
- With a number: tickets carry `caller_number`; the Brain offers "call you back on the number ending in ..." (reads the last four
  digits), and SMS goes only to that number or to a number the caller dictated.
- Without a number (web/test): the Brain asks for a mobile number; if none is given the ticket is still created, without SMS.
- Pass `open_tickets` (from `GET /v1/tickets?caller_number=&status=open`) to give repeat-caller context to the LLM (P1 feature).
- Caller ID can be spoofed; the Brain treats it as a contact detail, not as proof of identity. It answers **public information only**
  and declines personal records (fee dues, marks, attendance).
- After a runtime restart the number is lost (CR-4 in `CONTRACT_CHANGE_REQUEST.md`).

## A9. Error handling

| Situation | What happens | What you do |
|---|---|---|
| LLM down/slow/garbled | Brain streams: Meta(path=fallback), `create_ticket(SYSTEM_FAILURE, P3, callback_requested)`, speech with `{{ticket_id}}` | execute normally; ticket-first still holds |
| Unexpected exception inside the Brain | same fallback stream (flag `internal_error`) | same |
| `handle_turn` raises anyway (a bug; should not happen) | n/a | wrap in `try/except`: stream your own `runtime_lines.fallback` and create a `SYSTEM_FAILURE` ticket yourself |
| `reload_kb` fails | raises `KBCompileError(problems: list[str])`; **old KB stays active** | return 422 `ErrorEnvelope(code="validation_error", details=...)` listing `problems` |
| ops-api down | n/a | local TMP id, retry queue, speak the registered line (A6). Never block speech |
| Caller silent / unclear | Brain re-prompts once, then offers a person | nothing |
| Safety phrase | Brain never calls the LLM; emergency plan | execute; do not interrupt |

## A10. Latency expectations

Measured on a developer laptop (CPU, real e5 model, mock LLM): Brain-only cost per turn ~6-8 ms (embedding ~6 ms, safety check 8 us),
50 concurrent calls finish in ~120 ms wall. **Not measured:** anything involving the real Groq API.

| Path | Brain calls the LLM? | Expectation (design, not measured end to end) |
|---|---|---|
| Safety, human request, urgent pre-check, greeting/thanks, FAQ hit | No | tens of milliseconds |
| Normal question (LLM) | Yes (one buffered call, then validation) | LLM time-to-first-token + generation + a few ms; PRD target <= ~900 ms to first speech with a warm cache. **Unverified** |
| LLM outage | tries primary, retries once on the small model only if the first failure took < 1.5 s | an immediate connection error: ~instant. A *stalled* primary: up to the 3 s first-token / 6 s total timeout before the fallback line. **Consider a short filler chunk if no event arrives within ~1.5 s** (your decision; the Brain does not send one) |

## A11. Reference FastAPI glue (UNTESTED sketch: FastAPI is not installed in the Brain environment)

```python
# voice-runtime/resolvix_runtime/shim.py  (yours; adapt freely)
@router.post("/v1/chat/completions")
async def chat(request: Request, call_id: str | None = None):
    body = await request.json()
    if not body.get("stream"):
        raise HTTPException(400, "stream must be true")
    call_id = call_id or _call_id_from_system_message(body["messages"]) or str(uuid4())
    brain, rt = request.app.state.brain, request.app.state.runtime
    if call_id not in rt.known_calls:
        await rt.start_call(call_id, caller_number=lookup_caller(call_id))      # brain.start_call + ops.post_call
    msgs = [m for m in body["messages"] if m["role"] != "system"]
    user_text = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    return StreamingResponse(rt.stream_turn(call_id, user_text, history=msgs[:-1]), media_type="text/event-stream")

@router.post("/admin/kb/reload")
async def reload_kb(source: KBSource, request: Request):
    try:
        info = await request.app.state.brain.reload_kb(source)
    except KBCompileError as exc:
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "KB compile failed",
                            "retryable": False, "details": {"problems": "; ".join(exc.problems)}}})
    return info          # KBVersionInfo
```

`ErrorBody.details` is `dict[str, str]`, so join the problems into one string (or number them) rather than sending a list.

## A12. Typed test page / `/api/test/turn`

Same pipeline with `channel="test"`: call `start_call` once per test call, then `turn(...)` repeatedly; simulate transfers (the reference
runtime does). With `BRAIN_IMPL=real` and `LLM_MODE=mock` the whole demo script works with no key, no audio and no network.

## A13. Example: run the reference runtime yourself

```powershell
cd brain
$env:PYTHONUTF8 = "1"
python -m pytest tests/test_integration_mocked.py -v        # 19 tests, uses examples/runtime_sim.py
python -m resolvix_brain chat --mock                         # interactive; prints each BrainEvent as JSON
python examples/dump_payloads.py                             # regenerates docs/samples/*.json
```

---

# Part B: for Member C (ops-api and dashboard)

You own `ops/**` and `contracts/config/sms_templates.yaml`. The Brain never talks to you directly: Member A's runtime posts what the
Brain decides, and the Brain reads your KB export through Member A's `/admin/kb/reload`.

## B1. Knowledge-base export format (`GET /v1/kb/export`)

A `KBExport` (`contracts/jsonschema/KBExport.json`; real sample: `contracts/kb/sample_kb_export.json`, with problems:
`docs/samples/kb_export_with_problems.json`).

```json
{
  "version_label": "2026-10-23-1",
  "exported_at": "2026-10-23T09:00:00+05:30",
  "entries": [
    {"id": "FEE-001", "department": "accounts",
     "question_variants": ["B.Tech 2nd year fee last date", "fees kab tak jama karni hai"],
     "answer_en": "The last date for B.Tech second-year semester fee is 30 November 2026.",
     "answer_hi": "B.Tech second year ki semester fee ki last date 30 November 2026 hai.",
     "source_title": "Fee Notice 2026-27", "source_ref": "p.1",
     "valid_from": null, "valid_until": "2026-11-30", "tags": ["fee", "deadline"], "is_faq": true, "status": "approved"}
  ]
}
```

Requirements on your side:
- `id` must match `^[A-Z]{2,4}-\d{3,4}$`; `department` must be a key in `departments.yaml` (an unknown key is accepted by the Brain but
  breaks routing); at least one `question_variant`; `source_title` is **spoken to callers** ("Ye Fee Notice 2026-27 mein diya hai"), so keep it short and real.
- Put `valid_until` on anything with a date or deadline. The Brain refuses to speak an entry after its last valid day.
- Add **Devanagari question variants** for important FAQs if Hindi ASR returns Devanagari (measured: Devanagari queries ranked the right
  entry first 6/6 times but cleared the FAQ-hit bar only 1/6; the rest are answered via the LLM, which needs the Groq key).
- Dates/figures in `answer_en`/`answer_hi` must be written the way staff want them spoken: the Brain only speaks figures that appear in the cited entry.
- The Brain re-filters everything, so exporting a draft or expired entry is safe (it is excluded and reported), but report-and-fix is better.

## B2. KB reload API (`POST /v1/kb/publish` -> A's `POST /admin/kb/reload` -> `brain.reload_kb`)

Request body A receives (`docs/samples/kb_source_url.json`): `{"kind": "url", "location": "http://localhost:8100/v1/kb/export"}`
(`kind: "file"` also works). The Brain does an unauthenticated `GET` with a 10 s timeout, so the export endpoint must be reachable
without a session cookie from the runtime, or you must pass a pre-authenticated URL. **This has not been tested against your service.**

Success: `KBVersionInfo` (real output, `docs/samples/kb_version_info_after_reload.json`):

```json
{"kb_version": "6f4da57b0bf8", "entry_count": 10, "faq_count": 5, "token_count": 2707,
 "activated_at": "2026-11-01T14:24:42+05:30",
 "warnings": ["excluded 1 entry (expired (valid_until 2026-01-01)): FEE-002",
              "excluded 1 entry (status=draft): FEE-003",
              "excluded 1 entry (prompt-injection pattern ignore-instructions): FEE-099"]}
```

Show `warnings` on the Publish screen: they name every entry that was **not** published and why (draft, expired, not yet valid, injection
pattern, duplicate question, token budget). Failure: A returns 422 with the problem list (`docs/samples/kb_compile_error_problems.json`);
the previous KB stays active and live calls are unaffected. Return 502 `upstream_error` if A is unreachable (your contract).

## B3. KB versioning

`kb_version` = first 12 hex of SHA-256 of the compiled prompt prefix: the same entries on the same date always give the same version;
any change to an answer, a question, source, validity or the department directory changes it. The Brain keeps the last 3 versions (plus
any pinned by live calls); a call keeps the version it started with. `TurnSummary` does not carry the version; `CallStart.kb_version`
(which A sends) does, so the dashboard can show which KB a call used.

**Expiry:** `valid_until` is honoured on the day it is evaluated: at compile time, again at answer time, and the Brain recompiles by itself
on the first turn of a new day (IST). You do not need a midnight publish for expiry to be safe, but publish as soon as content changes.

## B4. Draft and expired filtering (what the Brain does with `status` and dates)

| Entry state | Result |
|---|---|
| `status != approved` | excluded, warning `excluded N entries (status=draft)` |
| `valid_from` in the future | excluded (`not yet valid`) |
| `valid_until` before today (IST) | excluded (`expired`) and never spoken even if the KB is stale |
| text matches an instruction-like pattern (`ignore previous instructions`, `system prompt`, `you are now`, ...) | excluded (`prompt-injection pattern ...`) |
| same question variant in two entries | kept on the first; warning `duplicate question` |
| same id twice, different content | whole compile fails (`duplicate id`) |
| total prompt tokens > `KB_TOKEN_BUDGET` (90,000) | whole compile fails with a per-department token report; nothing is truncated |

## B5. Department routing (so your dashboard filters make sense)

| Situation | Department |
|---|---|
| exam <= 60 min and blocked (R-EXAM-60) | `exam_cell` |
| fee deadline <= 24 h and blocked (R-DEADLINE-24H) | `accounts`; admit card -> `exam_cell`; form deadline -> topic match |
| complaint | topic match against `departments.yaml` `topics` (wifi/mess/room -> `hostel`), else `helpdesk` |
| human request | topic match, else `helpdesk` |
| unanswered question | topic match (bus/route -> `transport`), else the departments of the cited entries, else `helpdesk` |
| emergency | `emergency` |
| system failure | `helpdesk` (the default department) |

Non-MVP departments (`transport`, `admissions`) receive tickets even though they have no KB. Transfer happens only if the department is
**open** (hours in `departments.yaml`, IST, evaluated at the turn's `received_at`); otherwise `callback_requested=true` and an SMS.
Exceptions: P1 exam and emergency transfer regardless of hours.

## B6. Escalation events that reach you (via Member A)

Every escalation produces, in this order: `create_ticket` (blocking) -> optional `send_sms` / `log_gap` -> `transfer`.
Real samples: `docs/samples/events_*.json` (what A receives) and `docs/samples/ops_received_after_emergency_and_human.json` (what you receive).

| Scenario | Ticket type / priority | Also | Rule id in `priority_reason` / TurnSummary |
|---|---|---|---|
| Emergency phrase | `EMERGENCY` / P1, dept `emergency` | `staff_alert` SMS to every emergency alert number, transfer to on-call | `R-SAFETY` |
| Exam in <= 60 min, caller blocked | `URGENT` / P1, `exam_cell` | transfer; brief has roll no and paper | `R-EXAM-60` |
| Deadline in <= 24 h, blocked | `URGENT` / P2 | transfer if open, else callback + SMS | `R-DEADLINE-24H` |
| Complaint (after read-back + "yes") | `COMPLAINT` / P3 | `ticket_created` SMS | `R-COMPLAINT` |
| Asked for a person | `HUMAN_REQUEST` / P3 | transfer, or callback + SMS after hours | `R-HUMAN` |
| Question not in KB (after "yes" to ticket) | `KNOWLEDGE_GAP` / P3, `callback_requested` | `log_gap`, `ticket_created` SMS | `R-UNANSWERED` |
| Caller declines the ticket | none | `log_gap` only | n/a |
| LLM/internal failure | `SYSTEM_FAILURE` / P3, `callback_requested` | none | `R-FALLBACK` |

`priority_reason` format: `<RULE-ID>: <rule reason> (<facts>)`, for example
`R-EXAM-60: Exam within 60 minutes and caller blocked (exam, in 15 min, caller blocked)`. Display it verbatim; it is the audit trail.

## B7. Ticket creation requirements (what you can rely on in `POST /v1/tickets`)

- Body validates against `TicketCreate`. `idempotency_key` = `{call_id}:{turn_index}:{TYPE}` (a retry sends the same key: return the
  existing ticket with `created=false`).
- `summary` <= 280 chars; `brief` <= 500 chars, 2-4 lines for staff. **The `brief` and `collected_fields` intentionally contain the roll
  number** (staff need it). `transcript_excerpt` has every run of >= 10 digits replaced by `[REDACTED]`.
- `collected_fields` keys you will see: `roll_no`, `paper` (urgent); `category`, `location`, `callback_number` (complaint);
  `callback_number` (unknown question). All values are strings.
- `caller_number` is the number from the call (may be null); `callback_number` is the number staff should call (confirmed by the caller).
- Ticket ids are yours (`<PREFIX>-<seq>`); the Brain only ever refers to them through `{{ticket_id}}`.

## B8. Staff alert requirements

- Template `staff_alert` = `"RESOLVIX ALERT: {ticket_id} {summary}. Open dashboard for brief."` The Brain sends `vars = {ticket_id, summary}`
  with `consent="staff"`; `summary` is deliberately generic ("Medical emergency reported on a live call"): no names, no roll numbers, no
  caller text. Do not require `source`/`url` for this template.
- Recipients are the numbers in `departments.yaml` -> `emergency` -> `sms_alert_numbers` (one request each; idempotency key
  `{call_id}:staff_alert:{to_number}`).
- On a P1 ticket creation emit `alert.p1` on `/v1/stream` within 1 s so the dashboard can sound/flash; the Brain cannot do this for you.
- `ticket_created` SMS: `vars = {ticket_id, dept}` where `dept` is the department **name** ("Hostel Office"), `consent="transactional"`,
  sent only to the caller's own or confirmed number.
- **Known limitation (CR-7):** the frozen key `{call_id}:ticket_created:{to_number}` means a *second* ticket in the same call to the same
  number gets its SMS deduplicated away. Expect this; it is not a bug in the Brain.
- `answer_copy` and `status_change` templates are not emitted by the Brain (status SMS is yours, triggered by staff changes).

## B9. What the dashboard should be able to show

Per ticket: priority (P1 first), type, department, `priority_reason`, `summary`, `brief`, `collected_fields`, caller/callback numbers, SMS
status, transfer events (`transfer_attempted/connected/failed`), and the knowledge-gap cluster for `KNOWLEDGE_GAP` tickets. Per call:
`TurnSummary` rows (`path`, `tier`, `kb_ids`, `urgency`, `priority`, `rule_id`, `validator_flags`, `latency_ms`, `cached_tokens`).
`validator_flags` values you may see: `citation_invalid`, `number_not_in_source`, `trimmed_sentences`, `url_removed`, `empty_text`,
`language_mismatch`, `language_mismatch_retry`, `json_retry`, `llm_timeout`, `llm_http`, `llm_empty`, `llm_config` (no API key),
`llm_truncated`, `llm_retry_failed`, `llm_retry_skipped`, `retry_failed_kept_first`, `clarify_limit`, `internal_error`.

## B10. Run the Brain-side checks that concern you

```powershell
cd brain
$env:PYTHONUTF8 = "1"
python -m resolvix_brain compile --mock --lexical --source ../contracts/kb/sample_kb_export.json   # prints KBVersionInfo + warnings
python -m resolvix_brain compile --mock --lexical --source http://localhost:8100/v1/kb/export       # once your export endpoint runs
python -m pytest tests/test_kb.py tests/test_integration_mocked.py -q -k "kb or reload"
```
