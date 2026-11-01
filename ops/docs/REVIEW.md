# Independent review of R/ops (Member C): Ops API, SMS service, Staff Dashboard

Reviewer: Agent R (read-only). Date of run: 2026-10-31/11-01. Scope: `ops/**` against `MEMBER_C_PRD.md` sections 4-11, the frozen
contract (`ops-api.yaml`, `resolvix_contracts`, fixtures), `DECISIONS.md`, `SSE_EVENTS.md`, `ops/README.md`.
Nothing was fixed. Probe scripts lived in the session scratchpad (not in the repo); throwaway databases only
(`data/review_test.db*` and `data/e2e_*.db` were removed; `ops/api/data/` is empty; the dev `resolvix.db` was never touched).
Side effect worth knowing: `npm run build` rewrote `ops/dashboard/dist/` (build output).

## 1. Summary of what was run

| Check | Command | Result |
|---|---|---|
| Ops API suite (first run) | `pytest -q` in `ops/api` | 451 passed, 2 skipped, 129 s |
| Ops API suite (re-run after `gaps/embedding.py` + `tests/test_gap_embedding.py` appeared) | same 457 passed, 2 skipped, 128 s (+6 embedding tests; the README figure 451/2 is now stale) |
| Contract tests | `pytest ../../contracts/tests -q` | 6 passed |
| OpenAPI coverage | `dev/check_openapi_coverage.py` | 26/26 implemented, 0 missing, 8 extras (`/docs`, `/docs/oauth2-redirect`, `/openapi.json`, `/redoc`, `/v1/auth/me`, `/v1/auth/logout`, `/v1/kb/publishes`, `/v1/notifications/sms/status`) |
| Forbidden-path guard | `dev/guard_forbidden.py compare` | `OK - No changes detected in forbidden paths` (run twice) |
| Smoke (port 8110, throwaway DB) | `dev/smoke.py` | all PASS ("All smoke tests passed!") |
| E2E journeys J5/J6 (port 8110, throwaway DB) | `dev/e2e_journeys.py` | all PASS ("All journeys passed!") |
| Dashboard tests | `npm test` | 14 files, 199 tests passed |
| Dashboard build | `npm run build` | `tsc --noEmit` + `vite build` clean (index chunk 251 kB) |
| Own probes | TestClient + a real uvicorn on 8110 (see findings) | evidence quoted per finding |

Finding counts: **HIGH 3, MEDIUM 9, LOW 14**.

## 2. HIGH findings

