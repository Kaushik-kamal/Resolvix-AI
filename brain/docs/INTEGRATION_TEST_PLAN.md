# End-to-end integration test plan

## 0. Read this first: what "tested" means here

| Level | Meaning | Components that are real | Components that are mocked | Status |
|---|---|---|---|---|
| **M** (mocked integration) | The Brain is driven like the runtime would drive it and a stand-in ops service records what it receives | Brain, frozen contract models, HTTP for the KB-URL loader | speech-to-text (text typed in), TTS, Agora, telephony, ops-api, dashboard (represented by `FakeOps.dashboard_rows()`), SMS delivery | **Runs today, 19 tests pass** (`pytest -m mocked_integration`) |
| **G** (genuine end-to-end) | The real voice-runtime, real ops-api and real dashboard run together with the Brain | all of them | only what is unavoidable (SMS in `mock` mode, simulated transfer on the web channel) | **NOT RUN. Not possible yet:** `voice-runtime/`, `ops/` and `integration/` do not exist in this checkout, and no Groq key is configured |

A passing **M** test proves the Brain obeys the contract under a runtime that follows the contract. It does **not** prove that Member A's
code follows the contract, that Member C's code accepts these payloads, that Agora's ASR output looks like our test strings, or that the
dashboard renders anything. Every **G** row below is therefore marked `NOT RUN`; do not report them as done until someone runs them and
attaches the evidence listed in section 6.

The mocked reference runtime (`brain/examples/runtime_sim.py`) is written by Member B as an illustration. It is not a substitute for, and
must not be confused with, Member A's runtime.

## 1. The nine required scenarios

| # | Scenario | M test (passes today) | G test (needs A + C [+ key]) |
|---|---|---|---|
| 1 | Student speaks in Hindi | `test_hindi_question_is_answered_with_source_and_nothing_is_escalated` (typed Hindi text) | Speak the Hindi question into the Agora web call; confirm the agent answers aloud |
| 2 | Voice Runtime transcribes the query | **cannot be tested without Agora/ASR**; M passes the text straight in | Capture the ASR text for 20 spoken utterances (Hindi, English, Hinglish; with dates and amounts); record WER and **whether Hindi arrives in Devanagari or romanised** (see 4.2) |
| 3 | Brain understands and retrieves the correct answer | same test + `tests/test_fixture_parity.py` (real embedder), `eval --mock` | Same utterance with `LLM_MODE=live`, real KB: correct `kb_ids`, correct figure, source named |
| 4 | Brain generates the correct speech response | `test_sse_stream_has_the_shape_agora_expects` (metadata chunk, content chunk, finish, `[DONE]`, id spoken digit by digit) | Listen: number/date/amount pronunciation, ticket id read digit by digit, no pause > target before first audio |
| 5 | Operations receives the necessary events | `test_urgent_exam_reaches_ops_and_the_dashboard_with_reason_and_brief`, `test_all_posted_payloads_validate_against_the_frozen_contract` | Real ops-api: `GET /v1/calls/{id}` shows every turn; `GET /v1/tickets` shows the ticket; `GET /v1/gaps/clusters`; SMS log |
| 6 | Staff dashboard displays the appropriate ticket | proxy only: `FakeOps.dashboard_rows()` order, `alert.p1` in the fake SSE stream | Open the dashboard: P1 row on top with `priority_reason`, `brief`, `collected_fields`; banner/sound within 1 s of the call |
| 7 | Emergency query triggers the correct escalation | `test_emergency_alerts_staff_and_transfers_to_on_call`, `test_devanagari_emergency_is_detected_and_spoken_in_devanagari` | Say the phrase on a web call: script is spoken first, EMERGENCY P1 ticket, both staff-alert SMS (mock mode is fine), transfer event |
| 8 | Human assistance request reaches staff | `test_human_request_reaches_staff_open_and_closed`, `test_failed_transfer_keeps_the_ticket_open_and_tells_the_caller` | Say "mujhe kisi insaan se baat karni hai": HUMAN_REQUEST ticket, `transfer_attempted/...` events; repeat with the clock after office hours (callback + SMS) |
| 9 | LLM failure produces a safe fallback | `test_llm_failure_produces_a_ticket_and_a_spoken_fallback` (mock LLM times out) | Unset `GROQ_API_KEY` or block the network, ask a normal question: spoken fallback with ticket id, SYSTEM_FAILURE ticket in ops, no silence |

## 2. Additional scenarios (M tests that already exist)

