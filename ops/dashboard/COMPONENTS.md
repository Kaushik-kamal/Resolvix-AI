# Dashboard foundation: shared API for page agents

Everything below is built and tested by D1. Page agents (P1: tickets, calls; P2: gaps, kb, rules) import it and never
edit `package.json`, `src/api/types.ts`, `src/components/**`, `src/lib/**`, the layout or the router.
Import with the `@/` alias (`@/components`, `@/api`, `@/lib/format`) or relative paths; both work in Vite, tsc and Vitest.

Run: `npm run dev` (5173; page agents may use `npm run dev -- --port 5174` / `5175`), `npm test`, `npm run build`.
Point the dev server at your own API with `VITE_PROXY_TARGET=http://localhost:8104 npm run dev -- --port 5174`.

## 1. Add or fill in a page

Your folder already contains `index.tsx` with a placeholder. Keep the default export; replace the body.

```tsx
// src/pages/tickets/index.tsx
import { useQuery } from "@tanstack/react-query";
import { api, qk } from "@/api";
import { DataTable, PageHeader, Panel, PriorityBadge } from "@/components";

export default function TicketsPage() {
  const q = useQuery({ queryKey: qk.tickets.list({ limit: 200 }), queryFn: ({ signal }) => api.listTickets({ limit: 200 }, signal) });
  return (
    <>
      <PageHeader title="Tickets" />
      <Panel flush>
        <DataTable columns={[{ key: "id", header: "Ticket", cell: (t) => t.ticket_id }]}
                   rows={q.data?.items} rowKey={(t) => t.ticket_id}
                   isLoading={q.isPending} error={q.error} onRetry={() => void q.refetch()} />
      </Panel>
    </>
  );
}
```

- The router mounts pages at `tickets/*`, `calls/*`, `gaps/*`, `kb/*`, `rules/*` via `lazy(() => import("./pages/<name>/index"))`.
  Use `useSearchParams()` for deep links, or a nested `<Routes>` / `useParams()["*"]` for sub-paths.
- You may add any other files inside your own folder (components, hooks, tests). Do not add files elsewhere in `src/`.
- Pages render inside `AppLayout` (header, nav, P1 banner, SSE connection, auth guard). Never mount your own
  `QueryClientProvider`, router or `EventSource`.

### Deep-link conventions (other pages link to yours)
| Link | Owner | Behaviour expected |
|---|---|---|
| `/tickets?ticket=EX-1001` | P1 | open the ticket drawer for that id (live board cards and the P1 banner use it) |
| `/calls?call=<call_id>` | P1 | open the call detail |
| `/kb?draftFromGap=<cluster_id>` | P2 (gaps -> kb) | implemented: opens the KB editor prefilled from that cluster (the gaps page itself passes router state `kbDraft`) |

## 2. API client (`@/api`)

```ts
import { api, ApiError, isApiError, qk, type TicketRow } from "@/api";
const { items } = await api.listTickets({ status: "open", priority: "P1", limit: 50 });
```

All functions return the parsed JSON and throw `ApiError` (`code`, `message`, `status`, `retryable`, `details`) on any
non-2xx response or network failure (`code: "network_error"`, `status: 0`). The last argument of the GET functions is an
optional `AbortSignal`; pass TanStack's `signal`.

| Area | Functions |
|---|---|
| health/auth | `healthz()`, `login(email, password)`, `me()`, `logout()` |
| calls | `listCalls({from, outcome, active, limit})`, `getCall(id, {reveal})`, `startCall`, `appendTurn`, `endCall` |
| tickets | `listTickets({status, department, priority, caller_number, limit})`, `getTicket(id, {reveal})`, `createTicket`, `patchTicket(id, {status, assignee, note, resolution})`, `listTicketEvents(id)`, `addTicketEvent(id, event)` |
| sms | `sendSms(SmsRequest)` |
| gaps | `createGap`, `listGapClusters()`, `patchGapCluster(id, status)` |
| kb | `listKbEntries({status})`, `saveKbEntry(KBEntry)`, `importKb(file)`, `setKbEntryStatus(id, status)`, `exportKb()`, `publishKb()`, `listKbPublishes()` |
| config | `getDepartments()`, `getUrgencyRules()` |
| stream | `streamUrl()` (used by the SSE hook; you will not need it) |

