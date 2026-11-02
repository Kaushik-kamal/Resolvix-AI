from __future__ import annotations

import base64
import logging
import uuid
import httpx
from .base import TelephonyAdapter
from ..config import RuntimeSettings

logger = logging.getLogger(__name__)


class AgoraTelephony(TelephonyAdapter):
    """Telephony adapter using Agora REST APIs (per Spike S1 findings)."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self.app_id = settings.agora_app_id
        self.customer_id = settings.agora_customer_id
        self.customer_secret = settings.agora_customer_secret
        self.base_url = "https://api.agora.io"

    def _auth_header(self) -> dict[str, str]:
        if not self.customer_id or not self.customer_secret:
            return {}
        creds = f"{self.customer_id}:{self.customer_secret}".encode()
        encoded = base64.b64encode(creds).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}

    async def transfer(self, call_id: str, to_number: str) -> bool:
        """
        In Agora Conversational AI v2, transferring to an external PSTN number requires either
        a SIP Refer action on an active trunk or invoking the transfer REST action.
        If credentials or SIP gateway are unconfigured, logs and returns False so fallback line speaks.
        """
        logger.info("AgoraTelephony: attempting transfer call_id=%s to %s", call_id, to_number)
        if not self.customer_id or not self.app_id:
            logger.warning("Agora credentials missing; marking transfer as failed to trigger fallback line.")
            return False

        url = f"{self.base_url}/api/conversational-ai-agent/v2/projects/{self.app_id}/calls/{call_id}/transfer"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(
                    url,
                    headers=self._auth_header(),
                    json={"to_number": to_number},
                )
                if resp.status_code in (200, 202):
                    return True
                logger.error("Agora transfer failed status=%s response=%s", resp.status_code, resp.text)
                return False
        except Exception as e:
            logger.error("Agora transfer network error: %s", e)
            return False

    async def outbound_call(self, to_number: str, call_id: str) -> str:
        """Call Agora Conversational AI outbound-call API."""
        logger.info("AgoraTelephony: starting outbound call to %s for call_id=%s", to_number, call_id)
        if not self.customer_id or not self.app_id:
            logger.warning("Agora credentials missing; returning simulated call id.")
            return f"agora-sim-{uuid.uuid4().hex[:8]}"

        url = f"{self.base_url}/api/conversational-ai-agent/v2/projects/{self.app_id}/call"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(
                    url,
                    headers=self._auth_header(),
                    json={
                        "to_number": to_number,
                        "call_id": call_id,
                        "llm_url": f"{self.settings.public_base_url}/v1/chat/completions?call_id={call_id}",
                    },
                )
                if resp.status_code in (200, 201, 202):
                    data = resp.json()
                    return str(data.get("call_id") or data.get("id") or call_id)
                logger.error("Agora outbound call API returned %s: %s", resp.status_code, resp.text)
                return f"agora-err-{uuid.uuid4().hex[:8]}"
        except Exception as e:
            logger.error("Agora outbound call error: %s", e)
            return f"agora-err-{uuid.uuid4().hex[:8]}"
