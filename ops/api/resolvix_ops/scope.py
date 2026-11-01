"""Department scoping for staff (PRD P1-07).

Staff see only their department's tickets, gap clusters and the calls that produced those tickets; admins and the
service principal see everything. A record outside the scope answers 404 (its existence is not revealed).
Calls cannot be attributed to a department before a ticket exists, so call.* stream events are not sent to staff.
STAFF_SCOPE_ENABLED=false restores the unscoped M2 behaviour.
"""
from .deps import Principal


def scope_department(principal: Principal, settings) -> str | None:
    """None = unrestricted; otherwise the department key the principal is limited to ("" matches nothing)."""
    if not settings.staff_scope_enabled:
        return None
    if principal.kind == "user" and principal.role == "staff":
        return principal.department or ""
    return None


def event_visible(department: str | None, event_name: str, data: dict) -> bool:
    """Whether a stream event may be delivered to a subscriber limited to `department` (None = everything)."""
    if department is None:
        return True
    if event_name.startswith("call."):
        return False
    if event_name in {"ticket.created", "ticket.updated", "alert.p1"}:
        return data.get("department") == department
    if event_name == "gap.created":
        return data.get("department_guess") == department
    return False
