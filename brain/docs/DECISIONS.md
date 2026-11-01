# Decisions and assumptions (Member B)

Each entry: decision, why, and how to change it. "Measured" means a number from this repo's own tests/benchmarks.

1. **Layout follows the PRD, not the generic prompt.** `kb/` (compile), `faq.py` + `embeddings.py` (retrieval), `llm.py`,
   `validate.py`, `safety.py`, `urgency.py`, `rules.py`, `routing.py`, `session.py`, `flows.py`, `brain.py`, `settings.py`,
   `evaluation.py`; `eval/` and `scripts/` at `brain/`. The PRD layout matches Member A/C's expectations; separate `retrieval/`
   and `llm/` packages would only add indirection for ~150 lines each.
2. **`multilingual-e5-small` is not a fastembed built-in** (fastembed 0.9.1 lists only `-large`, ~2 GB). Primary approach
   *verified working*: `TextEmbedding.add_custom_model(...)` with mean pooling, normalisation, `onnx/model.onnx` from the Hugging
   Face repo (downloads ~470 MB once; ~47 s first load, ~2 s from cache). Documented fallback: a deterministic hashing embedder
   (`EMBED_MODE=lexical`, flagged `degraded` in `health()` and KB warnings), also used by most unit tests. It also kicks in
   automatically if the model cannot be loaded.
3. **FAQ thresholds stay 0.90 / 0.80** (PRD defaults). Checked on the real model (`calib` run, 14 hand-picked queries): true
   matches scored 0.906-0.934, the cross-style English gate question 0.861 (goes to the LLM exactly as fixture 02 expects), the
   best unrelated query 0.871. The margin is narrow (0.871 vs 0.906) on a 12-entry KB: **re-calibrate on the real dataset**
   using the abstain/answerable sets. The scorecard prints the false-hit count.
4. **Asymmetric E5 prefixes** (`query:` for the caller, `passage:` for indexed questions), as the prompt specifies. The symmetric
   variant (`query:` on both sides) scored a *false hit* of 0.914 for "library kab tak khuli rehti hai" vs a fee question.
5. **Pipeline additions (PRD order otherwise fixed).** Three deterministic steps run before the FAQ cache: personal-record
   guard (dues/marks/attendance: politely declined, person offered), greeting/thanks/goodbye handling, and a deterministic
   urgency pre-check. Reason for the last: "exam 15 minute mein hai, room nahi mil raha" is semantically close to the
   seating-plan FAQ and would otherwise be answered instead of escalated; it also keeps P1 working when the LLM is down. The
   pre-check only extracts *facts*; the rule table still decides.
6. **Plan on a copy, commit at first yield, defer lost actions.** `handle_turn` plans on `Session.clone()`, commits when the
   first content event is yielded, records only yielded speech as the assistant turn, and (if cancelled after commit) stores
   `create_ticket`/`send_sms`/`log_gap` events the runtime never received in `Session.deferred`; they are re-emitted at the
   start of the next turn (never `transfer`). Member A should not cancel non-interruptable turns (`MetaEvent.interruptable=False`).
7. **Script of replies.** Fixed lines are romanised Hindi/Hinglish (matches fixtures and sample KB) or English; if the caller's
   own text is Devanagari, Devanagari lines are used (`prompts/lines.yaml`, **not native-reviewed**). KB answers are spoken as
   written (`answer_hi` for hi/hinglish when present).
8. **`R-FALLBACK` added to `urgency_rules.yaml`** (structure unchanged); lexicon extended; see CONTRACT_CHANGE_REQUEST CR-3.
9. **Emergency: one staff alert per configured number** (see CR-2).
10. **Numeric grounding** (`speech.py`): every figure in LLM text must appear in the cited entries (answers, plus
    `source_title`/`source_ref`, because quoting "Exam Notice 14" is legitimate). Digits, `95,000`, `95 hazaar`, "ninety five
    thousand", month names (English/Hindi transliteration/Devanagari), `raat 10 baje` == `10 pm`; ordinals count ("second" ==
    2nd); `ek/do/one/two` count only before a unit (so "kar do" is not a figure); a spoken am/pm that contradicts a source am/pm
    for the same clock time is rejected, but an unstated meridiem cannot contradict. Offending **sentences are dropped**;
    `confident` becomes `partial` if grounded content remains, else `escalate`. Clarify questions may use 1-8 (option numbers).
    Limitation: Hindi number words above ~50 other than tens are not recognised; the persona tells the model to copy figures.
