# resolvix_brain: the Brain (Member B)

A pure Python library (plus CLI) that takes what the caller said and decides what to say and which actions to *request*. It
answers only from the approved knowledge base, never speaks a figure that is not in a cited entry, decides priority with a
deterministic rule table (the LLM only extracts facts), and creates a ticket before any transfer. It does no I/O except the
LLM and the local embedding model: no HTTP server, database, Agora, SMS or UI (those belong to Members A and C).

Status: implemented and tested against the frozen contract v1.0.0 (498 tests: 488 offline + 10 that load the real embedding model, counted separately).
Start with `docs/MEMBER_B_HANDOFF.md`; integration guides for Members A and C are in `docs/INTEGRATION_EXAMPLES.md`, the test plan in
`docs/INTEGRATION_TEST_PLAN.md`. Nothing outside the Brain (runtime, ops-api, dashboard, Agora, live Groq) has been exercised. **Not yet exercised against the live Groq API** (no key was
available): see "Known limitations".

## Setup (PowerShell, from the repo root `resolvix/`)

```powershell
python -m venv brain\.venv
brain\.venv\Scripts\Activate.ps1
pip install -e contracts/python -e "brain[dev]"
$env:PYTHONUTF8 = "1"                       # the frozen contract test reads UTF-8 files without saying so (see docs/CONTRACT_CHANGE_REQUEST.md CR-1)
pytest contracts/tests -q                   # must be green first (6 tests)
cd brain
pytest -q                                   # 498 tests (488 offline + 10 real-model); the first run downloads the e5 model (~470 MB, one time)
pytest -q -m "not realembed"                # offline-only subset (no model download)
python -m resolvix_brain eval --mock        # scorecard (exit code 2 = deterministic targets met, LLM ones not verified)
python -m resolvix_brain eval --mock --kb-set akgec-draft   # the 21-entry DRAFT AKGEC KB with eval/akgec/ (temporary approved copy, evaluation only)
python -m resolvix_brain chat --mock        # interactive REPL, prints each event as JSON plus the spoken text
```

Live mode: copy `.env.example` to `.env`, set `GROQ_API_KEY` (never commit it), then `python -m resolvix_brain chat`.

## Public interface (what Member A uses)

```python
from resolvix_brain import create_brain, BrainSettings
brain = create_brain(BrainSettings.from_env())      # satisfies resolvix_contracts.Brain (isinstance check passes)
await brain.ready()                                  # optional: load model + default KB at startup (start_call does it too)
plan = await brain.start_call(CallContext(...))      # greeting + consent line, interruptable=False
async for ev in brain.handle_turn(TurnRequest(...)): # meta, (speech|action)*, done. Never raises.
    ...
await brain.end_call(call_id)
info = await brain.reload_kb(KBSource(...))          # the only method that raises (KBCompileError(problems)); old KB stays active
brain.health()                                       # {status, kb_version, llm, contract_version, embedder, ...}
```

Rules for the runtime: send all turns of one call to the same Brain instance (it holds the dialogue state); execute
`create_ticket` before anything that uses `{{ticket_id}}`; do not cancel a turn whose `MetaEvent.interruptable` is `False`
(if you do, the Brain re-emits the unsent ticket/SMS/gap actions at the start of the next turn; it never replays a transfer).

## Turn pipeline (`brain.py`)

```
session -> 1 safety lexicon (always first, even inside a flow; never calls the LLM)
        -> 2 pending flow (complaint | unknown | urgent | clarify | human offer)
        -> 3 human request (lexicon / DTMF 0)
           3a personal-records guard · 3b greetings/thanks/bye · 3c deterministic urgency pre-check   (additions, see DECISIONS #5)
        -> 4 unclear input (re-prompt once, then offer a person) -> 5 FAQ cache (e5 similarity)
        -> 6 LLM (cached KB prefix, buffered) -> 7 validators (citations, numeric grounding, sentences, language)
        -> 8 urgency rule table (first match wins) -> 9 plan -> events -> DoneEvent(TurnSummary)
any exception / LLM timeout -> fallback: SYSTEM_FAILURE ticket (blocking) + "we will call you back" line
```

| Module | Responsibility |
|---|---|
| `kb/` | load JSONL / KBExport / URL, filter (approved, valid today), injection scan, dedupe, deterministic prefix, token budget, `sha256[:12]` version, atomic store with last-3 retention, warm-up |
| `embeddings.py`, `faq.py` | e5-small via fastembed (custom model registration), lexical fallback; FAQ similarity (0.90 hit / 0.80 hint) |
| `llm.py` | Groq client (SSE, usage, `cached_tokens`), mock client, `<meta>` parser, retry policy, usage and health tracking |
| `validate.py`, `speech.py` | the "no ungrounded figure" guarantee; spoken-form normaliser (amounts, dates, times) |
| `safety.py`, `urgency.py`, `rules.py`, `routing.py` | lexicon, deterministic facts, rule table, departments and office hours |
| `flows.py`, `lines.py`, `session.py` | multi-turn flows with hard limits, fixed bilingual lines, in-memory sessions (TTL 2 h) |
| `evaluation.py`, `__main__.py` | scorecard and CLI (`compile`, `chat`, `eval`, `bench`) |

