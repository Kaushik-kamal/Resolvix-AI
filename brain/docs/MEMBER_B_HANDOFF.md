# Member B handoff: the Brain, ready for integration

Date: 2026-11-01. Contract version: 1.0.0 (frozen, untouched). Owner: Member B (`brain/**` and the content of
`contracts/config/urgency_rules.yaml`).

Companion documents:
- `INTEGRATION_EXAMPLES.md`: how Member A and Member C plug in (initialisation, sessions, events, barge-in, KB export/reload, tickets, SMS), with real sample payloads in `docs/samples/`.
- `INTEGRATION_TEST_PLAN.md`: the nine end-to-end scenarios, split into **mocked (run, passing)** and **genuine (not run)**.
- `DECISIONS.md`, `CONTRACT_CHANGE_REQUEST.md` (CR-1 to CR-9), `LATENCY.md`, `../README.md`.

## 1. Where we stand

**The Brain is complete, tested and integration-ready as a library. The integrated Resolvix application does not exist yet.**
Member A's `voice-runtime/` and Member C's `ops/` are not in this checkout, so nothing outside the Brain has been exercised, and the
Brain itself has never talked to the real Groq API.

| Area | State |
|---|---|
| Brain library (pipeline, KB compiler, retrieval, safety, urgency, flows, validators, LLM client) | Complete; 498 tests (488 offline + 10 real-model) |
| Frozen contract v1.0.0 | Unchanged; 6 contract tests pass (need `PYTHONUTF8=1` on Windows) |
| Nine fixture scenarios | Reproduced structurally (10 tests incl. the emergency-alert check) |
| Clean-venv install | Verified today against the current code |
| Mocked integration with a reference runtime and an in-memory ops service | 19 tests pass |
| Genuine integration with Member A's runtime, Member C's ops-api and the dashboard | **Not run (components absent)** |
| Live Groq (request format, latency, prompt caching, answer quality) | **Not run (no key)** |
| Real AKGEC knowledge base and staff-reviewed urgency rules | **Missing** |

## 2. Step 1: verification results (re-run on 2026-11-01)

```powershell
cd D:\hackathon\resolvix\team-package\resolvix
brain\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
pytest contracts/tests -q                                   # 6 passed
cd brain
pytest -q                                                   # 498 passed (488 offline + 10 real-model)
pytest -q -m "not realembed"                                # 488 passed, 10 deselected (offline subset)
pytest -q -m realembed                                      # 10 passed (loads multilingual-e5-small)
pytest -m mocked_integration -q                             # 19 passed
python -m resolvix_brain eval --mock                        # exit code 2 = deterministic targets met, LLM ones not verified
```

### 2.1 Test-count reconciliation (the "304" question)

| Snapshot | Count | Why |
|---|---|---|
| mid-session run | 296 | before the ingest/CLI tests were added |
| end of the Brain build (the number in the earlier report) | **304** = 294 offline + 10 real-model | accurate **at that time** |
| after this handoff pass | **327** = 317 offline + 10 real-model | + 19 mocked-integration tests + 4 expiry-rollover tests |
| README wording | "300+" | still true; the exact figure is above |

Per file now: `test_rules_safety` 166, `test_validate_speech_llm` 49, `test_flows_brain` 49, `test_integration_mocked` 19, `test_kb` 22,
`test_fixture_parity` 10, `test_ingest_and_cli` 8, `test_expiry_rollover` 4. **Caution when quoting the number:** 166 of the 327 are one
parametrised test per safety-lexicon term/phrase, so the count overstates breadth. The meaningful groups are in section 2.2.

Contract tests: **6**, unchanged. They fail on Windows under the default cp1252 encoding even for the *original* files in the zip (CR-1);
set `$env:PYTHONUTF8 = "1"`.

### 2.2 What each requested area is verified by

