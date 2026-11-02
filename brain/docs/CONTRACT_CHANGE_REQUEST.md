# Contract change requests / observations (Member B)

Contracts are frozen at v1.0.0. **Nothing below blocks anyone**: the Brain is implemented and tested against the contract as
it is. These are findings to discuss before a future v1.1; no frozen file was edited.

## CR-1 (test portability, blocks Windows runs): `contracts/tests/test_contracts.py` needs UTF-8
`test_config_files` calls `read_text()` without `encoding`. On Windows the default is cp1252, so the test raises
`UnicodeDecodeError` while reading `contracts/config/urgency_rules.yaml`. This also fails on the **original, unmodified**
file from `resolvix-team-package.zip` (it already contains Devanagari terms such as the virama in "आत्महत्या"), so it is not
caused by Member B's lexicon edits. All 6 tests pass with `PYTHONUTF8=1`.
- Workaround (what we do): `$env:PYTHONUTF8 = "1"` before `pytest contracts/tests` in PowerShell.
- Proposed fix (owner of `contracts/tests`): `read_text(encoding="utf-8")` for the YAML and JSONL reads.

## CR-2 (informational): emergency staff alerts, fixture vs config
Fixture `05_emergency_safety` shows one `send_sms(staff_alert)` (to `+910000000901`) but `departments.yaml` configures two
`sms_alert_numbers` for the emergency department (`...901`, `...902`). The Brain follows the config and the prompt ("to each
emergency `sms_alert_numbers` entry"), so it emits two. The parity test treats consecutive identical action kinds as one and
a second test (`test_emergency_alerts_every_configured_number`) asserts both numbers are alerted. If one alert was intended,
the config or the fixture should change, not the Brain.

## CR-3 (informational): `urgency_rules.yaml` gained one rule, `R-FALLBACK`
Fixture `08` expects `rule_id == "R-FALLBACK"` but the delivered rule table had no such rule. Member B added it as
`when: {intent: system_failure}` (never matched from caller text; raised only by the brain on LLM/internal failure), placed
before the catch-all. The structure is unchanged (`rules[0].id == "R-SAFETY"`, last rule `when: {}`), contract tests stay
green. `action: ticket_and_callback` is a new action name; Member C only displays it. The `safety_lexicon` lists were also
extended (same four keys) and `human_request_exclusions` was added.

## CR-4 (limitation worth a v1.1 field): `TurnRequest` carries no caller number
The caller number reaches the Brain only through `CallContext` in `start_call`. If Member A's runtime restarts mid-call, the
next `TurnRequest` creates an ad-hoc session without a caller number, so the Brain cannot offer "call you back on this
number" or send an SMS (it asks for a number instead; verified by test). Suggest an optional `caller_number` on `TurnRequest`.

## CR-5 (informational): fixture `lang` values are inconsistent
`01` (romanised Hindi, no English function words) is labelled `hi`; `09` (the same style) is labelled `hinglish`. The Brain
labels both `hi`. The parity test does not compare `lang`; fixed spoken lines are identical for `hi` and `hinglish`.

## CR-6 (informational): fixtures 04 and 06 are mid-conversation
Both requests have an empty `history` but depend on earlier turns (urgency facts; location and number confirmation). The
parity tests replay the setup turns (turn 1 for `04`; turns 1-3 for `06`; turn 1 for `03`) before the fixture request. Member
A's runtime must send turns of one call to the same Brain session (the Brain keeps the dialogue state itself).

## CR-7 (real limitation in the frozen helper): the SMS idempotency key has no ticket/turn component
`sms_idempotency_key(call_id, template_id, to_number)` = `"{call_id}:{template_id}:{to_number}"`. Two tickets created in one
call for the same number (for example a complaint, then an unanswered question) produce the same key for their
`ticket_created` SMS, so ops-api (which dedupes on this key) will **suppress the second SMS**. The Brain uses the frozen helper
as the contract requires; the behaviour is pinned by `test_second_ticket_in_one_call_does_not_get_a_second_sms_because_of_the_frozen_key_format`.
Impact is small (the caller still hears the second ticket id) but the second ticket's SMS never leaves. Suggested v1.1 fix: include
`ticket_type` or `turn_index` in the key.

**Verified against the real ops-api (2026-11-01, scratch copy of Member C's `member-c-ops` branch, mock LLM):** a complaint
ticket `HS-1008` and then a human-request ticket `HD-1009` in one call to one number. ops-api stored **one** SMS row
(`cr7:ticket_created:+9190…`, ticket `HS-1008`); the second POST was deduplicated. The Brain told the caller "SMS bhi bhej diya
hai" for `HD-1009`, so the caller may believe a text about `HD-1009` is coming while only the `HS-1008` text exists.
**Agreed behaviour (review of PR #1, Member C, recorded here):**
- **Ops deduplicates SMS through `idempotency_key`.** A repeated key returns HTTP 200 with the *stored* `SmsResult` of the first
  message (a new request returns 202) and nothing is sent again. This is Member C's implementation and it is correct.
- **A deduplicated SMS must not be represented to the caller as successfully sent.** "SMS bhi bhej diya hai" / "I have also sent you an
  SMS" may be said only for an SMS that ops accepted as new (202) and did not suppress. A 200 duplicate, or a result whose status is
  `suppressed` or `failed`, means no text left for *this* ticket, so the spoken line must not claim one (the ticket id is still spoken).
- **Frozen contract v1.0.0 is not changed** (neither `sms_idempotency_key` nor the contract version) without approval from the team.
  Option 1 below is the only route that changes it and stays a v1.1 proposal.

**Status of that rule (honest limits):** the Brain still decides what to say *before* the runtime executes `send_sms` (the Brain does
no I/O and never sees the ops result), so today the Brain's line can be spoken for a second SMS that ops will then deduplicate. Closing
that gap needs either Option 2 (Brain-only, a session-level "already queued a `ticket_created` SMS to this number" check; not implemented,
needs a go-ahead) or Member A's runtime acting on the ops response (suppress or replace the claim). Until one of them lands, CR-7 is open
for calls that create two tickets for one number; the single-ticket path is unaffected. No code for this was changed in this review.

**Recommendation for the team (options):**
1. *Preferred, needs all three to approve (v1.1):* include `ticket_type` (or `turn_index`) in the SMS key. The Brain, A and C would each change one line, and fixture 06's key (`call-complaint:ticket_created:+91…`) would need regenerating, which is why the Brain does not do it alone.
2. *No contract change, Brain-only (not implemented, needs a go-ahead):* the Brain remembers it already queued a `ticket_created` SMS to that number in this call and, for the second ticket, drops the `send_sms` action and the line "SMS bhi bhej diya hai" (the ticket id is still spoken).
3. *Accept for the demo:* one ticket per call is the normal path; document it.

## CR-8 (integration hazard, not a contract change): once the Brain yields an action, the runtime owns it
The Brain only re-emits actions it never *delivered* (barge-in before the yield). If the runtime cancels its own task while a
`create_ticket` call is in flight, nothing re-sends it. The runtime must shield action execution from barge-in cancellation
(`asyncio.shield`) and must always `await agen.aclose()` on the `handle_turn` generator. Both are demonstrated and tested in
`examples/runtime_sim.py` (see docs/INTEGRATION_EXAMPLES.md section A7).

**Status of the investigation (2026-11-01):** it can only be settled in Member A's code, which does not exist on GitHub yet, so
no real-runtime test was possible. What is verified: the Brain side (cancel after the yield, deferred actions, `aclose`) with
generators/tasks, and the reference pattern in the mocked runtime. **Recommendation for A:** (1) run every action inside
`asyncio.shield(...)` and inside `try/finally` that always does `await agen.aclose()`; (2) key the per-call task registry by
`call_id` and cancel only the *speaking* task; (3) add a test that cancels the SSE response between the `create_ticket` event
and its completion and asserts that the ticket exists in ops-api afterwards (genuine E6). No contract change is needed.

## CR-9 (resolved inside the Brain, no contract change): `/v1/kb/export` needs a key the Brain did not send
`ops-api.yaml` applies `serviceKey | session` to every path unless it says `security: []`, and `/v1/kb/export` does not. Member C
implements exactly that (`kb_routes.export_kb` depends on `get_principal`), so `Brain.reload_kb(KBSource(kind="url"))` got
HTTP 401 against the real ops-api. `KBSource` has no header field and is frozen. **Brain fix:** `KB_EXPORT_SERVICE_KEY` (env, optional) is
sent as `X-Service-Key` for url sources only; it must equal the ops-api `SERVICE_KEY`. 401 and 403 produce clear
`KBCompileError` messages, the key is never logged or echoed, redirects are not followed, file sources never use it, and the old KB
stays active after a failed reload. Member A must make the same value available to the runtime process (the Brain runs in-process).
Nothing in ops-api authentication was weakened. For the contract: consider adding "requires X-Service-Key" to the `/v1/kb/export` description.
