"""Urgency rule table (first match wins, boundaries) and the pre-LLM safety / human-request lexicon."""
from __future__ import annotations

import time

import pytest
import yaml

from conftest import ROOT, Caller, actions, done, kinds
from resolvix_brain.rules import RuleTable
from resolvix_brain.safety import Lexicon
from resolvix_brain.urgency import extract_facts, merge_facts, minutes_to_event

RULES = ROOT / "contracts" / "config" / "urgency_rules.yaml"
table = RuleTable.from_file(RULES)
lex = Lexicon.from_rules_file(RULES)


def ev(**kw):
    base = {"event_type": "none", "minutes_to_event": None, "blocked": False, "safety_flag": False, "affected": None,
            "intent": "faq", "tier": "confident"}
    base.update(kw)
    return table.evaluate(base)


# ------------------------------------------------------------------ rules
@pytest.mark.parametrize("mins,expected", [(59, "R-EXAM-60"), (60, "R-EXAM-60"), (61, "R-ROUTINE"), (0, "R-EXAM-60")])
def test_exam_boundary(mins, expected):
    assert ev(event_type="exam", minutes_to_event=mins, blocked=True).rule_id == expected


@pytest.mark.parametrize("mins,expected", [(1439, "R-DEADLINE-24H"), (1440, "R-DEADLINE-24H"), (1441, "R-ROUTINE")])
@pytest.mark.parametrize("etype", ["fee_deadline", "form_deadline", "admit_card"])
def test_deadline_boundary(mins, expected, etype):
    assert ev(event_type=etype, minutes_to_event=mins, blocked=True).rule_id == expected


def test_not_blocked_is_not_urgent():
    assert ev(event_type="exam", minutes_to_event=15, blocked=False).rule_id == "R-ROUTINE"
    assert ev(event_type="fee_deadline", minutes_to_event=100, blocked=False).rule_id == "R-ROUTINE"


def test_missing_minutes_never_satisfies_a_numeric_rule():
    assert ev(event_type="exam", minutes_to_event=None, blocked=True).rule_id == "R-ROUTINE"


def test_first_match_wins_and_priorities():
    # safety beats everything, even with exam facts and a human request
    r = ev(event_type="exam", minutes_to_event=5, blocked=True, safety_flag=True, intent="human_request", tier="escalate")
    assert (r.rule_id, r.priority, r.ticket_type, r.department) == ("R-SAFETY", "P1", "EMERGENCY", "emergency")
    assert ev(event_type="exam", minutes_to_event=5, blocked=True, tier="escalate").rule_id == "R-EXAM-60"
    assert ev(event_type="complaint").rule_id == "R-COMPLAINT"
    assert ev(intent="human_request", tier="escalate").rule_id == "R-HUMAN"       # before R-UNANSWERED
    r = ev(tier="escalate")
    assert (r.rule_id, r.priority, r.ticket_type, r.action) == ("R-UNANSWERED", "P3", "KNOWLEDGE_GAP", "ticket_and_gap")
    r = ev()
    assert (r.rule_id, r.priority, r.ticket_type, r.action) == ("R-ROUTINE", "P4", None, "none")


def test_tone_is_not_an_input():
    # facts have no emotion field; an angry routine question is still P4
    assert ev(event_type="none").priority == "P4"


def test_rule_file_shape():
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    ids = [r["id"] for r in data["rules"]]
    assert ids[0] == "R-SAFETY" and ids[-1] == "R-ROUTINE" and "R-FALLBACK" in ids and len(ids) == len(set(ids))
    assert table.rule("R-FALLBACK").ticket_type == "SYSTEM_FAILURE"


# ------------------------------------------------------------------ deterministic fact extraction
@pytest.mark.parametrize("text,mins", [
    ("Exam 15 minute mein hai", 15), ("exam in 30 minutes", 30), ("exam ek ghante mein hai", 60),
    ("paper 2 hours baad", 120), ("aadha ghanta bacha hai", 30), ("exam kab hai", None)])
def test_minutes_to_event(text, mins):
    assert minutes_to_event(text) == mins


def test_extract_exam_urgency_facts():
    f = merge_facts(extract_facts("Exam 15 minute mein hai, room nahi mil raha!"))
    assert (f.event_type, f.minutes_to_event, f.blocked, f.affected) == ("exam", 15, True, None)
    f = merge_facts(extract_facts("mera exam 15 minute mein hai aur hall nahi mil raha"))
    assert f.event_type == "exam" and f.blocked and f.affected == "self"
    assert extract_facts("exam kab hai")["event_type"] == "none"          # no time, not blocked: routine
    assert extract_facts("hostel ka wifi nahi chal raha")["event_type"] == "complaint"
    assert extract_facts("hostel mein wifi password kya hai")["event_type"] == "none"


