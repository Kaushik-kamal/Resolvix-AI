"""SMS providers: the mock one and Twilio (plain REST over httpx, so it can be mocked with respx).

Never log numbers, message text, tokens or account SIDs from this module.
"""
import logging
import uuid
from dataclasses import dataclass

import httpx

from ..config import Settings

# httpx logs full request URLs at INFO; the Twilio URL contains the account SID.
logging.getLogger("httpx").setLevel(logging.WARNING)

TWILIO_API = "https://api.twilio.com/2010-04-01"


class ProviderError(Exception):
    """A send attempt failed. `reason` is a short snake_case string that ends up in SmsResult.reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SendResult:
    provider_id: str
    status: str  # provider's own status word (mock: "sent", twilio: "queued"/"sent"/...)


class SmsProvider:
    mode = "mock"  # SmsResult.mode value: "mock" | "live"

    def send(self, to_number: str, body: str, status_callback: str | None) -> SendResult:
        raise NotImplementedError

    def fetch_status(self, provider_id: str) -> tuple[str, str | None]:
        """(provider status, error code or None)."""
        raise NotImplementedError


class MockProvider(SmsProvider):
    """Records nothing and sends nothing; the SMS service stores the attempt with mode="mock"."""

    mode = "mock"

    def send(self, to_number: str, body: str, status_callback: str | None) -> SendResult:
        return SendResult(provider_id=f"mock-{uuid.uuid4().hex[:12]}", status="sent")

    def fetch_status(self, provider_id: str) -> tuple[str, str | None]:
        return "sent", None


class TwilioProvider(SmsProvider):
    mode = "live"

    def __init__(self, account_sid: str, auth_token: str, from_number: str, timeout_s: float = 5.0):
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._timeout = timeout_s

    def send(self, to_number: str, body: str, status_callback: str | None) -> SendResult:
        data = {"To": to_number, "From": self._from, "Body": body}
        if status_callback:
            data["StatusCallback"] = status_callback
        try:
            r = httpx.post(f"{TWILIO_API}/Accounts/{self._sid}/Messages.json", data=data,
                           auth=(self._sid, self._token), timeout=self._timeout)
        except httpx.TimeoutException:
            raise ProviderError("provider_timeout") from None
        except httpx.HTTPError:
            raise ProviderError("provider_unreachable") from None
        if r.status_code not in (200, 201):
            raise ProviderError(f"provider_http_{r.status_code}")
        try:
            payload = r.json()
            return SendResult(provider_id=payload["sid"], status=payload.get("status", "queued"))
        except (ValueError, KeyError):
            raise ProviderError("provider_bad_response") from None

    def fetch_status(self, provider_id: str) -> tuple[str, str | None]:
        try:
            r = httpx.get(f"{TWILIO_API}/Accounts/{self._sid}/Messages/{provider_id}.json",
                          auth=(self._sid, self._token), timeout=self._timeout)
            r.raise_for_status()
            payload = r.json()
        except (httpx.HTTPError, ValueError):
            raise ProviderError("provider_status_unavailable") from None
        code = payload.get("error_code")
        return payload.get("status", "unknown"), (str(code) if code else None)


def build_provider(settings: Settings) -> SmsProvider:
    """Provider for NOTIFY_MODE. Twilio mode fails fast, naming (never printing) the missing settings."""
    mode = settings.sms_mode
    if mode == "mock":
        return MockProvider()
    if mode == "twilio":
        missing = [name for name, value in (
            ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
            ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
            ("TWILIO_FROM", settings.twilio_from_number),
        ) if not value]
        if missing:
            raise RuntimeError(f"NOTIFY_MODE=twilio requires these settings, which are empty: {', '.join(missing)}")
        return TwilioProvider(settings.twilio_account_sid, settings.twilio_auth_token,
                              settings.twilio_from_number, settings.sms_send_timeout_s)
    raise RuntimeError(f"NOTIFY_MODE must be 'mock' or 'twilio' (got {settings.notify_mode!r})")
