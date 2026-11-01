"""Entry persistence shared by POST /v1/kb/entries and POST /v1/kb/import."""
from sqlalchemy.orm import Session

from resolvix_contracts import KBEntry

from ..orm import KBEntryDB
from ..timeutil import iso_utc, now_utc
from .scan import is_suspicious


def save_draft(db: Session, entry: KBEntry, actor: str, keep_status: bool = False) -> tuple[KBEntryDB, bool, bool]:
    """Upsert `entry` as a draft (whatever status it carried), re-running the injection scan.

    keep_status=True (admin bulk import, per ops-api.yaml "entries keep their status field") stores the status the
    line carries, but only for entries that pass the scan; a flagged entry is always a draft.

    Returns (row, flagged, created). The caller commits. A clean save clears an earlier flag.
    """
    stored = entry.model_copy(update={"status": "draft"})
    body = stored.model_dump(mode="json")
    flagged = is_suspicious(body)
    if keep_status and not flagged and entry.status != "draft":
        stored = entry.model_copy()
        body = stored.model_dump(mode="json")
    now = now_utc()
    row = db.get(KBEntryDB, stored.id)
    created = row is None
    if created:
        row = KBEntryDB(id=stored.id, created_at=now)
        db.add(row)
    row.department = stored.department
    row.status = stored.status
    row.body_json = body
    row.flagged = flagged
    row.updated_at = now
    row.updated_by = actor
    return row, flagged, created


def entry_dict(row: KBEntryDB) -> dict:
    """The stored KBEntry as JSON, with status taken from the authoritative column."""
    return {**row.body_json, "status": row.status}


def entry_meta(row: KBEntryDB) -> dict:
    return {"flagged": bool(row.flagged), "updated_at": iso_utc(row.updated_at), "updated_by": row.updated_by}