Rules that matter:
- **Numbers are masked** unless you pass `reveal: true`, which the API accepts ONLY on the detail endpoints
  (`getTicket`, `getCall`); the list functions have no `reveal` parameter and strip it (the API answers 422 for lists).
  Reveal is audited server-side (`number_revealed` per entity), so only do it on an explicit user action, never on page
  load, and never from a refetch: use `useReveal` (below). PATCH and SSE never reveal.
- **`getCall()` is audited** (`transcript_viewed` on every request). Fetch it only when the user opens the call, and do
  not poll it. SSE `call.turn` deliberately does not invalidate call details.
- `patchTicket` with a real status change makes the API send one status SMS (mock/live) and add `sms_*` events; refetch
  `qk.tickets.events(id)` afterwards (the `ticket.updated` SSE event does it for you).
- `publishKb()` is admin only: a staff user gets HTTP 403 with `code: "unauthorized"` (the contract has no "forbidden";
  check `error.status === 403`). An unreachable voice runtime gives `502 upstream_error`.
- A 401 on any data call redirects to `/login?expired=1` automatically (not while on `/login`); the login page then shows
  "Your session expired, please sign in again". `me()` and `login()` do not redirect. `handleUnauthorized()` runs the same handler
  (the SSE session probe uses it); `setUnauthorizedHandler()` replaces it in tests.
- KB: staff can save drafts but get 409 when the entry is approved or archived; `importKb` and `publishKb` are admin only (403).
  `getDepartments()` returns masked `sms_alert_numbers` for non-admin sessions.
- Request bodies are the generated contract types (`TicketPatch`, `KBEntry`, ...). `TicketRow = Required<Ticket>` is the
  shape the API actually returns (all fields present); `TicketEventRow`, `CallSummary`, `CallDetail`, `KBEntriesResponse`
  (items + `flagged_ids` + `meta`), `KBSaveResult`, `GapCreated`, `KBPublishRecord`, `UrgencyRulesDoc`, `Health`, `Me` are in `src/api/extra.ts`.
- `src/api/types.ts` is generated: `npm run gen:types` (reads `../../contracts/jsonschema/*.json`, never writes there).

### Query keys (`qk`, `src/api/queryKeys.ts`)
Always build keys through `qk`, so SSE invalidation keeps matching. Keys are hierarchical.

| Key | Used for |
|---|---|
| `qk.me`, `qk.health` | session, `/healthz` |
| `qk.calls.list(params)` / `qk.calls.lists()` | `GET /v1/calls` (prefix `["calls","list"]`) |
| `qk.calls.detail(id, reveal)` / `qk.calls.detailAny(id)` | `GET /v1/calls/{id}` |
| `qk.tickets.list(params)` / `qk.tickets.lists()` | `GET /v1/tickets` |
| `qk.tickets.detail(id, reveal)` / `qk.tickets.detailAny(id)` | `GET /v1/tickets/{id}` |
| `qk.tickets.events(id)` | `GET /v1/tickets/{id}/events` |
| `qk.gaps.clusters` (prefix `qk.gaps.all`) | `GET /v1/gaps/clusters` |
| `qk.kb.entries(params)` (prefix `qk.kb.entriesAny`), `qk.kb.publishes` | KB list, publish history |
| `qk.config.departments`, `qk.config.urgencyRules` | config (static: use `staleTime: Infinity`) |

After a mutation you do: `queryClient.invalidateQueries({ queryKey: qk.tickets.lists() })` (or the detail key).

## 3. Live updates (SSE)

`AppLayout` mounts `EventStreamProvider` once: one `EventSource("/v1/stream", {withCredentials:true})`, reconnect with
exponential backoff (1 s, 2 s, 4 s ... 30 s cap, reset after a successful open), status shown in the header pill. Events
are not replayed after a reconnect, so every reconnect invalidates calls, tickets and gaps.

Query invalidation per event (`src/stream/invalidation.ts`, tested):