| Area | Evidence |
|---|---|
| Nine fixtures | `tests/test_fixture_parity.py`: same event types/order, action kinds, tier, priority, rule id, department, urgency facts, SMS template/consent (consecutive speech events and identical action kinds collapsed; emergency alerts both configured numbers) |
| Clean virtual-environment install | fresh venv: `pip install -e contracts/python -e "brain[dev]"`, `pip check` clean, tests as above (repeated today) |
| KB compiler | `tests/test_kb.py` (22): deterministic version, draft/expired/future/injected exclusion, dedupe, token budget, atomic swap, pinned sessions, warm-up, HTTP loader; `tests/test_expiry_rollover.py` (4) |
| Urgency and emergency detection | `tests/test_rules_safety.py`: every rule and boundary (59/60/61 and 1439/1440), first match wins, every lexicon term, normal sentences not flagged, < 5 ms, LLM never called on the safety path, LLM-extracted safety flag also escalates |
| LLM fallback | `test_llm_down_...`, retry-policy tests with a scripted client, Groq client over a mocked SSE transport (429, timeout, empty, usage/`cached_tokens`), `invalid-json`, `bad-citation`, `ungrounded-number` drills. **Not verified against live Groq** |
| Hindi / English / Hinglish | reply language and script follow the caller (`test_reply_language_and_script_follow_the_caller`: English, Devanagari, romanised), short English replies do not flip a Hindi call, Hinglish complaint/unknown/urgent flows, spoken-form numbers (`95 hazaar rupaye`, `raat 10 baje`), Devanagari emergency end to end |

### 2.3 Discrepancies found and resolved during this pass

| Finding | Resolution |
|---|---|
| Test count differed between messages (296 / 304 / "300+") | explained above; the count measured on 2026-11-02 is 498 = 488 offline (`-m "not realembed"`) + 10 real-model tests (`-m realembed`), run as separate selections with no overlap; subsets such as `-m mocked_integration` are part of the 488, not additional | **Expired KB entries kept being served after midnight** until someone published | **fixed**: expiry re-checked at answer time (FAQ hit and LLM citation), plus an automatic background recompile on the first turn of a new day (`brain.py::_maybe_refresh`, 4 tests). Small targeted change; no module rewritten |
| SMS idempotency key (frozen helper) suppresses the second `ticket_created` SMS of a call | handled Brain-side per call (`Session.sms_requested`, no contract change); see CR-7 and `tests/test_sms_dedup.py` |
| Runtime cancellation can lose an action the Brain already delivered | not a Brain bug; documented as CR-8 and demonstrated in the reference runtime (shield + `aclose`) |
| Devanagari queries rarely clear the FAQ threshold (1 of 6) although the right entry ranks first (6 of 6) | measured, not fixed: they fall through to the LLM. Needs real ASR transcripts to tune (section 6) |
| `compile`/`chat` print a "GROQ_API_KEY is missing" error in live mode without a key | expected; use `--mock` for key-less runs |

Files changed in this pass (all inside `brain/`): `kb/compiler.py` (`compiled_on`, `is_expired`), `kb/store.py` (`last_source`),
`validate.py` (optional `today`), `brain.py` (expiry + daily refresh), `pyproject.toml` (marker), `tests/test_integration_mocked.py`,
`tests/test_expiry_rollover.py`, `examples/runtime_sim.py`, `examples/dump_payloads.py`, `docs/*`. **Nothing outside `brain/` was
touched in this pass**, and `contracts/` is byte-identical to the previous state (the only change from your original zip remains
`urgency_rules.yaml`, listed in CR-3).

## 3. What the Brain guarantees (and does not)

Guarantees (tested): never raises to the runtime from `handle_turn`; meta first, done last; ticket before transfer and before any
`{{ticket_id}}` speech; safety phrases never reach the LLM; priority decided by the rule table, never by the LLM; no figure/date/amount
is spoken unless it appears in a cited, currently valid KB entry; no SMS to anyone but the caller's own/confirmed number or staff; PII
(>= 10-digit runs) is masked in summaries, excerpts and everything sent to the LLM.

Does **not**: perform side effects (A executes actions); persist sessions; answer personal records; authenticate callers; guarantee
latency with the real LLM; answer anything without a valid KB entry.

## 4. Exactly what the other two members need to do

### Member A (voice-runtime): `INTEGRATION_EXAMPLES.md` Part A has the detail

