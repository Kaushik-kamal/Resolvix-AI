# Agent D2: dashboard review fixes (M4, M8 UI, L7 to L12, projector mode)

Scope: `ops/dashboard/**` only. No backend, contract or package.json change. `npm test`: 236 passed (was 199, 19 files);
`npm run build` green.

## What changed

| Item | Change | Where |
|---|---|---|
| M4 | Staff live board: counts row = "P1 open" + note (call statistics are admin only); the all-calls "today" query is not issued for staff; Active calls shows "Live calls are visible to admins ... once they produce a ticket for your department". Admin unchanged. | `pages/live/*`, `auth/AuthContext.tsx` (`useSessionUser`) |
| L7 | `sms_sent` mock = "SMS recorded (mock)" neutral, live = "SMS sent" green, no mode = "SMS recorded (mode unknown)" neutral; failed/suppressed unchanged. | `pages/tickets/TicketTimeline.tsx` |
| L8 | After publish the history is refetched and the mode of the newest row decides mock/live; warning text is the fallback only. | `pages/kb/PublishPanel.tsx` |
| L9 | "Create KB draft from resolution" in the ticket drawer (resolved/closed or a "Resolution:" note; staff + admin) -> `/kb` with router state `kbDraft`. Seed gained `source: "ticket"`, `answerEn`, `sourceTitle`, `ticketId` (gap seeds unchanged). | `pages/tickets/TicketDrawer.tsx`, `ticketLogic.ts`, `pages/kb/draftSeed.ts`, `kbModel.ts`, `KbPage.tsx` |
| L10 | Drawer focus trap (Tab/Shift+Tab cycle, stray focus pulled back, Esc, focus restored); `aria-live="polite"` on the connection pill and the counts row. | `components/Drawer.tsx`, `layout/ConnectionPill.tsx`, `LiveBoardPage.tsx` |
| L11 | After 2 consecutive stream errors the provider probes `GET /v1/auth/me`; 401 stops reconnecting and goes to `/login?expired=1`; REST 401 uses the same URL (not while on /login); login page banner "Your session expired, please sign in again". | `lib/sse.ts` (`onError`), `stream/EventStreamContext.tsx`, `api/client.ts`, `pages/login/LoginPage.tsx` |
| L12 | `useReveal`: one explicit `reveal=true` request per click; SSE/focus/reconnect refetches only touch the masked copy; Hide and unmount `removeQueries` the revealed copy. Used by ticket drawer and call detail. The list functions no longer have a `reveal` parameter (stripped at runtime too). | `hooks/useReveal.ts`, `TicketDrawer.tsx`, `CallDetailView.tsx`, `api/client.ts` |
| M8 UI | Rules page shows already masked numbers unchanged (helpers were idempotent; now tested), index added to list keys (two masked numbers can look identical), 112 stays plain. | `pages/rules/RulesPage.tsx`, tests |
| Backlog | Projector toggle (localStorage `resolvix.projector`), ~1.4x for cards, counts, column titles, P1 banner. Real browser check at 1280 px: scrollWidth == clientWidth, no wide elements (admin + staff). | `lib/projector.ts`, `pages/live/*`, `layout/AlertBanner.tsx` |
| KB backend changes | Import button/panel hidden for staff, 403 explained; 409/403 on save explained in the editor, staff warned when opening an approved entry; import copy now says unflagged lines keep their file status (flagged = draft). | `pages/kb/*` |

## Differences between the instructions and the contract / API

- None in paths, status codes or schemas. `reveal` is a documented query parameter of the detail endpoints; the dashboard now
  never sends it to the list endpoints.
- The contract has no `Ticket.resolution` field: a resolution is only visible as the note `[iso] actor: Resolution: <text>`
  (written by `PATCH /v1/tickets/{id}`). L9 depends on that note format (`extractResolution`); if the backend ever changes the
  prefix, update `RESOLUTION_PREFIX` in `ticketLogic.ts`.
- Instruction said ".. 409 (conflict) for an approved entry"; the coordinator note adds archived. The UI text says "approved or archived".

## Integration requests (backend, not done by me)

1. Staff `GET /v1/calls?active=true` returns only calls already linked to a ticket of their department; there is no stream event
   for them, so the staff Active calls panel refreshes only every 60 s. If wanted, send `call.started`/`call.ended` for calls
   that already have a ticket of the subscriber's department, or add `ticket.created` to the invalidation of the calls list
   (a dashboard-only change that I did not make to keep the staff board cheap).
2. Optional: expose `resolution` (or a structured note kind) on the ticket so the dashboard need not parse the note text.
3. `GET /v1/departments` for staff: the Rules page assumes the masked form `+91•••••0101` (first 3 characters, five bullets,
   last 4). Any other masking style is shown as received.

## Decisions

- The staff check is `role === "staff"` from the cached `qk.me`; an unknown user (no cache) gets the admin layout. The API
  stays the authority; this only avoids misleading numbers.
- The revealed copy lives in the React Query cache under `qk.tickets.detail(id, true)` / `qk.calls.detail(id, true)` with an
  `enabled: false` observer, so `invalidateQueries` (default `refetchType: "active"`) skips it. Its queryFn rejects, so even a
  forced refetch cannot create an audit row.
- Call detail: Reveal adds one extra `GET /v1/calls/{id}?reveal=true` (one more `transcript_viewed` + `number_revealed`
  audit pair) because the endpoint is the only source of the full number; the masked copy keeps serving the turns.
- Stream probe threshold is 2 consecutive errors (`SESSION_PROBE_AFTER_ATTEMPTS`), one probe at a time.
- Expiry redirect is a full page load to `/login?expired=1` (same mechanism as before), so the query cache starts empty.

## WALLS

- None. (A real-browser check of session expiry through a live stream was not possible without expiring the cookie
  server side; it is covered by the fake-EventSource tests.)
