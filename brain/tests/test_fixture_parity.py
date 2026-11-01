"""The nine frozen scenarios (contracts/fixtures/brain_streams) reproduced from text input.

"Structurally identical" = same sequence of event types and action kinds (consecutive speech events and
consecutive identical action kinds are collapsed: wording and sentence splitting may differ, and the emergency
fixture shows one staff alert while the config has two alert numbers), same path/tier/priority/rule_id, same
ticket type/priority/department, same transfer department, same SMS template and consent.
These need the real embedder because fixture 01 (FAQ hit) and 02 (LLM path) depend on actual similarity scores.
"""
from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter
from resolvix_contracts import TICKET_ID_PLACEHOLDER
from resolvix_contracts.models import BrainEvent

from conftest import FIXTURES, Caller, T_OPEN, load_fixture

pytestmark = pytest.mark.realembed
EV = TypeAdapter(BrainEvent)

# name -> (caller number, setup turns [(turn_index, text)])
SCENARIOS = {
    "01_faq_answer_hi": ("+919000000010", []),
    "02_llm_answer_en": ("+919000000011", []),
    "03_unknown_ticket_hinglish": ("+919000000001", [(1, "Noida sector 62 ke liye bus route kya hai?")]),
    "04_urgent_exam_transfer": ("+919000000002", [(1, "Exam 15 minute mein hai, room nahi mil raha!")]),
    "05_emergency_safety": ("+919000000003", []),
    "06_complaint_confirmed": ("+919000000004", [(1, "Hostel ka wifi do din se nahi chal raha"), (2, "Block B room 214"), (3, "Haan")]),
    "07_human_request": ("+919000000005", []),
    "08_llm_failure_fallback": ("+919000000006", []),
    "09_partial_answer": ("+919000000012", []),
}


def signature(raw_events: list[dict]) -> list[tuple]:
    sig: list[tuple] = []
    for r in raw_events:
        e = EV.validate_python(r)
        if e.type == "meta":
            sig.append(("meta", e.path, e.tier))
        elif e.type == "speech":
            if not sig or sig[-1][0] != "speech":
                sig.append(("speech",))
        elif e.type == "action":
            a = e.action
            if a.kind == "create_ticket":
                t = ("action", a.kind, e.blocking, a.ticket.type, a.ticket.priority, a.ticket.department)
            elif a.kind == "transfer":
                t = ("action", a.kind, e.blocking, a.department, a.requires_ticket)
            elif a.kind == "send_sms":
                t = ("action", a.kind, e.blocking, a.template_id, a.consent)
            else:
                t = ("action", a.kind, e.blocking)
            if not (sig and sig[-1] == t):
                sig.append(t)
        else:
            s = e.summary
            sig.append(("done", s.path, s.tier, s.priority, s.rule_id))
    return sig


@pytest.mark.parametrize("name", sorted(SCENARIOS))
async def test_fixture_parity(rbrain, name):
    number, setup = SCENARIOS[name]
    req, expected = load_fixture(name)
    c = Caller(rbrain, call_id=req["call_id"], number=number, now=T_OPEN)
    for idx, text in setup:
        await c.say(text, turn_index=idx)
    events = await c.say(req["user_text"], turn_index=req["turn_index"], history=[], dtmf=req["dtmf"])

    raw = [json.loads(e.model_dump_json()) for e in events]
    for r in raw:
        EV.validate_python(r)  # every event validates against the frozen contract
    assert signature(raw) == signature(expected), f"{name}: structure differs"

    # event order invariants from the Brain protocol
    assert events[0].type == "meta" and events[-1].type == "done"
    assert sum(e.type == "meta" for e in events) == 1 and sum(e.type == "done" for e in events) == 1
    seen_ticket = False
    for e in events:
        if e.type == "action" and e.action.kind == "create_ticket":
            seen_ticket = True
            assert e.blocking
        if e.type == "action" and e.action.kind == "transfer":
            assert seen_ticket, "transfer before ticket"
        if e.type == "speech" and TICKET_ID_PLACEHOLDER in e.text:
            assert seen_ticket, "ticket placeholder spoken before the ticket exists"

    # rule id / reason / urgency facts against the fixture's summary
    exp_sum = expected[-1]["summary"]
    got = events[-1].summary
    assert got.rule_id == exp_sum["rule_id"]
    if exp_sum["priority_reason"]:
        assert got.priority_reason.startswith(exp_sum["rule_id"] + ":")
    if exp_sum["urgency"]:
        assert got.urgency is not None
        for k in ("event_type", "minutes_to_event", "blocked", "safety_flag"):
            assert getattr(got.urgency, k) == exp_sum["urgency"][k], k
    assert got.kb_ids == exp_sum["kb_ids"]
    assert got.user_text_redacted == exp_sum["user_text_redacted"]


async def test_emergency_alerts_every_configured_number(rbrain):
    c = Caller(rbrain, call_id="call-em2", number="+919000000003")
    ev = await c.say("Hostel mein ek ladka behosh ho gaya hai", turn_index=1)
    sms = [e.action for e in ev if e.type == "action" and e.action.kind == "send_sms"]
    assert [s.to_number for s in sms] == ["+910000000901", "+910000000902"]
    assert all(s.consent == "staff" and s.template_id == "staff_alert" for s in sms)
    # the fixed script comes first and names the public emergency number
    assert ev[1].type == "speech" and "1 1 2" in ev[1].text
