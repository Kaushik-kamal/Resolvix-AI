"""Decision 27: a roll number / identifier must never become the complaint location nor reach a staff-facing field."""
from __future__ import annotations

import json

import pytest

from conftest import Caller, actions, done
from resolvix_brain.text import looks_like_identity, redact
from resolvix_brain.urgency import extract_location

ROLL = "2101234"
OPENER = "Hostel ka wifi do din se nahi chal raha"          # complaint without a place: the Brain asks for the location


async def run_complaint(brain, call_id, answers):
    c = Caller(brain, call_id, "+919000000001")
    out = [await c.say(OPENER)]
    for a in answers:
        out.append(await c.say(a))
    return out


def ticket_of(events_list):
    for ev in events_list:
        for a in actions(ev, "create_ticket"):
            return a.ticket
    return None


# ---------------------------------------------------------------- masking and classification
@pytest.mark.parametrize("text", [
    f"mera naam Rahul roll number {ROLL}", f"mera naam Rahul hai, roll no {ROLL}", f"my name is Rahul, roll number {ROLL}",
    "मेरा नाम राहुल है रोल नंबर २१०१२३४", f"enrollment no. 21-0123 hai", f"roll no {ROLL} hai", f"{ROLL} mera roll hai"])
def test_identity_statements_are_masked_and_never_a_location(text):
    out = redact(text)
    assert ROLL not in out and "2101234" not in out and "21-0123" not in out and "२१०१२३४" not in out and "[REDACTED]" in out
    assert looks_like_identity(text)
    assert extract_location(text) is None


@pytest.mark.parametrize("text,loc", [
    ("Block B room 214", "Block B room 214"), ("hostel room 305", "room 305"), ("Lab 3", "Lab 3"),
    (f"mera roll number {ROLL} hai aur Block B room 214 mein wifi nahi chal raha", "Block B room 214"),
    (f"roll no 2101 hai, Block C 102 mein hoon", "Block C 102"),
    ("मेरा रोल नंबर २१०१२३४ है, कमरा 214 में दिक्कत है", "कमरा 214")])
def test_genuine_locations_survive_even_beside_a_roll_number(text, loc):
    got = extract_location(text)
    assert got is not None and loc.lower() in got.lower(), (text, got)
    assert "2101" not in got and "२१०१" not in got


@pytest.mark.parametrize("text", [
    "Block B room 214", "Noida sector 62 201301", "Central library second floor", "hostel room 305", "fees 15000 hai",
    "Gate number 3 ke paas", "Kamra 214, B block"])
def test_numeric_addresses_and_room_ids_are_not_masked_or_flagged(text):
    assert redact(text) == text and not looks_like_identity(text)


def test_phone_numbers_are_still_masked():
    assert redact("mera number 98765 43210 hai") == "mera number [REDACTED] hai"
    assert redact("9876543210").startswith("[REDACTED]")


# ---------------------------------------------------------------- through the complaint flow
@pytest.mark.parametrize("intro", [
    f"mera naam Rahul roll number {ROLL}", f"mera naam Rahul hai aur roll no {ROLL}", f"my name is Rahul roll number {ROLL}",
    "मेरा नाम राहुल है रोल नंबर २१०१२३४"])
async def test_roll_number_answer_never_becomes_the_location(brain, intro):
    evs = await run_complaint(brain, "c-roll-" + str(abs(hash(intro)) % 10000), [intro, "Block B room 214", "haan", "haan sahi hai"])
    t = ticket_of(evs)
    assert t is not None
    assert t.collected_fields.get("location") == "Block B room 214"
    blob = t.model_dump_json() + json.dumps([done(e).model_dump(mode="json") for e in evs], default=str, ensure_ascii=False)
    assert ROLL not in blob and "२१०१२३४" not in blob and "21-0123" not in blob


async def test_without_a_real_location_no_location_field_is_stored(brain):
    evs = await run_complaint(brain, "c-roll-none", [f"mera naam Rahul roll number {ROLL}", "pata nahi", "haan", "haan sahi hai"])
    t = ticket_of(evs)
    assert t is not None and ROLL not in t.model_dump_json()
    assert "roll number" not in (t.collected_fields.get("location") or "").lower()


async def test_location_and_roll_number_in_the_same_sentence(brain):
    evs = await run_complaint(brain, "c-roll-same", [f"mera roll number {ROLL} hai aur Block B room 214 mein hoon", "haan", "haan sahi hai"])
    t = ticket_of(evs)
    assert t is not None and t.collected_fields.get("location") == "Block B room 214"
    assert ROLL not in t.model_dump_json()


async def test_genuine_plain_place_answers_still_work_in_collect_and_fix(brain):
    evs = await run_complaint(brain, "c-place", ["Central library second floor", "haan", "haan sahi hai"])
    t = ticket_of(evs)
    assert t is not None and t.collected_fields.get("location") == "Central library second floor"
    # correction step: a plain place name replaces the location
    evs = await run_complaint(brain, "c-fix", ["Block B room 214", "haan", "nahi", "Main library"])
    assert any("main library" in " ".join(e.text for e in ev if e.type == "speech").lower() for ev in evs[-1:])


async def test_roll_number_in_the_fix_step_is_not_taken_as_a_place(brain):
    c = Caller(brain, "c-fix-roll", "+919000000001")
    await c.say(OPENER)
    await c.say("Block B room 214")
    await c.say("haan")
    await c.say("nahi")                                                         # readback rejected -> fix step
    ev = await c.say(f"mera naam Rahul roll number {ROLL}")
    text = " ".join(e.text for e in ev if e.type == "speech")
    assert ROLL not in text and "roll number" not in text.lower()
    assert brain.sessions.get("c-fix-roll").pending.data["location"] == "Block B room 214"   # unchanged