1. `pip install -e ../contracts/python` and `pip install -e ../brain` into the runtime venv; `pip check`; `pytest contracts/tests`.
2. Implement `brain_loader.py` `BRAIN_IMPL=real`: `create_brain(BrainSettings.from_env())` and `await brain.ready()` at startup.
3. Run **one worker process**. (Sessions are in memory.)
4. Call `brain.start_call(CallContext(... caller_number ...))` once per call; one monotonic `turn_index` per call; `await brain.end_call()` at hang-up.
5. Translate events as in section A5; substitute `{{ticket_id}}` with `speak_ticket_id(id, lang)` in speech and the raw id in SMS vars.
6. Implement the executor rules (ticket-first, TMP id + retry queue, transfer events, SMS, gap).
7. **Barge-in:** `async for` inside `try/finally: await agen.aclose()`; execute actions under `asyncio.shield`; do not cancel `interruptable=False` turns.
8. `/admin/kb/reload` -> `brain.reload_kb(KBSource)`; map `KBCompileError.problems` to 422.
9. Pass `received_at` as the real IST time of the utterance (office hours depend on it).
10. Decide how to cover a stalled LLM (a filler line if nothing arrives within ~1.5 s); confirm your TTS reads romanised Hindi **and** Devanagari.
11. Replace the mock with the real Brain in your replay tests and run E1 from `INTEGRATION_TEST_PLAN.md`.

### Member C (ops-api and dashboard): `INTEGRATION_EXAMPLES.md` Part B has the detail

1. `GET /v1/kb/export` returns a valid `KBExport` and is reachable by the runtime **without a browser session** (the Brain does a plain GET).
2. Put `valid_until` on dated content; add Devanagari question variants for key FAQs; keep `source_title` short and speakable.
3. After `POST /v1/kb/publish`, show `KBVersionInfo.warnings` (what was excluded and why) and, on failure, the problem list.
4. Accept every ticket/SMS/gap/turn payload in `docs/samples/ops_received_after_emergency_and_human.json`; idempotent on the documented keys.
5. Emit `alert.p1` for P1 tickets within 1 s; show `priority_reason`, `brief`, `collected_fields`, transfer events, SMS status.
6. SMS policy must accept `staff_alert` (`vars: ticket_id, summary`; `consent: staff`) and `ticket_created` (`ticket_id, dept`; `transactional`). The Brain requests each (recipient, template) SMS at most once per call (CR-7); ops should still dedupe on `idempotency_key`.
7. Read `urgency_rules.yaml` as is (it now contains an `R-FALLBACK` rule with `action: ticket_and_callback`).

### Whole team
1. Give Member B the real dataset (`scripts/ingest_raw.py` turns it into draft entries) and set `KB_SOURCE`.
2. A staff member reviews `urgency_rules.yaml` (thresholds, lexicon, departments) and the Devanagari lines in `prompts/lines.yaml`.
3. Obtain a Groq key; Member B runs Spike S2 and the live eval (commands below), then re-tunes thresholds with real transcripts.
4. Run `INTEGRATION_TEST_PLAN.md` E0 -> E1 -> E2 and attach the evidence listed in its section 6.

### Member B (remaining)
Run live bench/eval when a key exists and update `LATENCY.md`; calibrate FAQ thresholds on real data and real ASR output; add a simple
LLM circuit breaker (see 5); review the CR items with A and C; rewrite `brain/eval/*.jsonl` for the real KB.

## 5. Step 5: real-world readiness

| Requirement | Status | What is needed |
|---|---|---|
| Groq API key | **Missing** | key in `brain/.env` (never committed); then run the live commands below. Also unknown: whether `max_tokens: 300` leaves room for gpt-oss reasoning tokens, and the exact streaming usage fields |
| Real college knowledge base | **Missing** | dataset -> `ingest_raw.py` -> human approval -> publish. Sample KB is placeholder data and must not be presented as real |
| Staff-reviewed urgency rules | **Missing** | thresholds (60 min / 24 h), departments, lexicon (recall-biased: "fire" etc.), emergency numbers (`112` and the on-call numbers in `departments.yaml` are placeholders) |
| Runtime integration | **Not started in this repo** | Member A (section 4); nothing outside the Brain has been exercised |
| Persistent session management | **Not implemented; required only if** the runtime runs more than one process or must survive restarts. Sessions are in memory (TTL 2 h). `Session`/`Flow` are plain dataclasses (JSON-serialisable) so Redis could be added behind `SessionStore`, but nothing is built or tested. For a single-process demo it is not needed |
| Production error handling | **Partial.** Present: never-raise contract, fallback ticket, timeouts, retry on the small model, safe KB reload, idempotent actions, secrets not logged, PII masked. **Missing:** an LLM circuit breaker (during a *stalling* outage every LLM turn can wait up to the 6 s timeout before falling back; `health()` reports `llm: down` after 3 failures but does not skip the call), structured logs with `call_id`, metrics/alerts, request rate limiting, load testing with the real LLM, a timer-based re-prompt for caller silence (the Brain only reacts to turns it is given; silence handling is a runtime P1 feature) |
| Hindi ASR script handling | **Unknown** | Devanagari vs romanised ASR output decides how often the FAQ cache hits (CR / plan section 4.1) |
| Data protection | **Not reviewed** | recording/transcript retention and DPDP obligations are the college's/legal decision; the Brain stores no transcripts itself (ops does) |

