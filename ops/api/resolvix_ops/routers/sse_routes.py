"""Server-Sent Events (SSE) routes."""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from starlette.concurrency import run_in_threadpool

from ..auth import decode_session_cookie
from ..deps import Principal, get_principal
from ..orm import User
from ..scope import event_visible, scope_department

router = APIRouter(prefix="/v1", tags=["sse"])

PING_SECONDS = 15


def _session_still_valid(app, cookie: str | None) -> bool:
    """Re-check a session cookie against the database (logout / deleted user / expiry close the stream)."""
    data = decode_session_cookie(cookie, app.state.settings) if cookie else None
    if not data:
        return False
    with app.state.session_factory() as db:
        user = db.query(User).filter(User.email == data.get("email")).first()
        return user is not None and data.get("sv") == user.session_version


@router.get("/stream")
async def stream_events(request: Request, principal: Principal = Depends(get_principal)):
    """Server-Sent Events for the dashboard.

    Event names: call.started, call.turn, call.ended, ticket.created, ticket.updated, alert.p1, gap.created.
    data = the event's JSON object (always includes `ts`; phone numbers are masked).
    Keep-alive comments are sent every 15 s. A stream opened with a session cookie is closed within one such
    interval after that session is revoked (logout, deleted user) or expires; the service key is not re-checked.
    """
    cookie = request.cookies.get("resolvix_session") if principal.kind == "user" else None
    hub = request.app.state.sse_hub
    department = scope_department(principal, request.app.state.settings)

    async def event_generator():
        subscriber_id, queue = hub.subscribe(lambda name, data: event_visible(department, name, data))
        try:
            yield {"comment": "connected"}
            while True:
                try:
                    event_name, data = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
                except asyncio.TimeoutError:
                    if cookie is not None and not await run_in_threadpool(_session_still_valid, request.app, cookie):
                        return
                    continue
                yield {"event": event_name, "data": json.dumps(data, ensure_ascii=False)}
        finally:
            hub.unsubscribe(subscriber_id)

    return EventSourceResponse(event_generator(), ping=PING_SECONDS)
