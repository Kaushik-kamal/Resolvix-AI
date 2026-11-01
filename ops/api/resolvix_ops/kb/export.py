"""Export: approved entries valid today (Asia/Kolkata), as a KBExport."""
import hashlib
from datetime import date

from sqlalchemy.orm import Session

from resolvix_contracts import KBEntry, KBExport

from ..orm import KBEntryDB
from ..timeutil import iso_utc


def is_current(entry: KBEntry, today: date) -> bool:
    """valid_from <= today <= valid_until, inclusive; a null bound is open-ended."""
    return (entry.valid_from is None or entry.valid_from <= today) and (
        entry.valid_until is None or today <= entry.valid_until)


def exportable(db: Session, today: date) -> list[tuple[KBEntryDB, KBEntry]]:
    rows = db.query(KBEntryDB).filter(KBEntryDB.status == "approved").order_by(KBEntryDB.id).all()
    out = []
    for row in rows:
        entry = KBEntry.model_validate({**row.body_json, "status": "approved"})
        if is_current(entry, today):
            out.append((row, entry))
    return out


def version_label(today: date, items: list[tuple[KBEntryDB, KBEntry]]) -> str:
    """Deterministic: date + 8 hex of sha256 over (id, updated_at) pairs; changes when the set or any entry changes."""
    digest = hashlib.sha256("\n".join(f"{r.id}@{iso_utc(r.updated_at)}" for r, _ in items).encode("utf-8")).hexdigest()
    return f"{today.strftime('%Y%m%d')}-{digest[:8]}"


def build_export(db: Session, clock) -> KBExport:
    today = clock.today_ist()
    items = exportable(db, today)
    return KBExport(version_label=version_label(today, items), exported_at=clock.now(),
                    entries=[e for _, e in items])
