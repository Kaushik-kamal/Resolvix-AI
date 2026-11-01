"""Server-Sent Events (SSE) hub for real-time dashboard updates."""
import asyncio
import logging
from typing import Any

from .timeutil import iso_utc, now_utc

log = logging.getLogger(__name__)

QUEUE_MAX = 100

# Event names of GET /v1/stream (contract: ops-api.yaml). Publish with these constants.
CALL_STARTED = "call.started"
CALL_TURN = "call.turn"
CALL_ENDED = "call.ended"
TICKET_CREATED = "ticket.created"
TICKET_UPDATED = "ticket.updated"
ALERT_P1 = "alert.p1"
GAP_CREATED = "gap.created"


class SSEHub:
    """In-process pub/sub hub, one per app instance.

    Event names: call.started, call.turn, call.ended, ticket.created, ticket.updated, alert.p1, gap.created.
    Subscribers get a bounded asyncio.Queue (drop-oldest when full) of (event_name, data) tuples.
    publish() is safe to call from sync endpoints running in the threadpool.
    """

    def __init__(self, queue_max: int = QUEUE_MAX):
        self._queue_max = queue_max
        self._subscribers: dict[int, asyncio.Queue] = {}
        self._filters: dict[int, object] = {}
        self._next_subscriber_id = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop | None):
        """Capture the serving event loop (called from lifespan; None on shutdown)."""
        self._loop = loop

    def subscribe(self, visible=None) -> tuple[int, asyncio.Queue]:
        """visible(event_name, data) -> bool filters what this subscriber receives (None = everything)."""
        subscriber_id = self._next_subscriber_id
        self._next_subscriber_id += 1
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max)
        self._subscribers[subscriber_id] = queue
        self._filters[subscriber_id] = visible
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: int):
        self._subscribers.pop(subscriber_id, None)
        self._filters.pop(subscriber_id, None)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event_name: str, data: dict[str, Any]) -> bool:
        """Queue an event for every subscriber. Adds 'ts' (UTC ISO) if absent.

        Never raises: the DB commit that triggered the event has already succeeded, so a
        dead loop must not turn the request into a 500. Returns False if nothing was scheduled.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return False
        payload = dict(data)
        payload.setdefault("ts", iso_utc(now_utc()))
        try:
            loop.call_soon_threadsafe(self._deliver, event_name, payload)
        except RuntimeError:
            return False
        return True

    def _deliver(self, event_name: str, data: dict[str, Any]):
        """Runs on the event loop thread."""
        for subscriber_id, queue in list(self._subscribers.items()):
            visible = self._filters.get(subscriber_id)
            if visible is not None and not visible(event_name, data):
                continue
            try:
                if queue.full():
                    queue.get_nowait()  # drop oldest
                queue.put_nowait((event_name, data))
            except Exception:  # pragma: no cover - defensive
                log.exception("SSE delivery to subscriber %s failed", subscriber_id)
