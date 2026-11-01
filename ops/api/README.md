# Resolvix Ops API (Member C)

Backend for ops dashboard, tickets, SMS, and knowledge base management.

## Setup

```powershell
# Create venv with Python 3.11
py -V:Astral/CPython3.11 -m venv .venv

# Activate
.\.venv\Scripts\Activate.ps1

# Install contracts
pip install -e ../../contracts/python

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Install package in editable mode
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and configure:
- `SERVICE_KEY`: Shared key for runtime authentication
- `SESSION_SECRET`: 32+ character secret for session cookies
- `SEED_PASSWORD`: Default password for seed users
- Other settings per `.env.example`

## Run Tests

**Important:** Always run Python with UTF-8 mode on Windows to handle non-ASCII content in config files:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests -v
```

Or from project root:

```powershell
cd ops/api
python -X utf8 -m pytest
```

## Run Server

```powershell
.\.venv\Scripts\python.exe -X utf8 -m uvicorn resolvix_ops.app:app --port 8100 --loop asyncio --workers 1
```

For auto-reload during development:

```powershell
python -X utf8 -m uvicorn resolvix_ops.app:app --port 8100 --reload
```

## Smoke Test

```powershell
python -X utf8 dev/smoke.py
```

## Project Structure

```
ops/api/
├── resolvix_ops/         # Main package
│   ├── routers/          # Route handlers
│   ├── app.py            # Application factory
│   ├── config.py         # Settings
│   ├── db.py             # Database session
│   ├── orm.py            # SQLAlchemy models
│   ├── auth.py           # Authentication
│   ├── audit.py          # Audit logging
│   └── errors.py         # Error handlers
├── tests/                # Pytest tests
├── dev/                  # Development utilities
├── data/                 # SQLite database (gitignored)
└── .venv/                # Virtual environment (gitignored)
```

## API Documentation

Once running, visit:
- http://localhost:8100/docs (Swagger UI)
- http://localhost:8100/redoc (ReDoc)


## SMS

`POST /v1/notifications/sms` (A) queues an SMS; staff status changes send one automatically (see "Status-change SMS").
Every attempt is stored in `sms_messages`; the full number is stored there only. Responses, ticket events and logs
show it masked (`+91•••••0004`); message vars are never logged.

### Modes (`NOTIFY_MODE`)

| Mode | What happens | `SmsResult.mode` |
|---|---|---|
| `mock` (default) | Nothing is sent. The record is stored as `status=sent`, `provider_id=mock-<id>`. The ticket event carries `mode: mock`; the dashboard must label it "SMS (mock)". | `mock` |
| `twilio` (`live` is accepted as an alias) | Sent through the Twilio Messages REST API. 5 s timeout per attempt, one retry, then `failed` (record flagged). | `live` |

Twilio mode needs `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM` (`TWILIO_FROM_NUMBER` also works); the app
refuses to start with a clear message listing the empty ones. `OPS_PUBLIC_URL` is the base for the Twilio status callback
(`{OPS_PUBLIC_URL}/v1/notifications/sms/status`). Other settings: `SMS_SEND_TIMEOUT_S` (5), `SMS_POLL_ENABLED` (true),
`SMS_POLL_DELAY_S` (10).

**Mock or test-sender messages are not production delivery.** Indian SMS needs a DLT-registered sender id and DLT-approved
templates; the wording in `contracts/config/sms_templates.yaml` must match the registered templates before live sending.

### Policy (checked in this order; first failure becomes `status=suppressed` with a `reason`)

0. Idempotency: an `idempotency_key` seen before returns the stored record with HTTP 200 and sends nothing (suppressed results are stored too, so their duplicates return the same suppressed result).
1. `unknown_template`: template id missing from `sms_templates.yaml` (an id outside the contract enum is rejected earlier with 422).
2. `consent_not_allowed`: `ticket_created`/`status_change` need `transactional`; `answer_copy` needs `caller_requested` or `offer_accepted`; `staff_alert` needs `staff`.
3. `invalid_e164` (`^\+[1-9]\d{7,14}$`), and for `staff_alert` `staff_number_not_allowed` unless the number is a department or emergency `sms_alert_numbers` entry in `departments.yaml`.
4. `missing_vars`: a placeholder has no var (extra vars are ignored but still scanned for PII); `vars_too_long`: a var over 200 chars or rendered text over 480.
5. `pii_in_vars`: the vars (never the fixed template text) match one of these rules:
   - `money_amount`: a currency sign or word next to a number (`₹`, `Rs`, `INR`, `rupees`), e.g. `Rs 4500`, `5000 rupees`.
   - `marks_or_grade`: marks, score, CGPA/SGPA/GPA, percentage, percentile or result followed by a number (`marks are 82`, `Result: 71%`), a number followed by marks, `%`, CGPA, GPA or "out of", or `grade B+`.
   - `dues_or_fees`: dues, fee(s), fine, outstanding, balance, pending or arrears followed within 15 non-digit characters by a number of 3 or more digits (`fees 45000`; "fee deadline 30 Nov" still passes).
   - `roll_number_with_name`: a roll-number-like token (a bare run of 9-14 digits not preceded by `+`, `21CS1234` style, or `roll no ...` followed by digits) together with a name-like token (two or more Capitalised words, `Mr/Mrs/Ms/Dr/Shri/Smt <name>`, or `name: ...`) anywhere in the vars. Phone numbers (`+910000000101`), ticket ids (`HS-1044`) and department names pass.
6. `url_not_allowed`: any URL in the rendered text (with a scheme, `www.`, or a bare domain on a common TLD) must start with an entry of `allowed_url_prefixes`.

These are simple regex heuristics, not a guarantee; they are meant to stop the obvious mistakes. The implementation is `resolvix_ops/sms/policy.py`.

### Status-change SMS

When staff change a ticket status (PATCH), the notifier sends one `status_change` SMS to the ticket's `callback_number`
(consent `transactional`, idempotency key `{ticket_id}:status:{new_status}`), only if the ticket has both a `call_id` and a
`callback_number`. Consequence of that key: moving a ticket back to a status it already had does not send a second SMS for that
status. No SMS is sent when a ticket is created. SMS problems never fail the PATCH.

### Delivery status

Twilio posts delivery status to `POST /v1/notifications/sms/status` (public route, but it requires a valid `X-Twilio-Signature`
for `{OPS_PUBLIC_URL}/v1/notifications/sms/status`; otherwise 403). `delivered` marks the record delivered; `failed`/`undelivered`
mark it failed, flag it and add an `sms_failed` ticket event. When `OPS_PUBLIC_URL` is localhost Twilio cannot call back, so a
single status poll runs 10 s after the send.

Ticket events written per SMS (when `ticket_id` belongs to a ticket): `sms_sent`, `sms_failed`, `sms_suppressed`, with payload
`template_id, mode, status, to (masked), reason, message_id`.
