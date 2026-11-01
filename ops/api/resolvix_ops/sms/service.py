"""SMS service: policy, persistence, sending, status tracking.

Three short transactions so the SQLite write lock is never held while talking to the provider:
  1. idempotency lookup + policy + insert (status "queued", or "suppressed" and done)
  2. provider call (no transaction open), one retry after a failure
  3. record the outcome (+ ticket event)
Numbers are stored in full in sms_messages; everything that leaves the service (results, events, logs) is masked.
"""
import logging
import threading
import uuid
from urllib.parse import urlparse

from resolvix_contracts import SmsRequest, SmsResult
from sqlalchemy.exc import IntegrityError

from ..orm import SmsMessage, Ticket, TicketEvent
from ..privacy import mask_number
from ..timeutil import now_utc
from . import policy
from .providers import ProviderError, SmsProvider

log = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
_FINAL = {"delivered", "failed", "suppressed"}
_EVENT_KIND = {"sent": "sms_sent", "failed": "sms_failed", "suppressed": "sms_suppressed"}


def result_of(row: SmsMessage) -> SmsResult:
    return SmsResult(message_id=row.message_id, status=row.status, mode=row.mode, reason=row.reason)


class SmsService:
    def __init__(self, settings, session_factory, config: policy.SmsConfig, staff_numbers: frozenset[str],
                 provider: SmsProvider):
        self.settings = settings
        self._sessions = session_factory
        self.config = config
        self.staff_numbers = staff_numbers
        self.provider = provider
        self.on_outcome = None  # callable(ticket_id): the SMS record/event of a ticket changed (set by create_app)
        self.scheduled_polls: list[str] = []  # provider ids a status poll was scheduled for (tests assert it stays empty)

    # ------------------------------------------------------------------ public
    def submit(self, req: SmsRequest, notify_outcome: bool = False) -> tuple[SmsResult, bool]:
        """Returns (result, is_new). A repeated idempotency_key returns the stored record and sends nothing.

        notify_outcome=True (background sends) calls on_outcome(ticket_id) once the outcome is stored, so the
        dashboard can refresh a ticket whose request already returned."""
        mode = self.provider.mode
        with self._sessions() as db:
            existing = self._by_key(db, req.idempotency_key)
            if existing is not None:
                return result_of(existing), False

            decision = policy.evaluate(
                self.config, self.staff_numbers, template_id=req.template_id, consent=req.consent,
                to_number=req.to_number, variables=req.vars)
            needed = policy.placeholders(self.config.templates.get(req.template_id, ""))
            row = SmsMessage(
                idempotency_key=req.idempotency_key,
                message_id=f"{'mock' if mode == 'mock' else 'msg'}-{uuid.uuid4().hex[:12]}",
                to_number=req.to_number,
                template_id=req.template_id,
                vars_json={k: v for k, v in req.vars.items() if k in needed} if decision.ok else {},
                consent=req.consent,
                call_id=req.call_id,
                ticket_id=req.ticket_id,
                status="queued" if decision.ok else "suppressed",
                mode=mode,
                reason=decision.reason,
                flagged=False,
                created_at=now_utc(),
                updated_at=now_utc(),
            )
            db.add(row)
            if not decision.ok:
                self._ticket_event(db, row)
            try:
                db.commit()
            except IntegrityError:  # lost a race on the unique key: the other writer's record is the answer
                db.rollback()
                return result_of(self._by_key(db, req.idempotency_key)), False
            if not decision.ok:
                log.info("sms %s suppressed: %s", row.message_id, decision.reason)
                return result_of(row), True
            message_id, to_number, text = row.message_id, row.to_number, decision.text

        send_result, failure = self._send_with_retry(to_number, text)

        with self._sessions() as db:
            row = db.query(SmsMessage).filter(SmsMessage.message_id == message_id).one()
            if send_result is not None:
                row.status = "sent"
                row.provider_id = send_result.provider_id
            else:
                row.status = "failed"
                row.reason = failure
                row.flagged = True
            row.updated_at = now_utc()
            self._ticket_event(db, row)
            db.commit()
            log.info("sms %s %s", row.message_id, row.status)
            result = result_of(row)
            provider_id = row.provider_id

        if send_result is not None and self.provider.mode == "live":
            self._maybe_schedule_poll(provider_id)
        if notify_outcome and req.ticket_id:
            self._outcome(req.ticket_id)
        return result, True

    def apply_provider_status(self, provider_id: str, provider_status: str, error_code: str | None = None) -> bool:
        """Apply a Twilio status (callback or poll). Only non-final records change. True if the record changed."""
        provider_status = provider_status.lower()
        if provider_status == "delivered":
            new_status, reason = "delivered", None
        elif provider_status in {"failed", "undelivered"}:
            new_status = "failed"
            reason = f"provider_{provider_status}" + (f"_{error_code}" if error_code else "")
        else:
            return False  # queued / sending / sent: nothing new
        with self._sessions() as db:
            row = db.query(SmsMessage).filter(SmsMessage.provider_id == provider_id).first()
            if row is None or row.status in _FINAL:
                return False
            row.status = new_status
            row.reason = reason
            row.flagged = new_status == "failed"
            row.updated_at = now_utc()
            if new_status == "failed":
                self._ticket_event(db, row)
            ticket_id = row.ticket_id
            db.commit()
        if ticket_id:
            self._outcome(ticket_id)
        return True

    # ------------------------------------------------------------------ internals
    def _outcome(self, ticket_id: str) -> None:
        if self.on_outcome is not None:
            try:
                self.on_outcome(ticket_id)
            except Exception:
                log.warning("sms outcome hook failed", exc_info=False)

    @staticmethod
    def _by_key(db, key: str) -> SmsMessage | None:
        return db.query(SmsMessage).filter(SmsMessage.idempotency_key == key).first()

    def _send_with_retry(self, to_number: str, text: str):
        callback = self._status_callback()
        failure = "provider_error"
        for _attempt in (1, 2):  # the attempt and ONE retry
            try:
                return self.provider.send(to_number, text, callback), None
            except ProviderError as exc:
                failure = exc.reason
                log.warning("sms send attempt failed: %s", exc.reason)
        return None, failure

    def _status_callback(self) -> str | None:
        if self.provider.mode != "live" or self._public_url_is_local():
            return None
        return f"{self.settings.ops_public_url.rstrip('/')}/v1/notifications/sms/status"

    def _public_url_is_local(self) -> bool:
        return (urlparse(self.settings.ops_public_url).hostname or "") in _LOCAL_HOSTS

    def _maybe_schedule_poll(self, provider_id: str | None) -> None:
        """Twilio cannot reach a localhost callback URL: poll the status once, later."""
        if not provider_id or not self.settings.sms_poll_enabled or not self._public_url_is_local():
            return
        self.scheduled_polls.append(provider_id)
        timer = threading.Timer(self.settings.sms_poll_delay_s, self._poll_once, args=(provider_id,))
        timer.daemon = True
        timer.start()

    def _poll_once(self, provider_id: str) -> None:
        try:
            status, error_code = self.provider.fetch_status(provider_id)
            self.apply_provider_status(provider_id, status, error_code)
        except Exception:  # a failed poll just leaves the record at "sent"
            log.warning("sms status poll failed", exc_info=False)

    @staticmethod
    def _ticket_event(db, row: SmsMessage) -> None:
        """sms_sent / sms_failed / sms_suppressed on the ticket, when the SMS belongs to an existing ticket."""
        kind = _EVENT_KIND.get(row.status)
        if kind is None or not row.ticket_id:
            return
        if db.query(Ticket.id).filter(Ticket.ticket_id == row.ticket_id).first() is None:
            return
        db.add(TicketEvent(
            ticket_id=row.ticket_id, kind=kind, actor="system", at=now_utc(),
            payload={
                "template_id": row.template_id,
                "mode": row.mode,
                "status": row.status,
                "to": mask_number(row.to_number) or "",
                "reason": row.reason or "",
                "message_id": row.message_id,
            },
        ))