| Behaviour | M test |
|---|---|
| ticket-first is enforced by the runtime too | `test_runtime_refuses_to_dial_before_a_ticket_exists` |
| ops outage never blocks the call; ticket replayed later; no duplicate | `test_ops_outage_never_blocks_the_call_and_the_ticket_is_replayed_later`, `test_replaying_a_turns_actions_is_idempotent` |
| barge-in before actions are delivered / while one is in flight / new request cancels the old stream | `test_barge_in_before_actions_are_delivered_defers_them_to_the_next_turn`, `..._while_an_action_is_in_flight_does_not_lose_it`, `test_a_new_request_for_the_same_call_cancels_the_running_stream` |
| caller number only from `CallContext` | `test_caller_number_comes_from_call_context_only` |
| KB publish over real HTTP, drafts/expired/injected excluded, live calls keep their version, bad source keeps the old KB | `test_kb_reload_from_a_url_like_the_ops_publish_flow` |
| unknown question -> gap + ticket + SMS only after the caller agrees | `test_unknown_question_creates_gap_ticket_and_sms_after_confirmation` |
| frozen SMS-key limitation (CR-7) | `tests/test_sms_dedup.py`, `tests/test_turn_rollback.py`; `test_second_ticket_in_one_call_requests_no_second_sms_and_never_posts_a_duplicate` |
| expired entries not served after midnight, daily refresh | `tests/test_expiry_rollover.py` (4 tests) |

Run them:

```powershell
cd D:\hackathon\resolvix\team-package\resolvix\brain
.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
pytest -m mocked_integration -v          # 19 tests, ~3 s, no network, no key
pytest -q                                # everything: 493 tests (483 offline + 10 that load the real e5 model; the two selections do not overlap)
```

## 3. Genuine end-to-end plan (to be executed by Member A with B and C present)

### E0. Preconditions (all must be true; record the evidence)

| # | Check | Command / evidence | Owner |
|---|---|---|---|
| E0.1 | contracts green in all three environments | `pytest contracts/tests -q` -> `6 passed` (use `$env:PYTHONUTF8="1"` on Windows) | each member |
| E0.2 | Brain installs in the runtime's venv | `pip install -e brain; pip check` -> no broken requirements | A |
| E0.3 | ops-api healthy | `Invoke-RestMethod http://localhost:8100/healthz` -> `status: ok`, `contract_version: 1.0.0` | C |
| E0.4 | runtime healthy with the real Brain | `Invoke-RestMethod http://localhost:8000/healthz` -> `brain.status` is `ok` or `degraded` with a known reason, `brain.kb_version` not `none` | A |
| E0.5 | KB loaded from ops | publish from the dashboard; response is a `KBVersionInfo` with the expected warnings | C + A |
| E0.6 | Groq key present for the live runs | `$env:GROQ_API_KEY` set, `LLM_MODE=live`; `python -m resolvix_brain bench` shows `cached_tokens` on the warm call | B |
| E0.7 | phone numbers in `departments.yaml` are real or deliberately mock | (config review) | all |

### E1. Typed-turn E2E (no audio): real runtime + real ops + real Brain

Start (commands from PRD section 12; **they could not be verified here because those packages do not exist**):

```powershell
# terminal 1 (Member C)
uvicorn resolvix_ops.app:app --port 8100
# terminal 2 (Member A)
$env:BRAIN_IMPL = "real"; $env:OPS_API_URL = "http://localhost:8100"; $env:LLM_MODE = "mock"   # then "live" for the second pass
uvicorn resolvix_runtime.app:app --port 8000
# terminal 3 (Member C)
npm run dev   # dashboard on :5173
```

Drive scenario turns with the typed endpoint from `voice-runtime.yaml` (`POST /api/test/turn`, body `{call_id?, text}`):

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/test/turn -ContentType "application/json" `
     -Body (@{ call_id = "e1-urgent"; text = "Exam 15 minute mein hai, room nahi mil raha!" } | ConvertTo-Json)
$r.spoken_text
$r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/test/turn -ContentType "application/json" `
     -Body (@{ call_id = "e1-urgent"; text = "Roll number 2400271549999, paper Data Structures." } | ConvertTo-Json)
