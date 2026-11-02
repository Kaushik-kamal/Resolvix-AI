"""Ingest script, CLI entry points and the Member A / Member C integration surface."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from conftest import ROOT, make_settings
from resolvix_contracts import Brain
from resolvix_contracts.models import KBEntry, KBSource

BRAIN = ROOT / "brain"


def _load_ingest():
    spec = importlib.util.spec_from_file_location("ingest_raw", BRAIN / "scripts" / "ingest_raw.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ingest_csv_marks_everything_draft_and_reports_gaps(tmp_path):
    m = _load_ingest()
    csv = tmp_path / "raw.csv"
    csv.write_text("question,answer,department,source\n"
                   "hostel mess timing | khana kab milta hai,Mess is open 7 to 9 am,hostel,Hostel Rules p.2\n"
                   "late fee kitni hai,A fine of 100 rupees per day until 15 January 2027,,\n"
                   "only a question,,hostel,x\n", encoding="utf-8")
    out = tmp_path / "kb.jsonl"
    assert m.main([str(csv), "--out", str(out)]) == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == ["HST-001", "FEE-001"] and all(r["status"] == "draft" for r in rows)
    assert rows[0]["question_variants"] == ["hostel mess timing", "khana kab milta hai"]
    review = (tmp_path / "kb_review.md").read_text(encoding="utf-8")
    assert "skipped" in review and "no source document" in review and "valid_until" in review and "no Hindi answer" in review
    for r in rows:
        KBEntry.model_validate(r)


def test_ingest_markdown_blocks(tmp_path):
    m = _load_ingest()
    md = tmp_path / "faq.md"
    md.write_text("Q: Library timing?\nA: Open 9 to 5.\nDept: helpdesk\nSource: Booklet\n\nQ: Exam date?\nA: 8 December.\n", encoding="utf-8")
    rows = m.read_rows(md)
    assert len(rows) == 2 and rows[0]["department"] == "helpdesk" and rows[1]["answer"] == "8 December."


def run_cli(*args, env_extra=None):
    import os
    env = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "resolvix_brain", *args], capture_output=True, text=True, cwd=BRAIN, env=env,
                          timeout=300)


def test_cli_compile_prints_versioninfo_and_fails_cleanly():
    r = run_cli("compile", "--lexical")
    assert r.returncode == 0 and json.loads(r.stdout)["entry_count"] in (11, 12)
    r = run_cli("compile", "--lexical", "--source", str(BRAIN / "nope.jsonl"))
    assert r.returncode == 1 and "file not found" in r.stderr


def test_cli_chat_in_mock_mode_pipes_through_events():
    import os
    env = {**os.environ, "PYTHONUTF8": "1"}
    p = subprocess.run([sys.executable, "-m", "resolvix_brain", "chat", "--mock", "--lexical"], input="hostel gate timing\n/quit\n",
                       capture_output=True, text=True, cwd=BRAIN, env=env, timeout=300)
    assert p.returncode == 0 and '"type":"meta"' in p.stdout.replace(" ", "") and "Hostel Rules" in p.stdout


def test_cli_eval_deterministic_sets_pass_with_lexical_embedder():
    r = run_cli("eval", "--mock", "--lexical", "--set", "safety,human,urgency,robustness")
    assert r.returncode == 2, r.stdout                        # 2 = deterministic targets met, LLM sets not verified
    assert not [l for l in r.stdout.splitlines() if l.startswith("  FAIL")], r.stdout
    assert "safety" in r.stdout and "100%" in r.stdout


# ----------------------------------------------------------------- Member A / C integration surface
def test_public_interface_exactly_as_the_prompt_specifies(monkeypatch):
    for k, v in {"LLM_MODE": "mock", "EMBED_MODE": "lexical"}.items():
        monkeypatch.setenv(k, v)
    from resolvix_brain import BrainSettings, create_brain
    brain = create_brain(BrainSettings.from_env())
    assert isinstance(brain, Brain)
    for name in ("start_call", "handle_turn", "end_call", "reload_kb", "health"):
        assert callable(getattr(brain, name))


def test_settings_repr_never_leaks_the_key(monkeypatch):
    from resolvix_brain import BrainSettings
    s = BrainSettings.from_env({"GROQ_API_KEY": "gsk_abcdef"})
    assert "gsk_abcdef" not in repr(s) and s.groq_api_key == "gsk_abcdef"


async def test_member_c_kbexport_is_consumable_and_drafts_are_ignored(tmp_path, brain):
    export = json.loads((ROOT / "contracts" / "kb" / "sample_kb_export.json").read_text(encoding="utf-8"))
    assert {"version_label", "exported_at", "entries"} <= set(export)
    export["entries"][0]["status"] = "draft"                   # C only exports approved, but B must still not trust it
    p = tmp_path / "export.json"
    p.write_text(json.dumps(export), encoding="utf-8")
    info = await brain.reload_kb(KBSource(kind="file", location=str(p)))
    assert info.entry_count == len(export["entries"]) - 1 and any("status=draft" in w for w in info.warnings)
