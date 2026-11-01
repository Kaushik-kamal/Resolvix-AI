"""Publish: tell the voice runtime (A) to reload the KB from our export URL, or answer from the fixture in mock mode."""
import json
import logging
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session

from resolvix_contracts import KBSource, KBVersionInfo

from ..config import Settings
from .export import exportable

log = logging.getLogger(__name__)

# R/ops/api/resolvix_ops/kb/publish.py -> R
_FIXTURE = Path(__file__).resolve().parents[4] / "contracts" / "fixtures" / "ops" / "kb_version_info.json"
_FALLBACK = {"kb_version": "a1b2c3d4e5f6", "entry_count": 0, "faq_count": 0, "token_count": 0,
             "activated_at": "2026-01-01T00:00:00+00:00", "warnings": []}
MOCK_WARNING = "mock publish: nothing was sent to the voice runtime"


class PublishError(Exception):
    """A publish failure that maps to an ErrorEnvelope: 422 (A rejected the KB) or 502 (A unreachable/broken)."""

    def __init__(self, status_code: int, code: str, message: str, details: dict[str, str] | None = None,
                 retryable: bool = False):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message
        self.details, self.retryable = details or {}, retryable


def _fixture() -> dict:
    try:
        return json.loads(_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(_FALLBACK)


def mock_publish(db: Session, clock) -> KBVersionInfo:
    """kb_version_info.json with a fresh activated_at and the true count of exportable entries / FAQs.
    kb_version and token_count stay the fixture's (we do not compile; inventing a hash would be misleading)."""
    items = exportable(db, clock.today_ist())
    data = _fixture()
    data.update(entry_count=len(items), faq_count=sum(1 for _, e in items if e.is_faq),
                activated_at=clock.now().isoformat(), warnings=list(data.get("warnings") or []) + [MOCK_WARNING])
    return KBVersionInfo.model_validate(data)


def _problems(resp: httpx.Response) -> tuple[str, dict[str, str]]:
    """(message, details) from A's ErrorEnvelope; falls back to the raw text when the body is not one."""
    try:
        err = resp.json()["error"]
        details = {str(k): str(v) for k, v in (err.get("details") or {}).items()}
        return str(err.get("message") or "Knowledge base rejected by the voice runtime"), details
    except (ValueError, KeyError, TypeError, AttributeError):
        return "Knowledge base rejected by the voice runtime", {"problems": resp.text[:500]}


def live_publish(settings: Settings) -> KBVersionInfo:
    """POST {RUNTIME_URL}/admin/kb/reload. The service key is sent but never logged."""
    url = f"{settings.runtime_url.rstrip('/')}/admin/kb/reload"
    source = KBSource(kind="url", location=f"{settings.ops_public_url.rstrip('/')}/v1/kb/export")
    try:
        resp = httpx.post(url, json=source.model_dump(mode="json"), headers={"X-Service-Key": settings.service_key},
                          timeout=httpx.Timeout(settings.kb_publish_timeout_s))
    except httpx.TimeoutException as exc:
        log.warning("KB publish: voice runtime timed out after %ss", settings.kb_publish_timeout_s)
        raise PublishError(502, "upstream_error", "The voice runtime did not answer in time", retryable=True) from exc
    except httpx.HTTPError as exc:
        log.warning("KB publish: voice runtime unreachable (%s)", type(exc).__name__)
        raise PublishError(502, "upstream_error", "The voice runtime is unreachable", retryable=True) from exc

    if resp.status_code == 422:
        message, details = _problems(resp)
        raise PublishError(422, "validation_error", message, details)
    if resp.status_code != 200:
        log.warning("KB publish: voice runtime answered HTTP %s", resp.status_code)
        raise PublishError(502, "upstream_error", f"The voice runtime answered HTTP {resp.status_code}",
                           retryable=resp.status_code >= 500)
    try:
        return KBVersionInfo.model_validate(resp.json())
    except (ValueError, ValidationError) as exc:
        raise PublishError(502, "upstream_error", "The voice runtime returned an invalid KBVersionInfo") from exc