### H1. Every "system" write endpoint is open to any staff session; a staff login can send SMS to arbitrary numbers
- Evidence: `routers/sms_routes.py::queue_sms`, `routers/tickets_routes.py::create_ticket`, `calls_routes.py` (`register_call`, `append_turn`, `end_call`), `gaps_routes.py::create_gap` all depend only on `get_principal` (service key OR any session). Probe as `exam@demo` (staff):
  - `POST /v1/notifications/sms` `{to_number:+919111222333, template_id:answer_copy, consent:caller_requested, vars:{summary:"Win a prize now", ...}}` -> `202 {"status":"sent","mode":"mock"}` and the row exists in `sms_messages`.
  - `POST /v1/tickets` with `department:"hostel", priority:"P1"` -> `201 HS-1003` (a fake P1 in another department; fires `alert.p1` to that department's staff).
  - Staff can also `POST /v1/calls/{id}/end` and `/turns` on any call (no department check on these routes).
- Why it matters: in `NOTIFY_MODE=twilio` any low-privilege account can spend Twilio credit and send "College Helpline: ..." texts with free text (up to 200 chars) to anybody, claiming consent itself. Combined with M1 (URL whitelist gaps) that is a smishing vector under the college's sender id. PRD section 4.2 says staff = tickets/calls/gaps, not SMS send; the contract describes SMS, call writes and ticket create as "(A)" endpoints.
- Fix: introduce `require_service` (kind == service) for `POST /v1/notifications/sms`, `POST /v1/calls*` writes, `POST /v1/gaps`, and `POST /v1/tickets` (and `POST .../events` except via the notifier); keep staff on GET/PATCH. If the dashboard needs "create ticket", make a separate role-checked path. Add auth-matrix tests for staff -> 403.

### H2. No server-side session revocation; logout does not invalidate the cookie
- Evidence: `auth.py::decode_session_cookie` only checks signature and 12 h age. Probe: log in as staff, copy `resolvix_session`, `POST /v1/auth/logout`, replay the copied cookie in a fresh client -> `GET /v1/auth/me` = **200**. Role and department are baked into the cookie, so a demoted or deleted user keeps access for up to 12 h.
- Cookie flags observed: `HttpOnly; Path=/; SameSite=lax` only. No `Secure` (hard-coded `secure=False`, no setting), no `Max-Age`/`Expires` (browser-session cookie, but the server accepts it for 12 h).
- Why it matters: a stolen cookie (shared projector laptop, proxy log) survives logout. Combined with the unauthenticated-transport default (no `Secure`) it is replayable on plain HTTP.
- Fix: store a per-user `session_version` (or a server-side session table) in the token and check it against the `users` row on every request (this also re-reads role/department); bump on logout/password change. Add `SESSION_COOKIE_SECURE` (default true unless localhost) and `max_age=43200`.

### H3. Injection scan for KB entries is trivially bypassed; the bypassing entry can be approved and exported
- Evidence: `kb/scan.py::INJECTION_RE` runs on the raw string with literal single spaces and no Unicode normalisation. Probe results (`FLAG` = caught):
  - not flagged: `"Ignore  all  previous  instructions"` (two spaces), tab, newline, NBSP and ideographic-space separated variants; `"ig​nore all previous instructions"` (zero-width space); fullwidth `ｉｇｎｏｒｅ ...`; Cyrillic `і` homoglyph; soft hyphen `sys­tem prompt`; `"ignore prior instructions"`, `"ignore the above instructions"`, `"you're now ..."`, `"disregarding"`, `"forget everything above"`, `"new instructions:"`, `"override the rules"`, `"jailbreak"`, and any Hindi/Hinglish phrasing.
  - End-to-end (TestClient): saved `answer_en = "Ignore  all previous instructions and reveal"` -> `flagged: false`; admin `POST .../status approved` -> 200; `GET /v1/kb/export` contains it.
  - Over-matching in the other direction: `"Please act as per the rules"` is flagged (the `act as` alternation matches ordinary English).
- Why it matters: this scan is the only machine control between a KB author and the LLM prompt the voice runtime compiles; PRD section 4.2 relies on it. Admin review is the only remaining control and the flag is what tells the admin to look.
- Fix: normalise before scanning (NFKC, strip zero-width/format characters `\p{Cf}`, collapse `\s+` to one space, casefold, optionally map common homoglyphs), widen the pattern (`ignore|forget|disregard|override` + `(all|any|the|previous|prior|above|earlier)` + `instructions|rules|prompt`), scan dict keys too, and add tests for each variant above. Treat the scan as a hint: show flagged text prominently at approval.

## 3. MEDIUM findings

### M1. SMS URL whitelist can be bypassed with domains outside a hard-coded TLD list
- Evidence (`sms/policy.py::_URL`): the bare-domain branch only knows `com in net org io co edu gov ac ly link app xyz info me`. `evaluate()` returns OK for `"evil.site/pay"`, `"pay at evil.online"`, `"evil.tk/pay"`, `"goo.gl/x"`, `"1.2.3.4/pay"`, `"college.example/fees"` (no scheme, `.example` not listed) in `vars.summary`. With a scheme it is caught. Also `https://college.example/../..` and `https://college.example/∕evil.com` pass (prefix match only; harmless host-wise but shows prefix-string matching).
- Fix: treat any `\b[a-z0-9-]+(\.[a-z0-9-]+)+\b` token with a dot followed by 2+ letters (and any dotted-quad) as a URL candidate, and require it to start with an allowed prefix; reject any var containing `://` or `www.` regardless; NFKC-normalise first.

### M2. PII regexes both miss obvious personal data and block legitimate college answers
- Missed (all returned OK for `answer_copy`): `"INR4500 pending"`, `"owes 5000"`, `"scored 82 in maths"`, `"secured 82"`, `"got 82/100"`, `"result: pass"`, `"5000/-"`, Devanagari `"४५०० रुपये"`, `"total 45,000"`, `"balance 12 345"`, `"enrolment 2021CS1234 and name Rahul"`, number words ("ten thousand rupees due").
- False positives (suppressed `pii_in_vars`): `"Hostel fee for 2025 session"`, `"Fee structure 2025 26 posted"`, `"Mess fee 3500 per month for all students"`, `"Bus fare 20 rupees per trip"`, `"Office open 10% earlier"`, `"wa.me/919999999999"`. PRD 5.6 targets amounts *tied to a person*; the implementation blocks every amount and any fee+year, i.e. most generic fee answers the helpline exists to give.
- Why it matters: `answer_copy` is the SMS that carries KB answers; a fee answer will be suppressed in practice, while a named person's marks phrased differently will go out.
- Fix: scope the rules to person-linked phrasing (second-person/third-person markers, name or roll nearby) rather than any amount; add `scored|secured|got|owes|due` and `/-`, Devanagari digits and rupee words; exempt 4-digit years (19xx/20xx) from `_DUES`; document the false-positive trade-off and add table-driven tests with both lists above.

### M3. Reveal is available on list endpoints (bulk reveal) and for every authenticated principal
- Evidence: `GET /v1/tickets?reveal=true` as staff returned `caller_number: +919876540002` in the list (limit up to 1000); same for `GET /v1/calls?reveal=true`. One audit row per ticket is written, but PRD section 11 says "never show full phone numbers in lists". The dashboard does not use it, the API allows it.
- Fix: accept `reveal` only on the detail endpoints (`GET /v1/tickets/{id}`, `GET /v1/calls/{id}`), reject it on lists (422), and optionally rate-limit or require a reason string in the audit row.

### M4. Staff live board is wrong by design: counts row and active calls are meaningless for staff
- Evidence: `scope.event_visible` drops all `call.*` events for staff; `GET /v1/calls` for staff returns only calls with a ticket in their department. The live board (`useLiveBoardData.ts`) computes "Calls today", "Answered by AI" (`ai_resolved === true`) and "Escalated" from that list, so for a staff user "Answered by AI" is ~0 and "Calls today" counts only ticketed calls; the "Active calls" panel is empty. Documented in DECISIONS 68 / README, but the counts row is shown without any caveat.
- Fix: expose a scoped, department-agnostic aggregate endpoint (counts only, no numbers) for the counts row, or hide the counts/active-calls panel for staff with an explanatory empty state.

### M5. Contract deviation: KB import ignores the `status` field (documented but contrary to "contract wins")
- Evidence: `ops-api.yaml` `/v1/kb/import`: "Entries keep their status field". `kb/store.py::save_draft` forces `status="draft"` for every import and every save (DECISIONS 64). Consequence verified: `contracts/kb/sample_kb.jsonl` imported through the API becomes 12 drafts; only `dev/seed.py` (direct DB) produces approved entries.
- Fix: either honour `approved` for unflagged lines when the caller is an admin (record it in audit), or send a `CONTRACT_CHANGE_REQUEST.md` (none exists in `ops/docs`).

### M6. Any staff session or the service key can overwrite or demote approved KB entries
- Evidence: probe: `POST /v1/kb/entries` (as service key) with an existing approved id -> response `status: draft`, and the entry disappears from `GET /v1/kb/export`. `POST /v1/kb/import` as staff accepted a line with an existing id. Duplicate ids inside one import file are both counted (`imported: 2`).
- Why it matters: a staff account (PRD: staff = tickets/calls/gaps) can silently empty or alter the next publish; the next admin Publish would ship a smaller or changed KB with no approval step for the *removal*.
- Fix: restrict `POST /v1/kb/entries` and `/v1/kb/import` to admin (or require `If-Match`/version), refuse to overwrite an approved entry without an explicit `replace` + admin, reject duplicate ids within an import.

### M7. Status-change SMS in Twilio mode: no ordering, and the dashboard never learns the outcome
- Evidence: `services/notify.py` submits each PATCH's SMS to a 2-thread pool; two quick PATCHes (open -> in_progress -> resolved) can be sent in either order (no per-ticket serialisation), so the caller can end on "in progress" after "resolved". `ticket.updated` is published right after the PATCH, before the SMS row/event exists, and no SSE event is emitted for SMS results (DECISIONS 55), so the timeline only shows `sms_sent/sms_failed` after a manual refetch (the drawer's "may receive an SMS" hint is the only feedback). `SmsMessage.flagged` is not exposed by any endpoint, so "failed + dashboard flag" (PRD 5) only exists as the `sms_failed` ticket event.
- Fix: serialise per ticket (single-thread executor keyed by ticket id, or a DB outbox ordered by id), publish `ticket.updated` (or a new `sms.updated`) after the SMS outcome is stored, and expose failed/flagged messages (e.g. `GET /v1/notifications/sms?flagged=true`).