| Event | Invalidates |
|---|---|
| `call.started`, `call.turn` | `qk.calls.lists()` (never call details: those GETs are audited) |
| `call.ended` | `qk.calls.lists()`, `qk.calls.detailAny(call_id)` |
| `ticket.created`, `alert.p1` | `qk.tickets.lists()` |
| `ticket.updated` | `qk.tickets.lists()`, `qk.tickets.detailAny(id)`, `qk.tickets.events(id)` |
| `gap.created` | `qk.gaps.all` |
| reconnect | `qk.calls.all`, `qk.tickets.all`, `qk.gaps.all` |

Hooks (`@/stream/EventStreamContext`):
- `useEventStream()` -> `{ state: {status, attempt, retryInMs, lastActivityAt}, subscribe(handler), lastTurns }`
  (`lastTurns[call_id]` = latest `call.turn` payload since page load).
- Session expiry (L11): after `SESSION_PROBE_AFTER_ATTEMPTS` (2) consecutive stream errors the provider probes `GET /v1/auth/me`.
  A 401 closes the stream for good (no endless reconnect) and calls `handleUnauthorized()` -> `/login?expired=1`; any other
  answer (200, network error, 5xx) keeps reconnecting. `createEventStreamClient` has a new `onError(attempt)` option for this.
- `useStreamEvent("ticket.created", (data) => ...)` runs a handler for one event name (payloads are typed by
  `StreamEventMap` in `@/api`). Use it for toasts or local state; plain list refresh needs nothing, the invalidation does it.
- `useAlerts()` (`@/alerts/AlertContext`) -> `{ alerts, dismiss, dismissAll, muted, toggleMuted, isFlashing(ticketId) }`.
  P1 handling (banner in `AppLayout`, WebAudio beep, mute persisted in `localStorage` key `resolvix.alertsMuted`,
  8 s flash of the new ticket) is already done; call `isFlashing(id)` if you want your table row to flash too.
- The reconnect logic itself is `createEventStreamClient()` in `src/lib/sse.ts` (framework-free; takes an
  `EventSourceImpl`, so tests inject `FakeEventSource`).

## 4. Components (`@/components`)

| Component | Props | Notes |
|---|---|---|
| `PriorityBadge` | `priority: "P1".."P4" \| null`, `size?: "sm" \| "md"`, `className?` | colours P1 #B5603F, P2 #A97B49, P3 #6F8592, P4 #9CA9B1; unknown shows a grey `?` |
| `StatusChip` | `status: string`, `label?`, `tone?: "neutral"\|"info"\|"good"\|"warn"\|"bad"`, `className?` | colour from the status word: ticket (open, in_progress, resolved, closed), call outcome, KB (draft, approved, archived), gap (new, needs_document, answered, ignored), SMS (queued, sent, delivered, failed, suppressed) |
| `MaskedNumber` | `value`, `revealed?`, `onToggleReveal?`, `className?` | monospace; an unmasked value is re-masked on screen unless `revealed`; an already masked value ("+91•••••0101", what non-admin sessions get from the API) is shown unchanged, never masked twice (`maskNumber` / `displayNumber` are idempotent); the eye button only appears with `onToggleReveal` |
| `LoadingState` | `label?`, `variant?: "spinner"\|"skeleton"`, `rows?`, `className?` | `role="status"` |
| `EmptyState` | `title`, `hint?`, `icon?`, `action?`, `className?` | |
| `ErrorState` | `error: unknown`, `title?`, `onRetry?`, `className?` | shows `message (code, HTTP status)` for `ApiError`; `role="alert"` |
| `Drawer` | `open`, `onClose`, `title`, `subtitle?`, `headerExtra?`, `footer?`, `size?: "md"\|"lg"\|"xl"`, `children` | Esc / backdrop / X close, scroll lock, focus restore to the opener, focus trap (Tab / Shift+Tab cycle inside; focus that lands outside is pulled back); render always, drive with `open` |
| `DataTable<T>` | `columns: Column<T>[]`, `rows \| undefined`, `rowKey`, `onRowClick?`, `isLoading?`, `error?`, `onRetry?`, `emptyTitle?`, `emptyHint?`, `emptyAction?`, `selectedKey?`, `rowClassName?`, `initialSort?`, `caption?` | `Column<T> = {key, header, cell(row), sortValue?(row), align?, width?, className?}`; header click sorts columns that have `sortValue`; built-in loading (first load only), error and empty states; rows are keyboard-activatable |
| `ModeBadge` | `mode: "mock"\|"live"`, `prefix?` (default "SMS") | "SMS (mock)" amber vs "SMS (live)" green; use for SMS events and results |
| `RelativeTime` | `value` (ISO), `tickMs?` (30000) | `<time>` with "5m ago"; hover title is the IST time |
| `PageHeader` | `title`, `subtitle?`, `actions?` | |
| `Panel` | `title?`, `actions?`, `flush?`, `className?` | white card; `flush` removes padding (tables) |
| `Button` | `variant?: "primary"\|"secondary"\|"danger"\|"ghost"`, `size?: "sm"\|"md"` + button props | `type="button"` by default |

