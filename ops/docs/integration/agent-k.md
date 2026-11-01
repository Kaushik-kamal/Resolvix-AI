# Agent K: knowledge base (integration note)

Code: `ops/api/resolvix_ops/kb/` (scan, store, importer, export, publish) and `routers/kb_routes.py`.
Tests: `tests/test_kb.py`, `tests/test_kb_import.py`, `tests/test_kb_publish.py`.

## For the orchestrator

1. **Allowlist the additive route** `GET /v1/kb/publishes` in `test_openapi_coverage.py` / `dev/check_openapi_coverage.py` (publish history; any authenticated principal).
2. All 7 contract KB operations are implemented (`GET/POST /v1/kb/entries`, `POST /v1/kb/import`, `POST /v1/kb/entries/{id}/status`, `GET /v1/kb/export`, `POST /v1/kb/publish`), so the coverage count goes from 17 to 23 of 26 contract endpoints before gaps/other work.
3. No change to a file I do not own is required. No new packages (python-multipart, httpx and respx were already installed).
4. `test_auth_matrix.py` may add the KB routes: anonymous gets 401 everywhere; `POST /v1/kb/entries/{id}/status` and `POST /v1/kb/publish` give 403 (`unauthorized`) for staff and the service key.

## For the dashboard: exact response shapes

Errors are always `ErrorEnvelope` `{error: {code, message, retryable, details}}`.

### `GET /v1/kb/entries?status=draft|approved|archived`
```json
{ "items": [ /* strict KBEntry objects, ordered by id */ ],
  "flagged_ids": ["FEE-102"],
  "meta": { "FEE-102": { "flagged": true, "updated_at": "2026-11-15T06:00:00+00:00", "updated_by": "admin@demo" } } }
```
**Reading `flagged`:** `flagged_ids.includes(item.id)` or `meta[item.id].flagged`. It is deliberately NOT a key inside `items[]` because `KBEntry` forbids extra fields, so each item still validates as a KBEntry. `meta` has one record per returned item.

### `POST /v1/kb/entries` (201)
Body is a KBEntry. The server always stores it as `draft`, whatever `status` the body carries (omitting it is fine). Response:
`{ "id": "FEE-101", "status": "draft", "flagged": false, "entry": <KBEntry> }`. Show a "flagged: cannot be approved until the text is edited" warning when `flagged` is true. 422 on an invalid entry.

### `POST /v1/kb/entries/{id}/status` (admin session only)
Body `{ "status": "draft" | "approved" | "archived" }`. Response: same shape as above. 403 for staff, 404 unknown id, 409 when the entry is flagged and the target is `approved`.

### `POST /v1/kb/import` (multipart field `file`)
Response `{ "imported": int, "flagged": int, "errors": [ { "line": int, "message": str } ] }`. Line numbers are physical (1-based, blank lines counted). Every imported entry is a draft. Whole-file rejections (not UTF-8, over 2 MB, over 2000 non-blank lines, missing `file`) are 422 `validation_error` with a message.

### `GET /v1/kb/export`
`KBExport`. `version_label` is `YYYYMMDD-<8 hex>` (IST date plus a hash of the exported ids and their updated_at).

### `POST /v1/kb/publish` (admin session only)
200 `KBVersionInfo`. In mock mode the `warnings` list contains `"mock publish: nothing was sent to the voice runtime"`: show it so a mock publish is never mistaken for a live one. 422 carries the voice runtime's problems in `error.details` (`{ "<key>": "<problem>" }`). 502 `upstream_error` with `retryable: true` for unreachable, timeout or 5xx.

### `GET /v1/kb/publishes?limit=50` (additive)
`{ "items": [ { "kb_version", "info": <KBVersionInfo>, "mode": "mock"|"live", "actor": "<email>", "at": "<ISO UTC>" } ] }`, newest first.

## Decisions

- **Import never approves, and edits become drafts.** The yaml says import entries "keep their status field"; the orchestrator rule (draft always) wins. An imported or POSTed entry that already exists and was approved becomes a draft again and leaves the export until re-approved.
- **Scan regex:** the PRD pattern with word boundaries on both ends (`contact assistance` contains "act as" and must not flag), and `ignore all previous instructions` also matches (the literal PRD pattern misses the canonical phrasing). Every string field and list item is scanned, on every save and import line. A clean re-save clears the flag.
- **Import errors use `message`** (yaml), not `error`.
- **Limits:** the line limit counts non-blank lines; the size limit applies to the raw bytes. Both are 422 `validation_error`, as the contract has no 413. Nothing is stored for a rejected file.
- **Import audit:** one `kb_imported` audit row per upload (counts, flagged ids), not one row per entry. Single saves write `kb_entry_saved`; status changes write `kb_entry_status_changed` (old/new status); publishes write `kb_published` or `kb_publish_failed`.
- **Who may do what:** admin session for status changes and publish. Saving drafts, importing, listing and exporting accept any authenticated principal (service key included).
- **Mock publish:** fixture `kb_version_info.json` with `activated_at` = clock now, `entry_count` and `faq_count` = the real exportable entries, plus the mock warning. `kb_version` and `token_count` stay the fixture's because C does not compile anything, so a computed hash would be invented. Republishing identical content therefore stores equal `kb_version` rows (the column is not unique, by design).
- **Live publish:** `httpx.post` with `kb_publish_timeout_s` for every phase. Statuses other than 200/422 (including 401/404 from A) map to 502 `upstream_error`; `retryable` is true for network errors, timeouts and 5xx. The service key is only ever placed in the request header; nothing logs headers (covered by a caplog test at DEBUG level).
- `GET /v1/kb/export` is idempotent and read-only; `exported_at` is the injectable clock's now.

## Contract differences

- `POST /v1/kb/entries` response body (yaml: "Stored") is `{id, status, flagged, entry}` rather than a bare KBEntry, so the dashboard learns `flagged` immediately.
- `GET /v1/kb/entries` adds the sibling keys `flagged_ids` and `meta` next to `items`.
- `POST /v1/kb/import` yaml says "Entries keep their status field"; implemented as always-draft (see above).
- `GET /v1/kb/publishes` is not in the yaml (additive).

## WALLS

None. Live publish was verified only against respx mocks; it has not been run against the real voice runtime (Member A's `/admin/kb/reload`), which needs A's code running.
