"""Health and status endpoint."""
from fastapi import APIRouter, Depends

from resolvix_contracts import CONTRACT_VERSION
from ..deps import get_settings
from ..config import Settings

router = APIRouter()


@router.get("/healthz")
async def health_check(settings: Settings = Depends(get_settings)):
    """Public health check endpoint (no auth required)."""
    return {
        "status": "ok",
        "contract_version": CONTRACT_VERSION,
        "notify_mode": settings.sms_result_mode,  # contract: mock | live
        "runtime_mode": settings.runtime_mode
    }
