"""Audit logging helpers."""
from typing import Optional

from sqlalchemy.orm import Session

from .orm import AuditLog
from .timeutil import now_utc


def write_audit(
    db: Session,
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    details: Optional[dict] = None,
    commit: bool = True,
):
    """Write an audit log entry. commit=False leaves it in the caller's transaction."""
    entry = AuditLog(
        actor=actor,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details or {},
        at=now_utc()
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