$r.spoken_text                      # ticket id read digit by digit, "connecting"
Invoke-RestMethod "http://localhost:8100/v1/tickets?priority=P1" -Headers @{ "X-Service-Key" = $env:SERVICE_KEY }
```

| Case | Turns (text) | Assert in ops-api | Mock LLM enough? |
|---|---|---|---|
| E1-1 Hindi FAQ | `fees kab tak jama karni hai` | no ticket; `GET /v1/calls/{id}` has the turn with `kb_ids=["FEE-001"]` | yes (FAQ path) |
| E1-3 live answer | `What time does the hostel gate close?` | turn `path=llm`, `cached_tokens` on the 2nd run | **no: needs Groq key** |
| E1-7 emergency | `Hostel mein ek ladka behosh ho gaya hai` | 1 ticket `EMERGENCY` P1 `emergency`; 2 `staff_alert` SMS; ticket events `transfer_attempted`; `alert.p1` on `/v1/stream` | yes |
| E1-8 human | `mujhe kisi insaan se baat karni hai` | `HUMAN_REQUEST` P3 `helpdesk`; transfer events; repeat after hours -> `callback_requested=true` + `ticket_created` SMS | yes |
| E1-9 LLM failure | `Admission ke liye kaunse documents chahiye?` with the key unset | `SYSTEM_FAILURE` P3, turn `path=fallback`, `rule_id=R-FALLBACK` | yes (mock mode: this phrase triggers the mock timeout); in live mode unset the key |
| E1-U unknown | `Noida sector 62 ke liye bus route kya hai?`, then `haan isi number par call kar dena` | `KNOWLEDGE_GAP` ticket, one gap in `/v1/gaps/clusters`, `ticket_created` SMS | yes |
| E1-C complaint | the 4-turn script in `docs/samples/events_06_complaint_confirmed.json` | `COMPLAINT` ticket with `collected_fields.location` | yes |

**Pass criteria for E1:** every assertion above, plus: no ticket is created twice when the same turn is replayed; `GET /v1/tickets`
returns the P1 first; the typed page never shows `{{ticket_id}}`.

### E2. Web voice call (Agora), real audio

Cases: scenarios 1-4 and 7-9 spoken aloud in Hindi, English and Hinglish, with barge-in (talk over the answer, then talk over the
emergency script). Record for each: the ASR text (**Devanagari vs romanised**), time from end of speech to first audio (stopwatch or log
`latency_ms`), what was heard. Pass: nothing silent, ticket-first holds, the P1 appears on the dashboard while the call is still
in progress.

### E3. Phone call (only if Spike S1 succeeds)

Same as E2 from a real phone; transfer to a test number; unanswered transfer leaves the ticket open and the caller is told.

### Failure drills (from PRD 3.12; run in E1 and again in E2)

| Drill | Action | Must see |
|---|---|---|
| Groq down | unset `GROQ_API_KEY` / block `api.groq.com` | fallback line + `SYSTEM_FAILURE` ticket, safety/human/FAQ turns still work |
| ops-api down | stop uvicorn on 8100 | call continues, local TMP id, ticket appears after ops restarts, no duplicates |
| transfer unanswered | MockTelephony fail | ticket stays open, caller told, `transfer_failed` event |
| gibberish twice | `hmm`, then empty | re-prompt, then "connect you to staff?" |
| hang up mid-turn | close the call during an answer | no exception, `POST /v1/calls/{id}/end`, Brain session dropped |
| KB publish error | export an entry with a duplicate id | 422 with the problem, old KB still serving |

## 4. Known risks the genuine tests must settle (found while preparing, not yet resolved)

1. **Hindi ASR script.** If the ASR returns Devanagari, FAQ cache hits drop sharply (measured with the real embedder on 6 Devanagari
   FAQ-style questions: right entry ranked first 6/6, but only 1/6 cleared the 0.90 threshold). Those turns go to the LLM, so the
   live LLM path is on the critical path for Hindi callers. Mitigation: Devanagari question variants in the KB, or lower the threshold
   after measuring on real transcripts (decision for Member B with data from E2).
2. **Cancellation semantics** between the runtime and the Brain (A7 in `INTEGRATION_EXAMPLES.md`): the runtime must shield actions and close the generator.
3. **Single-process requirement** for the Brain's in-memory sessions.
4. **First-audio latency** with the real LLM is unmeasured.

## 5. Mapping to Member A's planned `integration/` files (PRD section 8, 12)

`integration/scenarios.yaml` should contain the E1 table (turns + assertions); `integration/e2e_test.py` runs each scenario through
`/api/test/turn` and asserts on ops-api state; `run_demo_checks.sh` (PowerShell equivalent on Windows) runs E0 and the failure drills.
Member B provides the expected values: use `docs/samples/*.json` for the exact event shapes and `contracts/fixtures/brain_streams` for the frozen ones.

## 6. Evidence required before a G test is reported as passing

For each G case record: date/time, git revision of all three components, `kb_version`, LLM mode and model, the exact input, the spoken
output (transcript), the ops-api JSON (ticket, turn, SMS), a dashboard screenshot for scenarios 6-8, and the measured latency. A case
without that evidence stays `NOT RUN`.

## 7. Status board (updated 2026-11-01)

| Scenario | M | G |
|---|---|---|
| 1 Hindi question | PASS | NOT RUN (A, C missing) |
| 2 Transcription | n/a | NOT RUN (needs Agora) |
| 3 Retrieval/answer | PASS (FAQ path real embedder; LLM path mock) | NOT RUN (needs Groq key) |
| 4 Speech response | PASS (shape and placeholders) | NOT RUN |
| 5 Ops receives events | PASS (against FakeOps) | NOT RUN (C missing) |
| 6 Dashboard shows ticket | proxy only | NOT RUN (C missing) |
| 7 Emergency | PASS | NOT RUN |
| 8 Human request | PASS | NOT RUN |
| 9 LLM failure fallback | PASS (mock timeout) | NOT RUN (live outage drill) |
