"""
Resolvix Member A dev ops stub.
A lightweight FastAPI app running on :8100 providing in-memory storage for ops-api
endpoints so voice-runtime can be developed and manually tested without Member C.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, Header, HTTPException, status
import uvicorn

from resolvix_contracts.models import (
    CallEnd,
    CallStart,
    GapCreate,
    SmsRequest,
    SmsResult,
    Ticket,
    TicketCreate,
    TicketCreated,
    TicketEvent,
    TicketStatus,
    TurnSummary,
)

app = FastAPI(title="Resolvix Ops Stub (Member A Dev)")

DEPT_PREFIXES = {
    "exam_cell": "EX",
    "accounts": "AC",
    "hostel": "HS",
    "helpdesk": "HD",
    "emergency": "EM",
    "transport": "TR",
    "admissions": "AD",
}

# In-memory storage
calls: dict[str, dict] = {}
turns: dict[tuple[str, int], TurnSummary] = {}
tickets: dict[str, Ticket] = {}
ticket_idempotency: dict[str, str] = {}
ticket_events: dict[str, list[TicketEvent]] = {}
sms_log: list[SmsRequest] = {}
sms_idempotency: dict[str, SmsResult] = {}
gaps: list[GapCreate] = []
ticket_seq = 1000


@app.get("/healthz")
def health():
    return {"status": "ok", "contract_version": "1.0.0", "notify_mode": "mock"}


@app.post("/v1/calls", status_code=status.HTTP_201_CREATED)
def post_call(call: CallStart, x_service_key: str | None = Header(None)):
    if call.call_id in calls:
        return {"status": "already_registered"}
    calls[call.call_id] = {
        "start": call,
        "ended": False,
        "end_data": None,
    }
    return {"status": "registered"}


@app.post("/v1/calls/{call_id}/turns", status_code=status.HTTP_201_CREATED)
def post_turn(call_id: str, turn: TurnSummary, x_service_key: str | None = Header(None)):
    turns[(call_id, turn.turn_index)] = turn
    return {"status": "stored"}


@app.post("/v1/calls/{call_id}/end")
def end_call(call_id: str, end: CallEnd, x_service_key: str | None = Header(None)):
    if call_id in calls:
        calls[call_id]["ended"] = True
        calls[call_id]["end_data"] = end
    return {"status": "ended"}


@app.post("/v1/tickets", response_model=TicketCreated, status_code=status.HTTP_201_CREATED)
def create_ticket(ticket: TicketCreate, x_service_key: str | None = Header(None)):
    global ticket_seq
    if ticket.idempotency_key in ticket_idempotency:
        existing_id = ticket_idempotency[ticket.idempotency_key]
        return TicketCreated(ticket_id=existing_id, created=False)

    ticket_seq += 1
    prefix = DEPT_PREFIXES.get(ticket.department, "HD")
    ticket_id = f"{prefix}-{ticket_seq}"

    now = datetime.now(timezone.utc)
    t = Ticket(
        ticket_id=ticket_id,
        call_id=ticket.call_id,
        type=ticket.type,
        priority=ticket.priority,
        priority_reason=ticket.priority_reason,
        department=ticket.department,
        status=TicketStatus.open,
        summary=ticket.summary,
        collected_fields=ticket.collected_fields,
        caller_number=ticket.caller_number,
        callback_number=ticket.callback_number,
        callback_requested=ticket.callback_requested,
        transcript_excerpt=ticket.transcript_excerpt,
        brief=ticket.brief,
        created_at=now,
        updated_at=now,
    )
    tickets[ticket_id] = t
    ticket_idempotency[ticket.idempotency_key] = ticket_id
    ticket_events[ticket_id] = []
    return TicketCreated(ticket_id=ticket_id, created=True)


@app.get("/v1/tickets")
def get_tickets(
    caller_number: str | None = None,
    status: str | None = None,
    department: str | None = None,
    x_service_key: str | None = Header(None),
):
    results = []
    for t in tickets.values():
        if caller_number and t.caller_number != caller_number:
            continue
        if status and t.status != status:
            continue
        if department and t.department != department:
            continue
        results.append(t)
    return {"items": [t.model_dump(mode="json") for t in results]}


@app.post("/v1/tickets/{ticket_id}/events", status_code=status.HTTP_201_CREATED)
def post_ticket_event(ticket_id: str, event: TicketEvent, x_service_key: str | None = Header(None)):
    if ticket_id not in ticket_events:
        ticket_events[ticket_id] = []
    ticket_events[ticket_id].append(event)
    return {"status": "stored"}


@app.post("/v1/notifications/sms", response_model=SmsResult, status_code=status.HTTP_202_ACCEPTED)
def post_sms(sms: SmsRequest, x_service_key: str | None = Header(None)):
    if sms.idempotency_key in sms_idempotency:
        return sms_idempotency[sms.idempotency_key]

    result = SmsResult(
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
        status="sent",
        mode="mock",
        reason=None,
    )
    sms_idempotency[sms.idempotency_key] = result
    return result


@app.post("/v1/gaps", status_code=status.HTTP_201_CREATED)
def post_gap(gap: GapCreate, x_service_key: str | None = Header(None)):
    gaps.append(gap)
    return {"status": "stored"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
