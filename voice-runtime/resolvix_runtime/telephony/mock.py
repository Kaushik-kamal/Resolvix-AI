from __future__ import annotations

import logging
import uuid
from .base import TelephonyAdapter

logger = logging.getLogger(__name__)


class MockTelephony(TelephonyAdapter):
    """Mock telephony adapter for offline testing and simulated transfer environments."""

    def __init__(self, transfer_success: bool = True) -> None:
        self.transfer_success = transfer_success
        self.transfers_attempted: list[tuple[str, str]] = []
        self.outbound_calls: list[tuple[str, str]] = []

    async def transfer(self, call_id: str, to_number: str) -> bool:
        logger.info(
            "MockTelephony.transfer(call_id=%s, to_number=%s) -> %s",
            call_id,
            to_number,
            self.transfer_success,
        )
        self.transfers_attempted.append((call_id, to_number))
        return self.transfer_success

    async def outbound_call(self, to_number: str, call_id: str) -> str:
        call_ref = f"mock-out-{uuid.uuid4().hex[:8]}"
        logger.info(
            "MockTelephony.outbound_call(to_number=%s, call_id=%s) -> %s",
            to_number,
            call_id,
            call_ref,
        )
        self.outbound_calls.append((to_number, call_id))
        return call_ref
