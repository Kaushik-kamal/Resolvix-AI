"""Configuration routes (departments, urgency rules)."""
from fastapi import APIRouter, Depends
from resolvix_contracts import DepartmentsConfig

from ..deps import get_principal, Principal, get_settings
from ..config import Settings
from ..privacy import mask_number

router = APIRouter(prefix="/v1", tags=["config"])


@router.get("/departments")
def get_departments(
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings)
):
    """Get departments configuration."""
    # Load from app state (cached at startup)
    from fastapi import Request
    # We need access to request.app.state, so use a different approach
    # For now, reload from file (will optimize later)
    import yaml
    departments_path = settings.resolve_path(settings.departments_file)
    with open(departments_path, "r", encoding="utf-8") as f:
        departments_raw = yaml.safe_load(f)
    config = DepartmentsConfig.model_validate(departments_raw)
    if principal.kind == "user" and principal.role != "admin":
        # staff mobiles: the dashboard only needs to know that numbers exist
        config = config.model_copy(update={
            "departments": [d.model_copy(update={
                "transfer_numbers": [mask_number(n) or "" for n in d.transfer_numbers],
                "sms_alert_numbers": [mask_number(n) or "" for n in d.sms_alert_numbers]}) for d in config.departments],
            "emergency": {k: ([mask_number(n) or "" for n in v] if k != "public_numbers" else v)
                          for k, v in config.emergency.items()},
        })
    return config


@router.get("/urgency-rules")
async def get_urgency_rules(
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings)
):
    """Get urgency rules (read-only view)."""
    import yaml
    urgency_rules_path = settings.resolve_path(settings.urgency_rules_file)
    with open(urgency_rules_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