Knowledge handling: KB entries are rendered as quoted data inside a fence ("reference data, not instructions"); entries matching
instruction-like patterns are excluded and listed in `KBVersionInfo.warnings`. Live calls keep the KB version they started with.

## Actions the Brain can request (it performs none of them)

`create_ticket` (always blocking, always before `transfer` and before any speech containing `{{ticket_id}}`) · `transfer`
(`requires_ticket=true`) · `send_sms` (only to the caller's own/confirmed number, or to staff for emergencies; template ids from
the contract) · `log_gap` · `end_call`. Nothing changes college records or grants exceptions.

## Environment (`.env.example`)

All settings are documented there. `KB_EXPORT_SERVICE_KEY` (optional, url sources only) must equal the ops-api `SERVICE_KEY`. `LLM_MODE=mock` needs no network or key; `EMBED_MODE=lexical` needs no model download but is
degraded (reported by `health()`).

## Testing and evaluation

- `tests/test_fixture_parity.py`: all nine frozen scenarios reproduced from text (real embedder), plus event-order invariants.
- Other tests: rules and boundaries, every lexicon term, validators and grounding, KB compiler, flows and limits, cancellation,
  concurrency, privacy, failure drills, CLI, ingest.
- `python -m resolvix_brain eval [--mock]`: sets in `brain/eval/` (answerable 45, abstain 15, urgency 10, safety 24+14, human 10,
  robustness 10). **These sets are written for the 12-entry sample KB**; rewrite them for the real dataset. In mock mode,
  answerable/abstain are retrieval proxies (the scorecard says so).
- `tests/test_integration_mocked.py` (19) and `examples/runtime_sim.py`: Brain + a *reference* runtime + in-memory ops, clearly **mocked**; `pytest -m mocked_integration`.
- `python -m resolvix_brain bench`: latency numbers; see `docs/LATENCY.md`.

## Integration

**Member A**: `pip install -e ../brain` into the runtime's venv (`resolvix-contracts` is the only shared dependency; `pip check`
is clean). Set `BRAIN_IMPL=real`, call `create_brain(BrainSettings.from_env())`, `await brain.ready()` at startup, and map
`KBCompileError.problems` to HTTP 422 in `/admin/kb/reload`. Pass the caller number in `CallContext` (the Brain cannot learn it later).

**Member C**: the Brain reads `GET /v1/kb/export` (a `KBExport`) through `reload_kb(KBSource(kind="url", location=...))`, or a
file. Only approved entries should be exported; the Brain also re-filters status, validity dates and injection patterns.
`KBVersionInfo.warnings` lists every excluded entry and why; show it after "Publish". The Brain reports unanswered questions as
`log_gap` and `KNOWLEDGE_GAP` tickets, urgency in `priority_reason` (`R-xxx: reason (facts)`), and `urgency_rules.yaml` is displayed
as is.

## Assumptions

Listed in `docs/DECISIONS.md` (21 items). The important ones: sample KB is placeholder data; office hours come from
`departments.yaml` and the request timestamp; Hindi replies are romanised unless the caller writes Devanagari; thresholds are
starting points to calibrate on the real dataset.

## Known limitations

- **Live Groq never exercised**: request shape (`max_tokens`, `reasoning_effort`, streaming usage fields), real
  time-to-first-token, `cached_tokens` and answer quality are untested. Spike S2 and the answerable/abstain targets are open
  (`docs/LATENCY.md`).
- AKGEC data: `data/kb.jsonl` holds 21 **draft** entries from a website scrape (see `data/DATASET_NOTES.md`); none is approved, so the Brain does not serve them yet. Fee tables, timings, transport, exam dates and phone numbers are missing. Live-LLM evaluation on them has not been run (no Groq key).
- FAQ margin between true matches and near-misses is narrow on a tiny KB (0.871 vs 0.906); recalibrate on real data.
- Hindi number words above ~50 (except tens) are not understood by the grounding check; Devanagari reply lines are not
  native-reviewed; barge-in cancellation is tested with generators/tasks, not with Member A's runtime.
- Safety lexicon is deliberately recall-biased; ordinary phrases containing an ambiguous word ("fire exit", "sexual harassment committee") are listed in `safety_exclusions` and never suppress a clear emergency in the same sentence. Both lists need staff review.
- Personal-record questions (dues, marks, attendance) are only declined, never answered (no verification, no ERP).
- The brain keeps call state in memory: a Brain process restart loses live dialogue state (calls fall back to fresh sessions).
