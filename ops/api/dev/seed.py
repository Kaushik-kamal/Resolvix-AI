"""Seed the Ops API database: approved sample KB entries, one draft "bus route" entry and the demo users.

Run with: python -X utf8 dev/seed.py [--database-url sqlite:///./data/other.db]
Settings come from ops/api/.env (run it from anywhere; paths resolve against ops/api like the API itself).

Idempotent and non-destructive: an entry that already exists (any status, edited or not) is never touched, users are
only seeded into an empty users table (existing behaviour of seed_users_if_needed), nothing is ever duplicated.
Works against an empty database and before uvicorn starts; it uses the app's own modules, no HTTP.
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEV_DIR = Path(__file__).resolve().parent
OPS_API_DIR = DEV_DIR.parent
if str(OPS_API_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_API_DIR))

import yaml  # noqa: E402
from resolvix_contracts import DepartmentsConfig, KBEntry  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from resolvix_ops.config import Settings  # noqa: E402
from resolvix_ops.db import create_db_engine, get_session_factory  # noqa: E402
from resolvix_ops.orm import Base, KBEntryDB, User  # noqa: E402
from resolvix_ops.seed_users import seed_users_if_needed  # noqa: E402
from resolvix_ops.timeutil import now_utc  # noqa: E402

SAMPLE_KB = OPS_API_DIR.parent.parent / "contracts" / "kb" / "sample_kb.jsonl"
SEED_ACTOR = "seed"

# The demo's self-healing moment: callers ask about the Noida bus route, the KB has nothing, a gap is logged, staff
# approve this draft, publish, and the next call is answered. Demo text, not a real timetable.
BUS_ROUTE_DRAFT = {
    "id": "BUS-001",
    "department": "transport",
    "question_variants": [
        "Noida sector 62 ke liye bus route kya hai",
        "college bus route Noida Sector 62",
        "bus kahan se milegi Noida sector 62 ke liye",
    ],
    "answer_en": "The college bus to Noida Sector 62 leaves from the main gate at 7:30 am and returns from Sector 62 "
                 "at 5:00 pm on working days. Contact the Transport Office for the stop list.",
    "answer_hi": "Noida Sector 62 ki college bus subah 7:30 baje main gate se chalti hai aur shaam 5:00 baje "
                 "Sector 62 se wapas aati hai. Stops ki list ke liye Transport Office se poochiye.",
    "source_title": "Transport Office Notice (demo draft)",
    "source_ref": "bus route sheet",
    "valid_from": None,
    "valid_until": None,
    "tags": ["transport", "bus"],
    "is_faq": False,
    "status": "draft",
}


@dataclass
class SeedResult:
    kb_inserted: int = 0
    kb_existing: int = 0
    kb_total: int = 0
    kb_approved: int = 0
    kb_draft: int = 0
    users_total: int = 0

    def summary(self) -> str:
        return (f"KB entries: {self.kb_inserted} added, {self.kb_existing} already present "
                f"({self.kb_total} total: {self.kb_approved} approved, {self.kb_draft} draft); "
                f"users: {self.users_total}")


def sample_entries() -> list[KBEntry]:
    """sample_kb.jsonl (read only) forced to approved, followed by the draft bus route entry."""
    entries = []
    for line in SAMPLE_KB.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(KBEntry.model_validate(json.loads(line)).model_copy(update={"status": "approved"}))
    entries.append(KBEntry.model_validate(BUS_ROUTE_DRAFT))
    return entries


def _department_keys(settings: Settings) -> set[str]:
    raw = yaml.safe_load(settings.resolve_path(settings.departments_file).read_text(encoding="utf-8"))
    return {d.key for d in DepartmentsConfig.model_validate(raw).departments}


def seed_kb(session_factory: sessionmaker) -> tuple[int, int]:
    """Insert missing entries only. Returns (inserted, already_present)."""
    inserted = existing = 0
    now = now_utc()
    with session_factory() as db:
        for entry in sample_entries():
            if db.get(KBEntryDB, entry.id) is not None:
                existing += 1
                continue
            db.add(KBEntryDB(
                id=entry.id, department=entry.department, status=entry.status,
                body_json=entry.model_dump(mode="json"), flagged=False,
                created_at=now, updated_at=now, updated_by=SEED_ACTOR))
            inserted += 1
        db.commit()
    return inserted, existing


def seed(settings: Settings | None = None, session_factory: sessionmaker | None = None, *,
         include_users: bool = True) -> SeedResult:
    """Seed KB entries and users.

    Pass `settings` (builds and disposes its own engine), or a `session_factory` of an existing app
    (`app.state.session_factory`); with a session factory and no settings, users are skipped.
    """
    if settings is None and session_factory is None:
        settings = Settings(_env_file=OPS_API_DIR / ".env")
    engine = None
    if session_factory is None:
        engine = create_db_engine(settings)
        session_factory = get_session_factory(engine)
    try:
        Base.metadata.create_all(bind=session_factory.kw["bind"])
        result = SeedResult()
        result.kb_inserted, result.kb_existing = seed_kb(session_factory)
        if include_users and settings is not None:
            with session_factory() as db:
                seed_users_if_needed(db, settings, _department_keys(settings))
        with session_factory() as db:
            result.kb_total = db.query(KBEntryDB).count()
            result.kb_approved = db.query(KBEntryDB).filter(KBEntryDB.status == "approved").count()
            result.kb_draft = db.query(KBEntryDB).filter(KBEntryDB.status == "draft").count()
            result.users_total = db.query(User).count()
        return result
    finally:
        if engine is not None:
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", default=None, help="override DATABASE_URL (default: from .env)")
    args = parser.parse_args(argv)
    os.chdir(OPS_API_DIR)  # relative sqlite paths resolve like they do when uvicorn runs from ops/api
    settings = Settings(_env_file=OPS_API_DIR / ".env")
    if args.database_url:
        settings = settings.model_copy(update={"database_url": args.database_url})
    result = seed(settings)
    print(result.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
