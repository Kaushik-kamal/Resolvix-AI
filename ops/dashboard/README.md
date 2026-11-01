# Resolvix Ops dashboard

React 18 + Vite + TypeScript + Tailwind CSS 3 + TanStack Query 5 + React Router 6 + Vitest. Staff UI for the ops-api
(live board, tickets, calls, knowledge gaps, KB, rules). Shared building blocks are documented in
[COMPONENTS.md](COMPONENTS.md).

## Setup

```bash
cd ops/dashboard
npm install
cp .env.example .env     # optional; defaults work with the API on port 8100
npm run dev              # http://localhost:5173
```

The API must be running (`uvicorn resolvix_ops.app:app --port 8100` from `ops/api`; seed users: see the ops README,
`admin@demo`, `exam@demo`, `accounts@demo`, `hostel@demo`).

In development the browser only talks to the Vite server. It proxies `/v1` (including the SSE stream) and `/healthz` to
`VITE_PROXY_TARGET`, so the `resolvix_session` cookie is same-origin and no CORS setup is needed.

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server on 5173 (`-- --port 5174` to change) |
| `npm run build` | `tsc --noEmit` then `vite build` into `dist/` |
| `npm run preview` | serve `dist/` on 5173 with the same proxy |
| `npm test` | Vitest, one run (`npm run test:watch` for watch mode) |
| `npm run typecheck` | type check only |
| `npm run gen:types` | regenerate `src/api/types.ts` from `../../contracts/jsonschema/*.json` (read only; never edit the output by hand) |

## Environment (`.env`, see `.env.example`)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_OPS_API_URL` | empty | Base URL of the API for the browser. Empty = same origin through the Vite proxy (recommended). Set it only when the dashboard is hosted on another origin; then the API's `CORS_ORIGINS` must include the dashboard origin and the cookie must be allowed cross-site. |
| `VITE_PROXY_TARGET` | `http://localhost:8100` | Where the dev/preview proxy forwards `/v1` and `/healthz`. Not exposed to the browser. |
| `VITE_RUNTIME_URL` | `http://localhost:8000` | Voice runtime (Member A) for links to the web-call and typed-test pages. |

## Layout

```
src/
  api/          client.ts (typed endpoints, ApiError), extra.ts (hand-written types), queryKeys.ts, types.ts (generated)
  auth/         AuthContext (me/login/logout), RequireAuth (route guard)
  alerts/       P1 alert state: banner list, beep, mute toggle, flash markers
  stream/       EventStreamProvider (one SSE connection), query invalidation per event
  lib/          prioritySort, format (IST, durations, masking), sla, sse (reconnect client), beep, storage
  components/   PriorityBadge, StatusChip, MaskedNumber, Loading/Empty/ErrorState, Drawer, DataTable, ModeBadge, RelativeTime, ...
  layout/       AppLayout (header, nav, connection pill, mute), AlertBanner
  pages/        live/ and login/ (D1); tickets/ calls/ (P1); gaps/ kb/ rules/ (P2)
  test/         setup, mockFetch, renderWithProviders, FakeEventSource
```

## Live board behaviour

- Left: active calls (`GET /v1/calls?active=true`): masked number, language, last turn path/tier (from `call.turn` events;
  empty after a page reload until the next turn), turn count, duration ticking each second.
- Right: P1 / P2 / P3 columns of open and in-progress tickets, newest first, with department, age and an SLA-style timer
  (targets in `src/lib/sla.ts`: P1 15 min, P2 4 h, P3 24 h, P4 72 h). P4 tickets are not shown (a footnote links to the list).
- Counts: calls today since 00:00 IST, answered by AI (`ai_resolved`), escalated (outcome `escalated`, `transferred` or
  `emergency`), P1 open (status open or in progress).
- `alert.p1`: red banner on every page, three-pulse WebAudio beep (no audio files), mute toggle in the header (stored in
  `localStorage` as `resolvix.alertsMuted`), the new ticket card flashes for 8 s. Browsers keep audio locked until the
  first click or key press on the page.
- Connection pill: Live / Connecting / Reconnecting in Ns (try n). Lists refetch after a reconnect.
- Staff sessions: the API scopes everything to their department and sends no `call.*` events, so the counts row shows only
  "P1 open" with a note (call statistics are admin only) and the Active calls panel explains that live calls are visible to
  admins. Admins see the full board.
- Projector toggle (header of the board, saved in `localStorage` as `resolvix.projector`): about 1.4x type for cards, counts and
  the P1 banner, still no horizontal scroll at 1280 px.
- Session expiry: a REST 401, or a stream that keeps failing while `GET /v1/auth/me` answers 401, ends on
  `/login?expired=1` ("Your session expired, please sign in again").
- Reveal (ticket drawer, call detail) is one explicit audited request per click and is dropped from the cache on Hide / close.

## Manual checklist (J5 / J6, run with a seeded API and `dev/simulate_calls.py`)

1. Sign in as `admin@demo`; the live board shows calls, tickets and counts; the header pill says Live and "SMS (mock)".
2. Run the simulator: a P1 ticket makes the red banner appear, the beep plays (after one click on the page), the card
   flashes; mute stops the sound and survives a reload.
3. Stop the API: the pill changes to "Reconnecting in Ns" and keeps trying; start it again: the pill returns to Live and the
   board refetches.
4. J5 (agent P1's pages): open `/tickets?ticket=<id>`, set status to In progress, check the timeline shows an "SMS (mock)"
   event. J6 (agent P2's pages): gap -> Draft KB entry -> approve -> Publish (mock), check the published version.

## Troubleshooting

- Blank board with "Cannot reach the ops API": the proxy target is not running (check `VITE_PROXY_TARGET`).
- Stuck on /login with a correct password: the API session cookie is `SameSite=Lax`, host-only; use the dashboard through
  one hostname (`localhost` everywhere), not a mix of `127.0.0.1` and `localhost`.
- Windows + OneDrive: if `npm install` fails on locked files, close editors watching `node_modules` and retry.
