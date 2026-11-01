# Agent P1 (tickets + calls pages): integration requests and notes

## Requests for files P1 does not own
None are blocking. Optional, for the orchestrator:

1. **PRD section 6 lists "Create KB draft from resolution" (P1 tickets) in the ticket drawer; it was not in the P1 spec and
   is not built.** If wanted: a link in the drawer to `/kb?draftFromTicket=<ticket_id>` (P2's KB page would prefill a draft
   from `ticket.summary` + the "Resolution: ..." note). Needs a P2 decision on the query parameter.
2. **Assignee cannot be cleared with `null`** (the API treats `assignee: null` as "no change"). The drawer sends
   `assignee: ""` to unassign; the API stores an empty string and the dashboard treats it as "Unassigned". An explicit
   clear semantic in `TicketPatch` (contract) would be cleaner; the current behaviour is documented here only.
3. **`GET /v1/calls` has no filter by `call_id` on tickets** (and `GET /v1/tickets` has no `call_id` filter), so the call
   detail does not list "tickets of this call". The ticket drawer links to the call (`/calls?call=<id>`) instead.
4. The simulator stores only the final turn of some calls (e.g. `turns_count 3`, one stored turn with `turn_index 2`); the
   turns table shows exactly what is stored.

## Contract differences found (dashboard vs contracts/openapi/ops-api.yaml)
- `GET /v1/calls`: the dashboard also sends the additive `active=true` (not in the OpenAPI) and reads the additive
  `last_turn`. `GET /v1/calls/{id}` and `GET /v1/tickets[/{id}]` receive the additive `reveal=true` on the explicit Reveal
  click only. All other behaviour follows the contract (`PATCH` body is exactly `TicketPatch`, ticket events kinds are the
  contract enum, status values `open|in_progress|resolved|closed`).
- The shared client sends `reveal=false` explicitly on detail calls (harmless; the API default is false).
- `TicketPatch.resolution` has no Ticket field: the API stores it as a note "Resolution: ...". The drawer shows it in the
  notes list and the timeline (one `note_added` event) accordingly.

## WALLS
None.

## Decisions (P1)
- Filters status/department/priority are sent to the API (`GET /v1/tickets?...`) and are kept in the URL
  (`/tickets?status=open&priority=P1`); search is client-side over summary, ticket id and department and is local state.
  Filtering is repeated on the client so cached and SSE-refreshed lists stay consistent. Limit 500.
- Drawer: opening pushes one history entry (`?ticket=<id>`, Back closes it); closing and filter changes replace the entry.
  The drawer is mounted only while open, so revealed numbers are discarded on close (reveal state is local).
- Reveal: a labelled button (not the eye icon) toggles one `reveal=true` refetch for both numbers; Hide returns to the
  cached masked variant (no new request). The revealed variant is not refetched on window focus. The "revealed, access
  recorded in the audit log" note appears only once the revealed response has arrived.
- Status change needs an explicit "Apply status" click (a change can trigger a caller SMS). The resolution textarea is shown
  for `resolved` and `closed`. After a status change on a ticket that has `call_id` and a (masked) `callback_number` an inline
  hint says the caller may receive a status SMS. Notes, assignee and status each send their own PATCH with only the fields
  that changed. Every PATCH settles with invalidation of ticket lists, the ticket detail variants and the ticket events.
- Assignee is free text with suggestions (assignees seen in the list plus the signed-in user read from the cached
  `qk.me`, never fetched) and an "Assign to me" shortcut.
- Transcript is behind a "Show transcript" button and loads `getCall` only on that click (audited by the API); it is not
  refetched on focus or reconnect. The call detail page behaves the same: one audited GET per open, a Refresh button for
  running calls (SSE `call.turn` deliberately does not touch call details).
- Calls page: the detail replaces the list (full width for the 10-column turns table; no list query while a call is open);
  URL `/calls?call=<id>`, list filters `outcome` and `active=true` are URL params.
- Phone-like values inside ticket event payloads are masked before display (defence in depth).
- Verified manually against a seeded API (own DB, port 8105) with the simulator: list, drawer, reveal, transcript, status
  PATCH with resolution, call list and detail rendered real data; no horizontal page overflow at 1280 px. The temporary
  database and processes were removed afterwards. No screenshot could be captured (the pane screenshot timed out), the
  check was made through the DOM.
