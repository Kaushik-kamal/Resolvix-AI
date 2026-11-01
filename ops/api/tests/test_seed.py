"""dev/seed.py: counts, idempotency, non-destructiveness, empty DB, CLI output."""
import importlib.util
import json
from pathlib import Path

import pytest
from resolvix_contracts import KBEntry
from resolvix_ops.app import create_app
from resolvix_ops.config import Settings
from resolvix_ops.orm import KBEntryDB, User

DEV_DIR = Path(__file__).parent.parent / "dev"
SAMPLE_KB = Path(__file__).parent.parent.parent.parent / "contracts" / "kb" / "sample_kb.jsonl"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"dev_{name}", DEV_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed_mod = _load("seed")


@pytest.fixture
def seeded(test_settings):
    """Run seed() against an empty temp DB (no app started) and return (settings, result)."""
    settings = test_settings.model_copy(update={"seed_users_on_startup": False})
    return settings, seed_mod.seed(settings)


def _rows(settings):
    app = create_app(settings)  # only for its engine/session factory; the lifespan is not started
    try:
        with app.state.session_factory() as db:
            return {r.id: r for r in db.query(KBEntryDB).all()}, db.query(User).count()
    finally:
        app.state.engine.dispose()


def test_empty_db_gets_sample_kb_draft_and_users(seeded):
    settings, result = seeded
    sample_count = len([line for line in SAMPLE_KB.read_text(encoding="utf-8").splitlines() if line.strip()])
    assert result.kb_inserted == sample_count + 1 and result.kb_existing == 0
    assert result.kb_approved == sample_count and result.kb_draft == 1
    assert result.users_total == 4
    rows, users = _rows(settings)
    assert len(rows) == sample_count + 1 and users == 4
    for row in rows.values():
        assert row.updated_by == "seed" and row.flagged is False
        entry = KBEntry.model_validate(row.body_json)  # body is a valid KBEntry
        assert entry.id == row.id and entry.status == row.status and entry.department == row.department


def test_sample_entries_are_approved_and_bus_route_is_draft_transport(seeded):
    rows, _ = _rows(seeded[0])
    bus = rows["BUS-001"]
    assert bus.status == "draft" and bus.department == "transport" and bus.body_json["status"] == "draft"
    sample_ids = {json.loads(line)["id"] for line in SAMPLE_KB.read_text(encoding="utf-8").splitlines() if line.strip()}
    assert sample_ids <= set(rows)
    assert all(rows[i].status == "approved" for i in sample_ids)


def test_second_run_changes_nothing(seeded):
    settings, first = seeded
    second = seed_mod.seed(settings)
    assert second.kb_inserted == 0 and second.kb_existing == first.kb_total
    assert second.kb_total == first.kb_total and second.users_total == first.users_total
    rows, users = _rows(settings)
    assert len(rows) == first.kb_total and users == 4


def test_never_overwrites_edited_or_approved_entries(seeded):
    settings, _ = seeded
    app = create_app(settings)
    try:
        with app.state.session_factory() as db:
            fee = db.get(KBEntryDB, "FEE-001")
            body = dict(fee.body_json, answer_en="Staff edited this answer.")
            fee.body_json, fee.updated_by = body, "staff@x"
            bus = db.get(KBEntryDB, "BUS-001")
            bus.status, bus.body_json = "approved", dict(bus.body_json, status="approved")
            db.get(KBEntryDB, "EXM-001").status = "archived"
            db.commit()
        seed_mod.seed(settings)
        with app.state.session_factory() as db:
            assert db.get(KBEntryDB, "FEE-001").body_json["answer_en"] == "Staff edited this answer."
            assert db.get(KBEntryDB, "FEE-001").updated_by == "staff@x"
            assert db.get(KBEntryDB, "BUS-001").status == "approved"
            assert db.get(KBEntryDB, "EXM-001").status == "archived"
    finally:
        app.state.engine.dispose()


def test_seed_fills_only_missing_entries(seeded):
    settings, first = seeded
    app = create_app(settings)
    try:
        with app.state.session_factory() as db:
            db.delete(db.get(KBEntryDB, "HST-002"))
            db.commit()
    finally:
        app.state.engine.dispose()
    result = seed_mod.seed(settings)
    assert result.kb_inserted == 1 and result.kb_total == first.kb_total


def test_seed_with_session_factory_of_a_running_app(ops_app):
    """Works against the app's own session factory (users already seeded by startup, so none added)."""
    result = seed_mod.seed(session_factory=ops_app.state.session_factory)
    assert result.kb_inserted == 13 and result.kb_draft == 1 and result.users_total == 4
    again = seed_mod.seed(session_factory=ops_app.state.session_factory)
    assert again.kb_inserted == 0


def test_users_not_reseeded_when_present(seeded):
    settings, _ = seeded
    app = create_app(settings)
    try:
        with app.state.session_factory() as db:
            db.query(User).filter(User.email == "hostel@demo").delete()
            db.commit()
    finally:
        app.state.engine.dispose()
    # existing behaviour of seed_users_if_needed: only an empty users table is seeded
    assert seed_mod.seed(settings).users_total == 3


def test_cli_prints_counts_but_no_secrets(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SERVICE_KEY", "cli-secret-service-key-9999")
    monkeypatch.setenv("SESSION_SECRET", "cli-secret-session-secret-needs-32-chars-ok")
    monkeypatch.setenv("SEED_PASSWORD", "CliSecretPassword!77")
    cwd = Path.cwd()
    try:
        code = seed_mod.main(["--database-url", f"sqlite:///{tmp_path / 'cli.db'}"])
    finally:
        import os
        os.chdir(cwd)
    out = capsys.readouterr().out
    assert code == 0 and "13 added" in out and "users: 4" in out
    for secret in ("cli-secret", "CliSecretPassword"):
        assert secret not in out
