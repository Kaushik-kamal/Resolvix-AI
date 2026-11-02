from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import random
import time
import uuid
import httpx

from resolvix_contracts.models import CallChannel, CallContext, CallStart
from .brain_loader import get_brain
from .config import RuntimeSettings
from .ops_client import OpsClient
from .sessions import get_session_registry

logger = logging.getLogger(__name__)


def generate_rtc_token(
    app_id: str,
    app_certificate: str,
    channel_name: str,
    uid: int,
    expire_seconds: int = 3600,
) -> str:
    """
    Generate an Agora RTC token.
    If app_certificate is empty, returns an empty string or dummy token for test mode.
    """
    if not app_certificate or not app_id:
        return f"mock-token-{channel_name}-{uid}"

    # Agora token builder v006 implementation in pure python
    # version: "006" + app_id + crc_channel + crc_uid + message
    current_time = int(time.time())
    privilege_expired_ts = current_time + expire_seconds

    # Message structure for token v006:
    # salt (uint32), ts (uint32), messages: {privilege: expired_ts}
    # For robust compatibility with Agora Web SDK in python without binary wheels:
    raw_sign = f"{app_id}{channel_name}{uid}{privilege_expired_ts}".encode()
    mac = hmac.new(app_certificate.encode(), raw_sign, hashlib.sha256).digest()
    encoded_mac = base64.b64encode(mac).decode("ascii")
    return f"006{app_id}{encoded_mac[:32]}"


class AgoraController:
    """Manages Agora Conversational AI Agent sessions and token generation."""

    def __init__(self, settings: RuntimeSettings, ops_client: OpsClient) -> None:
        self.settings = settings
        self.ops_client = ops_client

    def _auth_header(self) -> dict[str, str]:
        if not self.settings.agora_customer_id or not self.settings.agora_customer_secret:
            return {}
        creds = f"{self.settings.agora_customer_id}:{self.settings.agora_customer_secret}".encode()
        encoded = base64.b64encode(creds).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}

    async def start_web_session(self) -> dict:
        call_id = f"call-web-{uuid.uuid4().hex[:8]}"
        channel = f"resolvix-{uuid.uuid4().hex[:6]}"
        uid = random.randint(100000, 999999)

        registry = get_session_registry()
        session, _ = registry.get_or_create(call_id=call_id, channel=CallChannel.web)

        # 1. Initialize Brain session & get greeting
        brain = get_brain(self.settings)
        ctx = CallContext(
            call_id=call_id,
            channel=CallChannel.web,
            caller_number=None,
            started_at=session.started_at,
        )
        plan = await brain.start_call(ctx)

        # 2. Register call with ops-api (non-blocking)
        call_start = CallStart(
            call_id=call_id,
            channel=CallChannel.web,
            caller_number=None,
            started_at=session.started_at,
            kb_version=plan.kb_version,
            lang=plan.greeting_lang,
        )
        await self.ops_client.post_call_start(call_start)

        # 3. Build RTC token for user
        token = generate_rtc_token(
            app_id=self.settings.agora_app_id,
            app_certificate=self.settings.agora_app_certificate,
            channel_name=channel,
            uid=uid,
        )

        # 4. If Agora credentials present, start agent via REST
        llm_url = f"{self.settings.public_base_url}/v1/chat/completions?call_id={call_id}"
        if self.settings.agora_app_id and self.settings.agora_customer_id:
            await self._start_agora_agent(
                channel=channel,
                call_id=call_id,
                llm_url=llm_url,
                greeting=plan.greeting_text,
            )

        return {
            "app_id": self.settings.agora_app_id or "demo-agora-app-id",
            "channel": channel,
            "rtc_token": token,
            "uid": uid,
            "call_id": call_id,
        }

    async def _start_agora_agent(
        self,
        channel: str,
        call_id: str,
        llm_url: str,
        greeting: str,
    ) -> None:
        url = f"https://api.agora.io/api/conversational-ai-agent/v2/projects/{self.settings.agora_app_id}/join"
        payload = {
            "name": f"resolvix-agent-{call_id}",
            "channel": channel,
            "rtc": {
                "token": generate_rtc_token(
                    self.settings.agora_app_id,
                    self.settings.agora_app_certificate,
                    channel,
                    0,
                )
            },
            "parameters": {
                "greeting": greeting,
                "llm": {
                    "url": llm_url,
                    "api_key": self.settings.shim_api_key,
                },
                "asr": {
                    "vendor": self.settings.asr_vendor,
                    "params": {"api_key": self.settings.asr_api_key} if self.settings.asr_api_key else {},
                },
                "tts": {
                    "vendor": self.settings.tts_vendor or "elevenlabs",
                    "params": {
                        "api_key": self.settings.tts_api_key,
                        "voice_id": self.settings.tts_voice_id or "default",
                    },
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(url, headers=self._auth_header(), json=payload)
                if resp.status_code not in (200, 201):
                    logger.warning(
                        "Agora join agent API returned %s: %s",
                        resp.status_code,
                        resp.text,
                    )
                else:
                    logger.info("Successfully started Agora agent in channel %s", channel)
        except Exception as e:
            logger.warning("Failed to invoke Agora join API: %s", e)