## 6. Live-run commands (when a Groq key exists)

```powershell
cd D:\hackathon\resolvix\team-package\resolvix\brain
.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
$env:LLM_MODE = "live"
$env:GROQ_API_KEY = "<your key>"            # or put it in brain\.env (git-ignored); never paste it into a file that is committed
python -m resolvix_brain bench              # Spike S2: cold vs warm ttft/total/prompt_tokens/cached_tokens for both models
python -m resolvix_brain eval               # answerable/abstain now end to end; exit code 0 only if every target is met
python -m resolvix_brain chat               # talk to it; each event is printed as JSON plus the spoken text
```

Then paste the numbers into `docs/LATENCY.md` and report any failure honestly (the request shape and the answer quality have never been
checked against the real service).

## 7. Everyday commands

```powershell
# regenerate sample payloads after any behaviour change
python examples/dump_payloads.py
# KB tools
python -m resolvix_brain compile --mock --lexical --source ../contracts/kb/sample_kb_export.json
python scripts/ingest_raw.py data/raw/<dataset.csv> --out data/kb.jsonl
# offline subset (no model download), real-model subset
pytest -q -m "not realembed"
pytest -q -m realembed
```

## 8. File inventory (everything Member B owns)

`brain/resolvix_brain/` (18 modules, the `kb/` package, `prompts/persona.md`, `prompts/lines.yaml`), `brain/tests/` (8 files), `brain/eval/` (5 sets +
`run_eval.py`), `brain/scripts/ingest_raw.py`, `brain/examples/` (`runtime_sim.py`, `dump_payloads.py`), `brain/docs/` (this file,
`INTEGRATION_EXAMPLES.md`, `INTEGRATION_TEST_PLAN.md`, `DECISIONS.md`, `LATENCY.md`, `CONTRACT_CHANGE_REQUEST.md`, `samples/`),
`brain/README.md`, `brain/.env.example`, `brain/pyproject.toml`, `brain/data/raw/README.md`; plus the content of
`contracts/config/urgency_rules.yaml`. The `brain/.venv` and `brain/.cache` folders are local build artefacts (git-ignored; do not zip them).

## Phase 1 update (2026-11-01): Brain + Member C's real ops-api
Done in this package only (nothing in Member C's or Member A's files; nothing committed). Details: `CONTRACT_CHANGE_REQUEST.md` CR-7/8/9, `DECISIONS.md` 25-27.
- `KB_EXPORT_SERVICE_KEY` added (CR-9): fixes the HTTP 401 on `/v1/kb/export`. 10 new tests against a real local HTTP server (valid, missing, invalid, 403, redirect, logging, settings repr, file sources, failed reload keeps the old KB).
- Complaint flow investigated with a real ops-api: the earlier "incomplete" script was my script's turn order (the flow works as designed), but the trace exposed a real bug (a place-name correction was dropped); fixed with 2 tests.
- Ticket events: the reference runtime now stamps `at` (frozen `TicketEvent` requires it, ops-api returns 422 without it); the mocked ops validates every event with the frozen model.
- Test totals (measured 2026-11-02, same run session): 498 Brain tests = 488 offline passed + 10 real-model passed (separate selections, no overlap, 0 failed, 0 skipped), plus 6 contract tests.
