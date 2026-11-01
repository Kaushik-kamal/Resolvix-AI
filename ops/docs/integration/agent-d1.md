# Agent D1 (dashboard foundation): integration requests and notes

## Requests for files D1 does not own

1. **ops-api, additive field on `GET /v1/calls` items: `last_turn`** (owner: orchestrator / calls router).
   The live board shows "last turn path/tier" for each active call. The REST list has no such field, so the dashboard only
   learns it from `call.turn` SSE events: after a page reload (or when the tab was closed during the call) an active call
   shows "last turn: waiting for next" until the next turn. Requested change in `routers/calls_routes.py::call_to_dict`
   (list only, not the contract schema): add `"last_turn": {"path": ..., "tier": ..., "priority": ..., "turn_index": ...}`
   taken from the highest `turn_index` row, or `null`. The dashboard will use it as soon as it exists (no D1 change
   needed beyond reading `call.last_turn`; tell D1/P1 and it is a three-line change in `pages/live/ActiveCalls.tsx`).
   Workaround today: SSE-fed in-memory cache (`lastTurns`). Fetching `GET /v1/calls/{id}` per active call was rejected
   because every detail GET writes a `transcript_viewed` audit row.
2. **ops-api, `/v1/kb/publishes` response shape** (owner: KB agent). D1 typed it provisionally as
   `{items: [{id?, kb_version, info?: KBVersionInfo, mode?, actor?, at}]}` (matches the `KBPublish` ORM columns). If the
   route returns something else, P2 should adjust `KBPublishRecord` in `src/api/extra.ts` through the orchestrator
   (D1 owns that file; frozen dependency rules do not apply to it).
3. **ops-api, `GET /v1/kb/entries` item shape** (owner: KB agent). Typed as `KBEntry & {flagged?: boolean, updated_at?, updated_by?}`.
4. **ops-api, `gap.created` payload** (owner: gaps agent). Typed loosely (`cluster_id?, label?, department?, count?`);
   the dashboard only invalidates `qk.gaps.all` on it.

No change is needed in any forbidden path. The Vite proxy needs no CORS change in the API.

## Page-agent contracts D1 relies on
- P1: `/tickets?ticket=<ticket_id>` opens the ticket drawer; `/calls?call=<call_id>` opens the call detail. The live board
  cards and the P1 banner link to them.
- Placeholders: `src/pages/{tickets,calls,gaps,kb,rules}/index.tsx` with default exports `TicketsPage`, `CallsPage`,
  `GapsPage`, `KbPage`, `RulesPage`. The router lazy-imports `./pages/<name>/index` and mounts at `<name>/*`.

## WALLS
None.

## Decisions (D1)
- Tailwind 3.4 (not 4) with PostCSS; TypeScript 7 (`tsc --noEmit` in `npm run build`); Vite 8, Vitest 5, React 18.3.
- Session cookie auth only; the dashboard never sends `X-Service-Key`.
- `Escalated` on the counts row = call outcome in {escalated, transferred, emergency}; `P1 open` = P1 with status open or
  in_progress; `answered by AI` = `ai_resolved === true`; `calls today` = calls with `started_at` since 00:00 IST.
- SLA targets (display only): P1 15 min, P2 4 h, P3 24 h, P4 72 h; amber at 75 %, red after the target.
- SSE: `call.turn` does not invalidate call details (each detail GET is an audited transcript view).
- The Vite proxy destroys the browser SSE socket when the API dies mid-stream (otherwise EventSource never notices).
- `ErrorEnvelope.code` has no "forbidden": HTTP 403 arrives as `unauthorized`; UI distinguishes by `ApiError.status`.
