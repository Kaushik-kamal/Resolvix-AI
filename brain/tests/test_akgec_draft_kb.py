"""The draft AKGEC knowledge base (data/kb.jsonl) and its eval sets (eval/akgec/): guardrails that must keep holding.

Nothing here approves or publishes an entry: the KB stays ``status=draft`` and the Brain ignores drafts."""
from __future__ import annotations

import collections
import hashlib
import json
import re
import subprocess
import sys

from resolvix_contracts.models import KBEntry

from conftest import ROOT

BRAIN = ROOT / "brain"
KB = BRAIN / "data" / "kb.jsonl"
SETS = BRAIN / "eval" / "akgec"


def _rows(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_every_entry_is_a_valid_unique_draft_from_akgec_pages():
    entries = [KBEntry.model_validate(r) for r in _rows(KB)]
    assert len(entries) == 21 and len({e.id for e in entries}) == 21
    assert {e.status for e in entries} == {"draft"}
    assert all(e.source_ref and "akgec.ac.in" in e.source_ref for e in entries)


def test_no_personal_data_or_instructions_in_the_kb():
    text = KB.read_text(encoding="utf-8")
    assert "@" not in text and not re.search(r"\d{10}", text.replace(",", ""))            # no emails, no phone/roll numbers
    assert not re.search(r"ignore (all )?previous|system prompt|you are now", text, re.I)


def test_the_brain_ignores_the_draft_kb(tmp_path):
    from resolvix_brain.kb import load_entries
    from resolvix_contracts.models import KBSource
    entries = load_entries(KBSource(kind="file", location=str(KB)))
    approved = [e for e in entries if e.status == "approved"]
    assert approved == []                                         # nothing is live until staff approve


def test_eval_sets_only_reference_real_entries_and_cover_all_of_them():
    ids = {r["id"] for r in _rows(KB)}
    ans = _rows(SETS / "answerable.jsonl")
    assert all(r["expected_kb_ids"][0] in ids and r["must_contain"] for r in ans)
    per = collections.Counter(r["expected_kb_ids"][0] for r in ans)
    assert set(per) == ids and min(per.values()) >= 2            # every entry has at least two phrasings (en + romanised hi)
    assert {r["lang"] for r in ans} >= {"en", "hinglish"}
    ab = _rows(SETS / "abstain.jsonl")
    assert len(ab) >= 20 and not any("expected_kb_ids" in r for r in ab)
    texts = " ".join(r["text"].lower() for r in ab)
    assert "fee" in texts and "library" in texts and "bus" in texts   # fee, timings and transport questions must abstain


def test_cli_eval_on_the_draft_kb_uses_a_temporary_copy_and_never_touches_the_file():
    before = hashlib.sha256(KB.read_bytes()).hexdigest()
    r = subprocess.run([sys.executable, "-m", "resolvix_brain", "eval", "--mock", "--lexical", "--kb-set", "akgec-draft"],
                       capture_output=True, text=True, cwd=BRAIN, timeout=300, env={**__import__("os").environ, "PYTHONUTF8": "1"})
    assert r.returncode == 2, r.stdout + r.stderr                 # deterministic/proxy targets met; LLM not verified
    assert "DRAFT AKGEC KB" in r.stdout and "answerable" in r.stdout and "abstain" in r.stdout
    assert not [l for l in r.stdout.splitlines() if l.startswith("  FAIL")], r.stdout
    assert hashlib.sha256(KB.read_bytes()).hexdigest() == before
    assert {x["status"] for x in _rows(KB)} == {"draft"}