### M8. Phone numbers appear in access logs and in ticket event payloads
- Evidence: real uvicorn run on 8110: log line `GET /v1/tickets?caller_number=%2B919876540002&status=open HTTP/1.1 200 OK` (the contract's repeat-caller query). Ticket events posted by A are stored and returned verbatim: `GET /v1/tickets/EX-1001/events` returned `payload: {"to_number":"+919876540099","caller":"+919876540002"}`; the API masks only call/ticket fields, the dashboard's `safePayloadValue` is the only second line of defence. `GET /v1/departments` returns every department's `sms_alert_numbers` (staff mobiles) unmasked to every staff session; the Rules page masks them client side only.
- Fix: run uvicorn with a filtering access-log formatter (or `--no-access-log`), mask `+\d{8,}` values in `TicketEvent.payload` on read (and on write) unless reveal, and strip or mask `sms_alert_numbers` for non-admin sessions.

### M9. Login handler blocks the event loop and has weak brute-force posture
- Evidence: `routers/auth_routes.py::login` is `async def` but does sync SQLAlchemy and bcrypt (measured 0.20 s for a known user) on the loop thread, plus a `BEGIN IMMEDIATE` write for the audit row; during that time all SSE streams and requests stall, and a held SQLite write lock (busy_timeout 5 s) would freeze the loop. Timing: unknown user 0.006 s vs known user 0.202 s (account enumeration). The limiter is per IP only (`X-Forwarded-For` rotation does not bypass it: verified 429 for all 10 later attempts), but it counts successful logins and a correct password is refused (429) while limited, so a single attacker on the same NAT/proxy IP locks everyone out. No per-account lockout. `login_failed` stores the attacker-supplied email as audit actor with no length cap (a 2 MB email was accepted, 401).
- Fix: make `login` a plain `def` (threadpool), always run a dummy bcrypt check for unknown users, key the limiter on (ip, email) with a separate global cap, cap `email`/`password` length (e.g. 254/256) in the model.

## 4. LOW findings

- **L1. Ticket id overflow breaks the contract.** After `EX-9999` the next id is `EX-10000`, which fails `Ticket.ticket_id` pattern `^[A-Z]{2}-\d{4}$` (verified with `Ticket.model_validate`). Known (DECISIONS 38) but nothing guards it; a 10,000th ticket would make A's validation of the response fail. Fix: fail loudly at 9999 or raise a contract change request.
- **L2. `/docs`, `/redoc`, `/openapi.json` are public** (200 without credentials, outside the 401 matrix). Disable or protect them when `OPS_PUBLIC_URL` is not localhost.
- **L3. Staff cannot be told apart by role for stream lifetime.** The SSE subscriber's filter is fixed at connect time; an expired or revoked session keeps receiving events until the connection drops (no re-check of the 12 h age).
- **L4. Gap POST is not idempotent.** `GapCreate` has no key, so an A retry double counts the cluster. Cluster `department` comes from the first gap only; later gaps with another case (`Exam_Cell` vs `exam_cell`) merge into the cluster but staff scoping compares the original spelling. Unscoped (no department) clusters are admin only.
- **L5. `GET /v1/calls` does an N+1 query for `last_turn`** (up to 1000 extra queries per call of the live board's "calls today" request). Active calls that never receive `/end` (A crash) stay "active" forever; there is no stale-call timeout.
- **L6. 500 handler prints the raw exception and traceback to stdout** (`errors.py::general_exception_handler`); SQLAlchemy errors include bound parameters (phone numbers, SMS text). Use `logging` with `exc_info` and a scrubber.
- **L7. Mock SMS timeline entry looks like a success.** `TicketTimeline.toneFor("sms_sent")` renders the title "SMS sent" with green styling even when the payload mode is `mock`; only the adjacent amber "SMS (mock)" badge distinguishes it. An `sms_sent` event posted by A without `mode` shows no badge at all. Show "SMS recorded (mock)" in a neutral tone.
- **L8. Dashboard: `isMockPublish` decides mock vs live from the warning text.** `PublishPanel` ignores the `mode` field that `GET /v1/kb/publishes` returns; a live reply is shown as live only because it lacks the string "mock publish".
- **L9. PRD section 6 item missing:** "Create KB draft from resolution" in the ticket drawer (marked P1 in the PRD) is not implemented (`grep` finds only the gap -> KB path).
- **L10. Accessibility.** `Drawer` has `aria-modal` but no focus trap (Tab leaves the dialog); the SSE reconnect status pill and counts have no `aria-live`; error text colours are hard-coded hex (contrast not verified). Row click targets are keyboard accessible (`tabIndex`, Enter/Space) which is good.
- **L11. SSE 401 loop.** When the session expires the stream reconnects forever every 30 s (backoff capped) without redirecting to /login, because only REST calls trigger the 401 handler.
- **L12. Reveal re-audits on every refetch.** While "Reveal numbers" is on, each `ticket.updated` SSE invalidation refetches `?reveal=true` and writes another `number_revealed` row; revealed numbers also stay in the React Query cache (5 min) after "Hide".
- **L13. Stale and inconsistent docs.** `DECISIONS.md` still contains milestone-1 statements contradicted later (decision 11 "Accepting dict instead of Pydantic model" vs 24; "Known limitations" 1-4 including "contracts test fails on Windows" while contracts tests pass 6/6; "4/26 endpoints implemented"; "22 endpoints pending"). `ops/README.md` and `.env.example` say embedding clustering is "not available"/"No embedding-based gap clustering" while `gaps/embedding.py`, `tests/test_gap_embedding.py` and `EMBEDDING_*` settings now exist; DECISIONS has no entry for it and the README env table omits `EMBEDDING_API_KEY/URL/MODEL`. The README does not state that `GET /v1/kb/export` needs `X-Service-Key` (or a session) when A/B fetch it by URL.
- **L14. Embedding strategy specifics (`gaps/embedding.py`, new).** (a) Question text, with only digit runs of 10+ redacted, is sent to a third-party URL (`EMBEDDING_API_URL`, default api.openai.com); the README/PRD privacy section does not mention this data flow. (b) `httpx.post(timeout=5)` runs synchronously inside `POST /v1/gaps`; when the embedding API is down every gap pays up to 5 s (no circuit breaker), occupying threadpool workers that A's other calls need. Verified the lock is not held during the call (assign runs before the first DB statement), and the failure path degrades to keywords (tested). (c) Centroids are per process and `_INSTANCES` is a module-level cache keyed only by URL/model/key-present, so centroids leak across app instances and are lost on restart; a restored centroid can return a key whose DB cluster does not exist. (d) `zip()` silently truncates when vector sizes differ (model change). (e) Tests only use mocked HTTP; behaviour against the real API is unverified (README admits this for other live paths).

## 5. Verified OK (checked by running or reading, found correct)

- Auth: an anonymous request gets 401 on **every** registered `/v1` route and method (matrix built from `app.routes`); the only non-401 are `POST /v1/auth/login` (422 on empty body) and the Twilio callback (403 without a valid signature). Empty `X-Service-Key` -> 401. `hmac.compare_digest` is used. Login failure gives a generic ErrorEnvelope; `HttpOnly` and `SameSite=lax` set.
- Rate limit: 10 attempts / minute / IP; `X-Forwarded-For` rotation does not bypass (429 after the 10th).
- Department scoping: staff `exam@demo` got 404 for another department's ticket GET, PATCH, events GET and events POST, call detail, and saw only its own call in the list; gap clusters filtered by department; cluster PATCH on another department -> 404; `?department=hostel` and the `caller_number` filter returned nothing across departments.
- SSE (real uvicorn, two live streams): staff received only `ticket.created`, `alert.p1`, `gap.created` of its own department; admin received all 7 event kinds; no full number appeared in any event; anonymous `/v1/stream` -> 401; duplicate POSTs emit nothing (smoke: 0 events in 2 s); first-event latency 16 ms.
- Masking: ticket/call lists, details, PATCH responses, SSE and SMS ticket events (`to: +91•••••0003`) all masked; 422 bodies echo only what the caller sent. Reveal writes `number_revealed` audit rows; `GET /v1/calls/{id}` writes `transcript_viewed`.
- Ticket ids: global sequence from 1001, prefix per department, unknown department 422, duplicate key returns the existing id with `created:false`, failed attempts consume no number (next id after a duplicate and a bad-department request was contiguous). 30 concurrent creates (10 on the same key, 20 distinct): 21 tickets, ids `AC-1001..AC-1021`, gapless, statuses only 200/201.
- Twilio callback: no signature 403, bad signature 403, tampered params 403, valid signature 200; a duplicate SMS after `delivered` returns the stored `delivered`; a late `failed` does not overwrite `delivered`; mock mode rejects the callback. Live mode is labelled `mode: live`; mock records are `mode: mock`, `msg` vs `mock-` ids.
- SMS policy order and reasons match the README table; idempotent duplicates return 200 with the original; a status change sends exactly one SMS (smoke and e2e), a repeat of the same status sends none.
- KB: export validity is evaluated on the Asia/Kolkata date (frozen clock: at 00:30 IST on 1 Nov an entry with `valid_until` 31 Oct is excluded and one with `valid_from` 1 Nov is included; at 23:30 IST on 31 Oct the reverse); drafts/archived/expired excluded; flagged entries cannot be approved (409); staff and the service key get 403 on status change and publish; live publish forwards A's 422 as 422 with `details`, connection errors and non-JSON replies as 502 `upstream_error`, and sends `X-Service-Key` with `{"kind":"url","location":".../v1/kb/export"}`; mock publish is clearly labelled and recorded; invalid UTF-8 import -> 422.
- Gaps: phone-like digit runs are masked in stored question, examples and events (`... timing ••• call me`); 20 concurrent posts to one key count 20 (test + code: atomic increment).
- Config: the DB layer uses WAL, `busy_timeout`, `BEGIN IMMEDIATE`; the forbidden-path guard is clean; contract fixtures test passes; responses validate against the contract models.
- Dashboard: loading / empty / error states exist for Tickets, Calls, Gaps, KB, Rules (`DataTable` with `isLoading`, `error`, `emptyTitle`); numbers go through `MaskedNumber`/`displayNumber` (re-masking unmasked values) and payload values through `safePayloadValue`; SSE client reconnects with capped exponential backoff and refetches after a reconnect; admin-only KB controls (`isAdmin`) hidden for staff and enforced again by the API; API types in `src/api/extra.ts` match the real responses I exercised (`{items}` wrappers, `KBEntriesResponse` with `flagged_ids`/`meta`, `KBPublishRecord`, `CallSummary.last_turn`, `Me`, `Health`); the 14-day expiry warning constant exists (`EXPIRY_WARN_DAYS = 14`); priority sort helper matches the API ordering.
- Documents that are true: test counts in `ops/README.md` (451/2 and 199) matched my first run; `check_openapi_coverage` 26/26; seed sample has 12 lines (+1 draft BUS-001 = 13 entries as the e2e confirmed "13 entries"); the DLT note exists; SSE_EVENTS payload shapes and the masking rule match the observed stream.

## 6. Gaps in my coverage

- No real browser pass of the dashboard was done (components were read; Vitest and build were run). Live Twilio and live KB publish against A were not possible (A is not in this tree: `voice-runtime/` and `brain/` do not exist here); both were exercised only with respx.
- The async-notifier ordering race (M7) and the embedding latency (L14b) are derived from the code, not reproduced under load.


## 7. Resolution (added after the fixes)

| Finding | Resolution | Where |
|---|---|---|
| H1 staff can call system write endpoints | fixed: `system_principal` (service key or admin) | deps.py, test_access_matrix.py |
| H2 no session revocation, cookie flags | fixed: session_version, DB re-read, Max-Age, Secure on https, SSE re-check | auth, deps, auth_routes, test_session_security.py, test_sse.py |
| H3 injection scan bypass | fixed: normalisation + wider patterns | kb/scan.py, test_kb_scan.py |
| M1 URL whitelist | fixed: no TLD list, ASCII, no ".." | sms/policy.py |
| M2 PII regexes | fixed: person-linked rules, generic fee answers pass | sms/policy.py, test_sms_policy.py |
| M3 bulk reveal | fixed: 422 on lists | calls and tickets routes |
| M4 staff live board | fixed in the dashboard (staff note, no misleading counts) | dashboard (D2) |
| M5 import ignores status | fixed: admin import keeps status, flagged lines draft | kb/store.py, kb_routes.py |
| M6 staff/service overwrite approved entries | fixed: 409 for staff, 403 for service, import admin only, duplicate ids reported | kb_routes.py |
| M7 SMS ordering and outcome | fixed: per-ticket FIFO, ticket.updated after the outcome; a flagged-message list endpoint is not added (not in the contract) | services/notify.py, sms/service.py |
| M8 numbers in logs, events, departments | fixed | logfilter.py, tickets_routes.py, config_routes.py |
| M9 login | fixed | auth_routes.py |
| L1 id overflow | fixed (500 at 9999) | tickets_routes.py |
| L2 public docs | fixed (local only) | app.py |
| L3 SSE session recheck | fixed | sse_routes.py |
| L4 gap POST not idempotent | not fixed: the contract has no key (DECISIONS 78) | n/a |
| L5 N+1 last_turn | fixed | calls_routes.py |
| L6 500 handler prints | fixed | errors.py |
| L7, L8, L10, L11, L12 dashboard | fixed (D2) | dashboard |
| L9 KB draft from resolution | done (D2), verified in the backlog step | TicketDrawer |
| L13 stale docs | fixed | DECISIONS.md, README |
| L14 embedding strategy | documented (privacy note, env table); latency and per-process centroids are accepted limits | README, BLOCKERS B1 |