def test_merge_never_lowers_safety():
    f = merge_facts({"event_type": "exam", "minutes_to_event": 90}, {"event_type": "medical", "safety_flag": True,
                                                                     "minutes_to_event": 20})
    assert f.event_type == "medical" and f.safety_flag and f.minutes_to_event == 20


# ------------------------------------------------------------------ safety lexicon
def _all_terms():
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))["safety_lexicon"]
    return [(cat, t) for cat, terms in data.items() for t in terms]


@pytest.mark.parametrize("cat,term", _all_terms())
def test_every_lexicon_term_triggers(cat, term):
    hit = lex.safety_hit(f"please help, {term} ho gaya hai")
    assert hit is not None


@pytest.mark.parametrize("text", [
    "Hostel mein ek ladka behosh ho gaya hai", "Meri dost ko ragging kar rahe hain", "मेरा दोस्त बेहोश हो गया",
    "वो मुझे धमकी दे रहे हैं", "I want to commit suicide", "someone is bleeding badly", "ambulance bulao jaldi",
    "mujhe saans nahi aa rahi", "there was an accident near the gate", "वह आत्महत्या की बात कर रहा है",
    "कैंपस में मारपीट हो रही है", "he has a knife", "Heart Attack aaya hai!", "BEHOSH!!!"])
def test_emergency_phrases_hit(text):
    assert lex.safety_hit(text) is not None, text


@pytest.mark.parametrize("text", [
    "hostel ki fees kitni hai", "What time does the hostel gate close?", "exam kab se hain", "mess ka time kya hai",
    "B.Tech second year fees ki last date kya hai?", "mujhe admit card chahiye", "library kab khulti hai",
    "main behoshi ke baare mein nahi, fees ke baare mein puch raha hoon".replace("behoshi", "behoshiyan"),
    "firefox browser nahi chal raha"])
def test_normal_sentences_do_not_hit(text):
    assert lex.safety_hit(text) is None, text


def test_safety_hit_details():
    h = lex.safety_hit("Hostel mein ek ladka behosh ho gaya hai")
    assert (h.category, h.event_type, h.affected) == ("medical", "medical", "other")
    assert lex.safety_hit("mujhe ragging ka dar hai").affected == "self"


def test_safety_is_fast():
    t = time.perf_counter()
    for _ in range(200):
        lex.safety_hit("mera exam 15 minute mein hai aur hall nahi mil raha, please jaldi batao kahan jaana hai")
    per_call_ms = (time.perf_counter() - t) / 200 * 1000
    assert per_call_ms < 5, per_call_ms


@pytest.mark.parametrize("text,dtmf,expected", [
    ("Mujhe kisi insaan se baat karni hai", None, True), ("I want to talk to a person", None, True),
    ("can I speak to a real person", None, True), ("operator please", None, True), ("", "0", True),
    ("मुझे किसी से बात करनी है", None, True), ("what is the human resources department", None, False),
    ("hostel fees kitni hai", None, False), ("", "5", False)])
def test_human_request_lexicon(text, dtmf, expected):
    assert lex.human_request(text, dtmf) is expected


# ------------------------------------------------------------------ end to end: safety never calls the LLM
async def test_safety_path_never_calls_llm_even_inside_a_flow(brain):
    c = Caller(brain, "c-safe", "+919000000003")
    await c.say("Hostel ka wifi do din se nahi chal raha")                 # opens a complaint flow
    assert brain.sessions.get("c-safe").pending.name == "complaint"
    calls_before = len(brain.llm_client.calls)
    ev_ = await c.say("ek ladki behosh ho gayi hai")                        # safety overrides the pending flow
    assert done(ev_).path == "safety" and done(ev_).rule_id == "R-SAFETY"
    assert kinds(ev_)[:3] == ["meta", "speech", "create_ticket"]
    assert len(brain.llm_client.calls) == calls_before
    assert brain.sessions.get("c-safe").pending is None
    t = actions(ev_, "create_ticket")[0]
    assert (t.ticket.type, t.ticket.priority, t.ticket.department) == ("EMERGENCY", "P1", "emergency")


async def test_llm_extracted_safety_flag_also_takes_the_emergency_plan(brain):
    brain.llm_client.queue.append(
        '<meta>{"tier":"escalate","kb_ids":[],"lang":"hinglish","intent":"other","urgency_facts":'
        '{"event_type":"medical","minutes_to_event":null,"blocked":true,"safety_flag":true,"affected":"other"},"needs":[]}</meta>\nok')
    c = Caller(brain, "c-llm-safe", "+919000000003")
    ev_ = await c.say("mere bhai ki halat bahut kharab hai kuch bol nahi pa raha")
    assert done(ev_).rule_id == "R-SAFETY" and done(ev_).path == "safety"
    assert [a.kind for a in actions(ev_)] == ["create_ticket", "send_sms", "send_sms", "transfer"]