CSS helper classes (Tailwind components, `src/index.css`): `.card`, `.btn .btn-primary|secondary|danger|ghost .btn-sm`,
`.input` (also for `select` and `textarea`), `.label`, `.th`, `.td`. Tailwind tokens: `bg-header` (#5E4330), `bg-bg`
(#F4EFEA), `text-ink`, `text-ink-soft`, `text-ink-faint`, `border-line`, `bg-surface`, `bg-p1..p4`,
`text-accent` (#7A5A40), `accent-sand` (#CBA982), `accent-amber` (#A97B49), `accent-slate` (#6F8592), `accent-graphite` (#525A63).
Icons: `lucide-react`. Class merging: `clsx`.

## 5. Helpers (`@/lib/*`)

| Module | Exports |
|---|---|
| `prioritySort` | `prioritySort(items)` (P1->P4, then newest `created_at` first; new array, stable), `comparePriority`, `priorityRank`, `groupByPriority`, `PRIORITIES` |
| `format` | `formatDateTime` ("31 Oct 2026, 15:45 IST"), `formatDateTimeSeconds`, `formatTime(v, seconds?)`, `formatDate`, `formatDuration(seconds)` ("3m 05s"), `secondsBetween(start, end?)`, `formatRelative(v, now?)`, `startOfTodayIST()`, `istDateKey`, `parseApiDate`, `maskNumber`, `isMasked`, `displayNumber(value, revealed?)`, `humanize("exam_cell")`, `formatCount`. All dates render in Asia/Kolkata whatever the browser timezone. |
| `sla` | `SLA_TARGET_MINUTES` (P1 15, P2 240, P3 1440, P4 4320; edit here), `SLA_WARN_RATIO` (0.75), `slaFor(priority, elapsedSeconds)` |
| `storage` | `readStorage`, `writeStorage`, `readMuted`, `writeMuted` (all try/catch safe) |
| `projector` | `useProjectorMode()` -> `[on, set, toggle]` (localStorage key `resolvix.projector`, try/catch safe, shared by the live board and the P1 banner), `PROJECTOR_CLASSES` (the ~1.4x class names), `readProjector`, `writeProjector` |
| `beep` | `playAlertBeep()`, `primeAudio()` |
| hooks `@/hooks/useReveal` | `useReveal(queryKey, fetcher)` -> `{revealed, data, pending, error, toggle, hide}`: the explicit, one-shot `reveal=true` fetch (L12). The cached copy is `enabled: false`, so SSE invalidation, window focus and reconnects never re-request it (no repeated `number_revealed` audit rows); `hide()` and unmount call `removeQueries`, so the full numbers leave the React Query cache. Used by the ticket drawer and the call detail. |
| hooks `@/auth/AuthContext` | `useSessionUser()`: the cached `Me` (null while unknown) without needing an `AuthProvider`; set it in tests with `queryClient.setQueryData(qk.me, {...})`. |
| hooks `@/hooks/useNow` | `useNow(intervalMs)`: epoch ms that re-renders every interval; all users of one interval share a single timer |

## 5b. Behaviours added after the review (D2)

- **Staff live board (M4)**: for `role === "staff"` the counts row shows only "P1 open" (their department) plus a note that call
  statistics are admin only; `useLiveBoardData` does not even issue the "calls today" query. The Active calls panel shows
  "Live calls are visible to admins ... calls appear here once they produce a ticket for your department" when empty (staff get no
  `call.*` events; the scoped list refreshes every 60 s). Admin behaviour is unchanged.
- **Projector mode**: a "Projector" toggle in the live board header (persisted, see `projector` above) makes ticket cards, column
  titles, counts and the P1 banner about 1.4x; columns and cards use `min-w-0` and the board grid is `minmax(0,1fr)`, so nothing
  overflows horizontally at 1280 px (checked in a real browser: scrollWidth equals clientWidth).
- **Ticket timeline (L7)**: `sms_sent` with mode `mock` reads "SMS recorded (mock)" in a neutral tone, `live` stays "SMS sent" (green),
  no mode reads "SMS recorded (mode unknown)"; `sms_failed` / `sms_suppressed` unchanged (`titleFor`, `toneFor` in `TicketTimeline`).
- **Publish mode (L8)**: after `publishKb()` the KB page refetches `/v1/kb/publishes` and takes mock/live from the newest row
  (`newestPublishMode`); the "mock publish" warning text is only the fallback when the history cannot be read.
- **Create KB draft from resolution (L9)**: ticket drawer button (shown for resolved/closed tickets or when a "Resolution: ..." note
  exists; staff and admin) -> `navigate("/kb", { state: { kbDraft: KbDraftSeed } })`. `KbDraftSeed` (`pages/kb/draftSeed.ts`) gained
  `source: "gap" | "ticket"` and optional `answerEn`, `sourceTitle`, `ticketId` (gap seeds are unchanged); `buildTicketDraftSeed(ticket,
  resolution)` builds it, `extractResolution(notes)` (`ticketLogic`) strips the "[iso] actor: Resolution:" prefix.
- **KB writes**: the Import JSONL button and panel are hidden for staff (import is admin only; a 403 is also explained). Import keeps
  the status of each unflagged line, flagged lines become drafts. A 409 on save (staff vs an approved/archived entry) and a 403 are
  explained in the editor, which also warns staff before they try to save over an approved entry.

## 6. Tests

Vitest + jsdom + Testing Library (`npm test`; setup in `src/test/setup.ts`, globals on, no real network ever).
Helpers in `src/test/`:
- `mockFetch({ "GET /v1/tickets": (url) => ({ items: [...] }), "PATCH /v1/tickets/EX-1001": ... })` stubs global `fetch`;
  unrouted requests throw. Values are returned as JSON 200; return `errorResponse(500, "internal", "msg")` for errors.
  Call `vi.unstubAllGlobals()` in `afterEach`.
- `renderWithProviders(ui, { route: "/tickets?ticket=EX-1001", withStream: true })` wraps `QueryClientProvider` (no retries),
  `MemoryRouter` and optionally the stream/alert providers on a `FakeEventSource`.
- `FakeEventSource.last().open() / .emit("alert.p1", payload) / .fail()` to drive the live stream; call
  `FakeEventSource.reset()` in `beforeEach`.
- Name tests `*.test.ts(x)` next to your code (inside your page folder). Wrap `emit()` in `act(() => ...)`.
- Reveal, staff board, projector, drawer focus, session expiry and KB-publish examples: `pages/tickets/TicketDrawer.features.test.tsx`,
  `pages/live/LiveBoard.staffProjector.test.tsx`, `components/Drawer.test.tsx`, `stream/sessionExpiry.test.tsx`, `pages/kb/KbPage.backend.test.tsx`.
- `src/pages/live/LiveBoardPage.test.tsx` is a full example (queries, SSE events, banner, beep, error and empty states).

## 7. Do not
- Do not add npm dependencies (everything is installed: react-query, react-router, clsx, date-fns, lucide-react, msw,
  Testing Library, user-event, jest-dom, jsdom). Need something else? Write it to `ops/docs/integration/<your-id>.md`.
- Do not hand-edit `src/api/types.ts`; do not reveal numbers or fetch call details on load, and never pass `reveal` to a list endpoint; do not create your own SSE connection.
