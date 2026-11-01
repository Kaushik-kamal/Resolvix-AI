# Agent S: seed and simulator (integration notes)

## Files
- `api/dev/seed.py`: `seed(settings=None, session_factory=None, *, include_users=True) -> SeedResult`; CLI
  `python -X utf8 dev/seed.py [--database-url ...]`.
- `api/dev/simulate_calls.py` (CLI) and `api/dev/sim_lib/` (`run_simulation(client, speed, only, run_id, ...)`).
- Tests: `api/tests/test_seed.py`, `api/tests/test_simulator.py`.

## Behaviour worth knowing
- Seed inserts only missing KB ids (13 rows: 12 approved from `sample_kb.jsonl`, draft `BUS-001` for transport) and never
  touches an existing row, whatever its status. Users are seeded by the existing `seed_users_if_needed` (empty table only).
  Rows use `updated_by="seed"`, `flagged=False`, `body_json = KBEntry.model_dump(mode="json")`.
- Simulator: one call per fixture, ids `sim-<scenario>-<run id>`, idempotency keys re-suffixed with the run id. Outcome is
  derived: transfer -> `transferred` (`emergency` for EMERGENCY / safety), SYSTEM_FAILURE or fallback path -> `failed`,
  ticket without transfer -> `escalated`, otherwise `answered` (`ai_resolved` only for tier `confident`).
- Transfers are reported as `transfer_attempted` then `transfer_connected` (or `transfer_failed`, reason `no_answer_20s`,
  with `--fail-transfers`); payloads are strings and carry `mode: simulated`.
- Safety: if `GET /healthz` reports `notify_mode: live`, every SMS step is skipped. The fixture numbers must never be texted.
- A 404/405 from `POST /v1/gaps` is logged and skipped. The gap endpoint exists now, so a full run posts one gap.

## Requests to the orchestrator
None. (Optional: add `dev/seed.py` to the README run instructions; add a `make demo`-style note: seed, start uvicorn, then
`simulate_calls.py --speed 5`.)

## WALLS
None.