11. **LLM retry policy.** Primary `gpt-oss-120b`; on timeout/HTTP error/unparseable META/truncation retry **once on
    `gpt-oss-20b` only if elapsed < 1.5 s**, else the safe fallback (ticket + callback line). TTFT timeout 3 s, total 6 s.
    `max_tokens` is sent as `max_tokens` per the prompt; **unverified against live Groq** (reasoning models may count reasoning
    tokens against it; if answers truncate, raise `LLM_MAX_TOKENS` or switch to `max_completion_tokens`).
12. **Partial answers** end with an offer ("Kya main aapko X se jod doon?") and open a `human_offer` flow so "haan" connects the
    caller to that department; **confident** answers end with "anything else?" and a following "nahi/bas" ends the call.
13. **No vector DB**: the FAQ index is an in-memory numpy matrix (a few thousand questions at most); embedding runs in a worker
    thread so concurrent calls do not block the event loop.
14. **Safety lexicon is recall-biased**: one deliberate known false alarm class is documented in the eval ("fire safety
    course" contains the token `fire`). A missed emergency is worse than a staff call.
15. **Clocks.** Office hours/transfer decisions use `TurnRequest.received_at` (IST); KB validity uses `BrainSettings.today()`
    (IST date, overridable in tests). Tests pin 2026-10-23, the fixtures' date, so they do not rot when entries expire.
16. **Chit-chat path is labelled `faq`** (the `Path` enum has no chit-chat value) with `tier=chitchat`.
17. **Eval modes and exit codes.** `0` all targets met (live LLM), `1` a target missed, `2` deterministic targets met but
    LLM-dependent ones (answerable, abstain) only measured as *retrieval proxies* because the mock LLM cannot answer.
18. **PII.** Any run of >= 10 digits is masked (`[REDACTED]`) in `user_text_redacted`, in transcript excerpts, and in everything
    sent to the LLM. Roll numbers/phones are kept only in structured ticket fields (`collected_fields`, `callback_number`).
19. **Token counts are estimates** (`tiktoken o200k_base` vs Groq's tokenizer); falls back to chars/3.2 offline and says so.
20. **Caller number comes only from `CallContext`** (see CR-4).
21. **Eval data is sample-KB data**: `brain/eval/*.jsonl` and the numbers in the README describe the 12-entry placeholder KB.
22. **Expiry is enforced at answer time, not only at compile time.** An entry whose `valid_until` passed after compilation is never served
    from the FAQ cache and any LLM citation of it is `citation_invalid`; the first turn of a new IST day also recompiles from the last
    source in the background (`brain.py::_maybe_refresh`). Found while documenting versioning for Member C.
23. **The runtime owns delivered actions.** The Brain defers only actions it never yielded (barge-in); executing delivered actions
    must survive cancellation (CR-8). A reference implementation lives in `examples/runtime_sim.py`; it is an illustration, not Member A's code.
24. **No circuit breaker yet.** `health()` reports `llm: down` after 3 consecutive failures but the Brain still tries the LLM each turn
    (a stalling outage costs up to the 6 s timeout per turn). Listed as remaining work rather than added untested.
25. **KB export key (`KB_EXPORT_SERVICE_KEY`).** Optional env, sent as `X-Service-Key` for url sources only; never logged, masked in `BrainSettings.__repr__`, no redirect following (so it cannot be forwarded to another host). 401/403 give distinct, actionable `KBCompileError` messages. Found by running the Brain against Member C's real ops-api (HTTP 401); see CR-9. Caveat: `/admin/kb/reload` takes the URL from the request body, so the key goes to whatever URL the (service-key-authenticated) caller supplies; only A and C's publish flow should call it.
26. **Complaint correction bug fixed.** A correction that was a plain place name ("Central library second floor") was ignored in the `fix` step, the read-back repeated the old location, and the caller confirmed a wrong ticket. Found with the real flow against the real ops-api; two new tests. A correction that names a new problem changes the category and keeps the place; the original description is kept when a correction was consumed as a place.
27. **Known gap, not changed:** in the `collect` step any short answer (<= 8 words, no yes/no) is accepted as the location, so "mera naam Rahul hai roll number 2101234" became the location text (and was read back and stored in `collected_fields.location`). Runs of >= 10 digits are masked, shorter roll numbers are not. Needs a decision on how strict location capture should be.
