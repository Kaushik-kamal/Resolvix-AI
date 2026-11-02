"""Entries expire by date, but the KB is compiled once. These tests simulate the clock passing midnight *without* a reload:
an expired entry must never be spoken (FAQ cache or LLM citation), and the first turn of the new day triggers a refresh."""
from __future__ import annotations

import asyncio
import dataclasses
from datetime import date

from conftest import Caller, done, make_settings, speech, actions
from resolvix_brain.brain import ResolvixBrain
from resolvix_brain.embeddings import LexicalEmbedder

LAST_DAY = date(2026, 11, 30)       # FEE-001 has valid_until 2026-11-30
NEXT_DAY = date(2026, 12, 1)


async def make(today: date):
    b = ResolvixBrain(dataclasses.replace(make_settings(), today_override=today), embedder=LexicalEmbedder())
    await b.ready()
    return b


async def test_faq_entry_is_not_served_after_its_last_valid_day_even_without_a_reload():
    b = await make(LAST_DAY)
    ok = await Caller(b, "x1", "+919000000001").say("fees kab tak jama karni hai")
    assert done(ok).path == "faq" and "30 November" in speech(ok)
    version_before = b.health()["kb_version"]
    b._refreshing = True                                  # block the background refresh: isolate the per-answer check
    b.s.today_override = NEXT_DAY                         # midnight passes
    ev = await Caller(b, "x2", "+919000000001").say("fees kab tak jama karni hai")
    assert b.health()["kb_version"] == version_before     # still the old compiled KB...
    assert done(ev).path != "faq" and "30 November" not in speech(ev) and done(ev).kb_ids != ["FEE-001"]   # ...but not served
    await b.aclose()


async def test_llm_citation_of_an_expired_entry_is_rejected():
    b = await make(LAST_DAY)
    b._refreshing = True
    b.s.today_override = NEXT_DAY
    b.llm_client.queue.append('<meta>{"tier":"confident","kb_ids":["FEE-001"],"lang":"hinglish","intent":"faq"}</meta>\n'
                              "Last date 30 November hai, Fee Notice ke mutabik.")
    ev = await Caller(b, "x3", "+919000000001").say("semester fee ka deadline batao please abhi")
    s = done(ev)
    assert "citation_invalid" in s.validator_flags and "30 November" not in speech(ev) and s.rule_id == "R-UNANSWERED"
    await b.aclose()


async def test_first_turn_of_a_new_day_recompiles_the_kb_in_the_background():
    b = await make(LAST_DAY)
    before = b.health()["kb_version"]
    assert "FEE-001" in b.store.active.kb.entries and b.store.active.kb.compiled_on == LAST_DAY
    b.s.today_override = NEXT_DAY
    await Caller(b, "x4", "+919000000001").say("hello")           # triggers the refresh
    await asyncio.gather(*list(b._bg))
    after = b.store.active.kb
    assert after.kb_version != before and "FEE-001" not in after.entries and after.compiled_on == NEXT_DAY
    assert any("FEE-001" in w for w in after.info.warnings)
    # a second turn the same day does not refresh again
    await Caller(b, "x5", "+919000000001").say("hello")
    assert not b._bg and b.health()["kb_version"] == after.kb_version
    await b.aclose()


async def test_refresh_failure_keeps_serving_the_old_version_and_enforces_expiry(tmp_path):
    b = await make(LAST_DAY)
    b.store.last_source = b.store.last_source.model_copy(update={"location": str(tmp_path / "gone.jsonl")})
    b.s.today_override = NEXT_DAY
    ev = await Caller(b, "x6", "+919000000001").say("fees kab tak jama karni hai")
    await asyncio.gather(*list(b._bg))
    assert b.health()["kb_version"] == b.store.active.kb.kb_version and not b._refreshing
    assert "30 November" not in speech(ev)
    await b.aclose()
