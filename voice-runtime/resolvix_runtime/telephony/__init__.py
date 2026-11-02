from __future__ import annotations

from .base import TelephonyAdapter
from .mock import MockTelephony
from .agora import AgoraTelephony
from ..config import RuntimeSettings


def get_telephony_adapter(settings: RuntimeSettings) -> TelephonyAdapter:
    if settings.telephony_mode == "agora" and settings.agora_app_id:
        return AgoraTelephony(settings)
    return MockTelephony(transfer_success=settings.telephony_transfer_success)


__all__ = ["TelephonyAdapter", "MockTelephony", "AgoraTelephony", "get_telephony_adapter"]
