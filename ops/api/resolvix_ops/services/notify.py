"""Notification seam called by the ticket routes, and the real implementation behind it."""
import logging
import zlib
from concurrent.futures import ThreadPoolExecutor

from resolvix_contracts import SmsRequest
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


class ShardedExecutor:
    """N single-thread workers; work with the same key always runs on the same worker, in submission order.

    Two quick status changes of one ticket therefore reach the caller in the order they were made, while
    different tickets still send in parallel.
    """

    def __init__(self, workers: int = 2, name: str = "sms"):
        self._shards = [ThreadPoolExecutor(max_workers=1, thread_name_prefix=name) for _ in range(workers)]

    def submit(self, key: str, fn, *args):
        return self._shards[zlib.crc32(key.encode("utf-8")) % len(self._shards)].submit(fn, *args)

    def shutdown(self, wait: bool = True):
        for shard in self._shards:
            shard.shutdown(wait=wait)


class Notifier:
    """Notification interface; this base class does nothing (used by tests that do not want SMS)."""

    def on_ticket_status_changed(
        self,
        db: Session,
        ticket,  # Ticket ORM object
        old_status: str | None,
        new_status: str,
        actor: str,
    ):
        """Called once, after commit, for each real ticket status change."""


class SmsNotifier(Notifier):
    """Sends ONE status_change SMS per (ticket, new status) to the ticket's callback_number.

    Only for tickets that have both a call_id and a callback_number; others get nothing (not even a
    suppressed record). The idempotency key "{ticket_id}:status:{new_status}" means moving a ticket back to a
    status it already had does not send a second SMS for that status.
    The SMS service works in its own sessions and commits before returning, so its records are visible to the
    next request. Synchronous mode: errors propagate to the route, which logs them and still answers the PATCH.
    Async mode (executor given): the send runs on a worker thread and failures are only logged.
    """

    def __init__(self, sms_service, executor=None):
        self.sms = sms_service
        self.executor = executor  # ThreadPoolExecutor => send off the request thread

    def _send(self, req) -> None:
        try:
            self.sms.submit(req, notify_outcome=True)
        except Exception:  # worker thread: nobody to raise to, the PATCH already succeeded
            log.exception("status-change SMS failed for %s", req.ticket_id)

    def on_ticket_status_changed(self, db, ticket, old_status, new_status, actor):
        if not ticket.call_id or not ticket.callback_number:
            return
        req = SmsRequest(
            idempotency_key=f"{ticket.ticket_id}:status:{new_status}",
            to_number=ticket.callback_number,
            template_id="status_change",
            vars={"ticket_id": ticket.ticket_id, "status": new_status.replace("_", " ")},
            consent="transactional",
            call_id=ticket.call_id,
            ticket_id=ticket.ticket_id,
        )
        if self.executor is not None:
            self.executor.submit(req.ticket_id, self._send, req)  # own DB sessions; FIFO per ticket
        else:
            self.sms.submit(req)
