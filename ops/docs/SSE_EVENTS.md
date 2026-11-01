# GET /v1/stream - event reference

Server-Sent Events for the dashboard. Auth: session cookie `resolvix_session` (browser `EventSource` with
`withCredentials: true`) or `X-Service-Key`. Without credentials the endpoint answers `401` with an ErrorEnvelope.

Wire format: `event: <name>` + `data: <one-line JSON>` + blank line. Comment lines (start with `:`) are not events:
`: connected` is sent once on connect, `: ping - <time>` every 15 s as keep-alive. Ignore comments.

Rules that hold for every event:

- `ts` is present: UTC ISO-8601 with offset, e.g. `2026-10-31T10:15:00.123456+00:00`. It is the publish time.
- Phone numbers are always masked (`+91•••••0002`: first 3 chars, five bullets, last 4; `•••` if shorter than 8
  chars; `null` stays `null`). The stream never carries a full number; use `?reveal=true` on the REST endpoints.
- Events are sent only after the database commit succeeded. Duplicate requests (same call_id, same
  (call_id, turn_index), same ticket idempotency_key, second call end) emit nothing.
- Delivery is best effort: each subscriber has a 100-event queue; when it is full the oldest event is dropped. After a
  reconnect, re-fetch state with `GET /v1/calls?active=true` and `GET /v1/tickets` instead of relying on replay.
- All other timestamps inside payloads are ISO-8601 with `+00:00` offset.

## call.started
Emitted by `POST /v1/calls` (first registration only).
```json
{"call_id": "call-urgent-exam", "channel": "pstn", "caller_number": "+91•••••0002",
 "started_at": "2026-10-23T04:45:00+00:00", "kb_version": "a1b2c3d4e5f6", "lang": "hinglish", "ts": "..."}
```

## call.turn
Emitted by `POST /v1/calls/{id}/turns` (first write of a turn_index only; turns after call end still emit).
`tier` and `priority` may be `null`. `turns_count` is the call's turn count after this turn.
```json
{"call_id": "call-urgent-exam", "turn_index": 2, "path": "escalation", "tier": "escalate",
 "lang": "hinglish", "priority": "P1", "turns_count": 3, "ts": "..."}
```

## call.ended
Emitted by `POST /v1/calls/{id}/end` (first end only).
```json
{"call_id": "call-urgent-exam", "ended_at": "2026-10-23T04:47:00+00:00", "outcome": "transferred",
 "ai_resolved": false, "turns_count": 3, "ts": "..."}
```

## ticket.created
Emitted by `POST /v1/tickets` when a ticket is actually created (201). `priority` is `P1`..`P4`; `status` is `open`.
```json
{"ticket_id": "EX-1001", "call_id": "call-urgent-exam", "type": "URGENT", "priority": "P1",
 "priority_reason": "R-EXAM-60: exam in 15 min, caller cannot find room", "department": "exam_cell",
 "status": "open", "summary": "Student cannot find exam room; paper starts in 15 minutes.",
 "caller_number": "+91•••••0002", "callback_number": null, "callback_requested": false,
 "created_at": "2026-10-23T04:45:00+00:00", "ts": "..."}
```

## alert.p1
Emitted right after `ticket.created`, only when `priority == "P1"`. Show it as a banner / sound. Same ticket, same ids.
```json
{"ticket_id": "EX-1001", "call_id": "call-urgent-exam", "type": "URGENT", "department": "exam_cell",
 "priority": "P1", "priority_reason": "R-EXAM-60: exam in 15 min, caller cannot find room",
 "summary": "Student cannot find exam room; paper starts in 15 minutes.",
 "caller_number": "+91•••••0002", "callback_number": null, "created_at": "2026-10-23T04:45:00+00:00", "ts": "..."}
```

## ticket.updated
Emitted by every `PATCH /v1/tickets/{id}` (also when the patch changed nothing but the audit trail). It carries the
fields a board needs to move or re-render a card; fetch `GET /v1/tickets/{id}` for notes.
```json
{"ticket_id": "EX-1001", "status": "in_progress", "assignee": "exam@demo", "priority": "P1",
 "department": "exam_cell", "updated_at": "2026-10-23T05:00:00+00:00", "ts": "..."}
```

## gap.created
Emitted by `POST /v1/gaps` after commit, once per stored gap. `count` is the cluster size after this gap. It carries no
question text, call id or phone number; fetch `GET /v1/gaps/clusters` for the details.
```json
{"gap_id": 12, "cluster_id": "gc-3", "label": "Bus Route", "department_guess": "transport", "count": 3, "ts": "..."}
```

## Browser example
```js
const es = new EventSource(`${API}/v1/stream`, { withCredentials: true });
es.addEventListener("ticket.created", (e) => addCard(JSON.parse(e.data)));
es.addEventListener("alert.p1", (e) => showBanner(JSON.parse(e.data)));
es.onerror = () => { /* EventSource reconnects by itself; refetch lists once it is open again */ };
```
