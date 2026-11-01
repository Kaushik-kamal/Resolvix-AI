# Agent G (gaps) - integration notes

## Delivered
- `POST /v1/gaps` (201), `GET /v1/gaps/clusters` (200), `PATCH /v1/gaps/clusters/{cluster_id}` (200).
- Clustering: `resolvix_ops/gaps/cluster.py` (`ClusterStrategy.assign(question, department_guess) -> (key, label)`,
  `KeywordClusterStrategy`, `get_strategy(name)`, `register_strategy(name, cls)`); persistence in `gaps/service.py`.
- Strategy comes from `Settings.gap_cluster_strategy` (`keywords`); an unknown name logs a warning and falls back to keywords.

## Response shapes (the yaml gives none for POST)
- `POST /v1/gaps` -> `201 {"status": "ok", "gap_id": int, "cluster_id": "gc-N", "count": int}`.
- `GET /v1/gaps/clusters` -> `{items: GapCluster[]}`, sorted `count desc, last_seen desc, cluster_id`. Additive `?status=` filter.
- `PATCH` -> the updated `GapCluster`. Body `{status}` is required (an empty body is 422). Audit action `gap_cluster_updated`,
  entity `gap_cluster`, details `{status: {from, to}}`.

## SSE `gap.created` (for ops/docs/SSE_EVENTS.md, which the orchestrator owns)
Emitted once per successful `POST /v1/gaps`, after the commit. Payload:
`{"gap_id": 12, "cluster_id": "gc-3", "label": "Bus Noida", "department_guess": "transport", "count": 7, "ts": "..."}`.
It carries neither the question text nor the call id. Replace the "not emitted yet" paragraph of SSE_EVENTS.md with this.

## Decisions
- Cluster id = `gc-<n>` with n = cluster count + 1 (clusters are never deleted), assigned inside the BEGIN IMMEDIATE transaction.
- Phone-like digit runs (10+ digits, spaces/hyphens/brackets allowed, year lists excepted) are replaced with `•••` before
  clustering, so numbers never end up in a label, an example, the stored `gaps.question` or an SSE payload.
- Single-character tokens are not keywords. Label keywords are in the sorted key order, so the label is stable per key.
- Examples: stripped text, last 5, newest last; a repeated text is moved to the end. Every POST still increments `count`.
- New gaps never change `status` (ignored/answered/needs_document clusters are not reopened).
- Blank `question` (only whitespace) -> 422 (the model alone would accept it).
- `department_guess` is not validated against departments.yaml (the contract does not say it must be a known one).

## Requests for files I do not own
- `ops/docs/SSE_EVENTS.md`: document `gap.created` as above (orchestrator).
- `tests/test_contract_fixtures.py`: move `gap_create` and `gap_cluster` from SKIPPED to EXERCISED (orchestrator, already planned).
  `tests/test_gaps.py` validates both fixtures and posts `gap_create.json`.
- `tests/test_openapi_coverage.py` currently fails on two KB routes (`POST /v1/kb/entries/{entry_id}/status`,
  `GET /v1/kb/publishes`) that the KB agent added; no gap route is flagged.

## WALLS
None.
