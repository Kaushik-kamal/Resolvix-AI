# Overnight orchestration plan (Member C)

Status legend: [ ] pending, [~] in progress, [x] done and verified.

## Phase 0 - orchestrator alone
- [x] 0.1 baseline (suite, contracts, guard, coverage)
- [x] 0.2 snapshot ops -> Resolvix_v2/_snapshots/pre-overnight (again before Phase 2 and Phase 4)
- [x] 0.3 async notifier (ThreadPoolExecutor, NOTIFY_ASYNC)
- [x] 0.4 scaffolding: orm, settings, empty gaps/kb routers, gap.created constant, tests/helpers, clock
- [x] 0.5 full suite green, checkpoint

## Phase 1 - parallel agents
- [x] G gaps (ops/api/resolvix_ops/gaps/**, routers/gaps_routes.py, tests/test_gaps.py, tests/test_gap_cluster.py), port 8101
- [x] K knowledge base (kb/**, routers/kb_routes.py, tests/test_kb*.py), port 8102
- [x] S seed + simulator (dev/seed.py, dev/simulate_calls.py, dev/sim_lib/**, tests/test_seed.py, tests/test_simulator.py), port 8103
- [x] D1 dashboard foundation (ops/dashboard/** except src/pages/{tickets,calls,gaps,kb,rules}/**), port 5173

## Phase 2 - integration
- [x] apply integration notes, full suite, smoke gaps+KB, coverage 26/26, guard, checkpoint

## Phase 3 - page agents
- [x] P1 tickets + calls pages (src/pages/tickets/**, src/pages/calls/**), port 5174
- [x] P2 gaps + kb + rules pages (src/pages/gaps/**, kb/**, rules/**), port 5175
- [x] integrate: build, test, typecheck

## Phase 4 - final verification
- [x] dev/e2e_journeys.py (J5, J6)
- [x] clean-machine check
- [x] README + PRD section 10 checklist
- [x] agent R review (ops/docs/REVIEW.md), fix high/medium (resolution table in REVIEW.md)

## Phase 5 - backlog
1. [x] department scoping (API, dashboard staff board, tests)  2. [x] KB draft from resolution  3. [x] dashboard tests  4. [x] projector mode
5. [x] hardening (login rate limit, session expiry UX, 404)  6. [x] embedding clustering (interface + flag; real-API run is wall B1)  7. [x] REVIEW lows

## Ownership map
Orchestrator only: app.py, config.py, db.py, orm.py, deps/auth/errors/audit, sse.py, services/notify.py, sms/**,
routers/{calls,tickets,sse,health,auth,config}_routes.py, tests/helpers/**, tests/conftest.py, test_openapi_coverage.py,
test_auth_matrix.py, dev/smoke.py, dev/e2e_journeys.py, dev/check_openapi_coverage.py, dev/guard_forbidden.py,
ops/docs (except REVIEW.md, integration/*), READMEs, api .env.example, sms_templates.yaml.
Agents: only the paths listed above plus ops/docs/integration/<agent-id>.md.
Ports: orchestrator 8100, G 8101, K 8102, S 8103; dashboard dev 5173 (D1), 5174 (P1), 5175 (P2).
Only the orchestrator runs the full pytest suite and installs Python packages; only D1 runs npm install.
