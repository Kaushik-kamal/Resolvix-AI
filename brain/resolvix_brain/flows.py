"""Dialogue plans and multi-turn flows (FR-B2 steps 1-3, 8-9; PRD 3.6).

Every function here is *pure planning*: it returns a ``Plan`` (ordered Speech/Action events plus the metadata for
``MetaEvent``/``TurnSummary``) and mutates only the session copy it is given. The brain commits that copy when
content is first yielded. Nothing here performs I/O; actions are only *emitted* for Member A to execute.

Limits (PRD): clarifying questions <= 2 per topic; complaint follow-up questions <= 2; urgent questions <= 2;
one yes/no re-prompt per step. Slots already known are never asked again.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from resolvix_contracts import sms_idempotency_key, ticket_idempotency_key
from resolvix_contracts.models import (
    ActionEvent, CreateTicketAction, Lang, LogGapAction, SendSmsAction, SpeechEvent, Tier, TICKET_ID_PLACEHOLDER,
    TicketCreate, TransferAction, UrgencyFacts, EndCallAction,
)

from .lines import line, spoken_digits
from .routing import Directory
from .rules import RuleResult, RuleTable
from .safety import Lexicon, SafetyHit
from .session import Flow, Session
from .speech import to_spoken
from .text import (extract_phone, extract_roll_number, last4_spoken, looks_like_identity, redact, reply_lang, tokens,
                   word_count, yes_no)
from .urgency import extract_location, extract_paper, infer_category

MAX_FOLLOWUPS = 2
_E164 = re.compile(r"^\+\d{10,15}$")
_CATEGORY_LABEL = {"wifi": "Wi-Fi", "mess": "mess", "water": "water supply", "electricity": "electricity",
                   "cleanliness": "cleanliness", "transport": "transport", "room": "room", "exam": "exam",
                   "fees": "fees"}


# --------------------------------------------------------------------------- plan
@dataclass
class Plan:
    path: str                                  # contract Path value
    tier: Tier | None
    interruptable: bool = True
    events: list[SpeechEvent | ActionEvent] = field(default_factory=list)
    rule_id: str | None = None
    priority: str | None = "P4"
    priority_reason: str | None = None
    urgency: UrgencyFacts | None = None
    kb_ids: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    latency: dict[str, int] = field(default_factory=dict)
    cached_tokens: int | None = None
    awaiting: str | None = None
    lang: Lang | None = None

    def say(self, text: str) -> "Plan":
        if text.strip():
            self.events.append(SpeechEvent(text=text.strip()))
        return self

    def act(self, action, blocking: bool = False) -> "Plan":
        self.events.append(ActionEvent(action=action, blocking=blocking))
        return self

    @property
    def spoken(self) -> str:
        return " ".join(e.text for e in self.events if isinstance(e, SpeechEvent))


@dataclass
class Ctx:
    directory: Directory
    rules: RuleTable
    lexicon: Lexicon
    now: datetime
    call_id: str
    turn_index: int
    today: Any = None


# --------------------------------------------------------------------------- small helpers
def L(sess: Session, key: str, **fmt: str) -> str:
    return line(key, reply_lang(sess.lang), sess.script, **fmt)


def _bucket(sess: Session) -> str:
    return reply_lang(sess.lang)


def valid_e164(n: str | None) -> bool:
    return bool(n and _E164.match(n))


def excerpt(sess: Session, current: str, limit: int = 400) -> str:
    parts = [("Caller: " if r == "user" else "Agent: ") + redact(t) for r, t in sess.turns[-4:]]
    if not parts or not parts[-1].endswith(redact(current)):
        parts.append("Caller: " + redact(current))
    return " | ".join(parts)[-limit:]


def build_ticket(sess: Session, ctx: Ctx, *, ttype: str, priority: str, reason: str, dept: str, summary: str,
                 fields: dict[str, str] | None = None, callback_number: str | None = None,
                 callback_requested: bool = False, brief: str = "", text: str = "") -> TicketCreate:
    return TicketCreate(
        idempotency_key=ticket_idempotency_key(ctx.call_id, ctx.turn_index, ttype),
        call_id=ctx.call_id, type=ttype, priority=priority, priority_reason=reason[:300], department=dept,
        summary=summary[:280], collected_fields={k: str(v) for k, v in (fields or {}).items() if v},
        caller_number=sess.caller_number, callback_number=callback_number, callback_requested=callback_requested,
        transcript_excerpt=excerpt(sess, text), brief=brief[:500])


def sms_action(sess: Session, ctx: Ctx, template: str, to: str | None, vars: dict[str, str], consent: str,
               plan: Plan | None = None):
    """The ``send_sms`` action, or None when there is no valid number or this call already requested the same SMS.

    CR-7: ops dedupes on the frozen key ``{call_id}:{template}:{to}``, which has no ticket component, so a second
    request for the same recipient and template in one call would be dropped there and the caller told a text is
    coming. The Brain therefore remembers the keys it requested in this call (``Session.sms_requested``, committed with
    the turn, gone when the call ends) and does not request the same one again. Callers must say nothing about an SMS
    when this returns None. The Brain never learns whether ops delivered anything, so the spoken line only says an SMS
    was *requested*."""
    if not valid_e164(to):
        return None
    key = sms_idempotency_key(sess.call_id, template, to)
    if key in sess.sms_requested:
        if plan is not None and "sms_duplicate_suppressed" not in plan.flags:
            plan.flags.append("sms_duplicate_suppressed")
        return None
    sess.sms_requested.add(key)
    return SendSmsAction(idempotency_key=key, to_number=to, template_id=template, vars=vars, consent=consent)


def _transfer(ctx: Ctx, dept: str, reason: str, brief: str) -> TransferAction:
    return TransferAction(department=dept, to_number=ctx.directory.transfer_number(dept), reason=reason,
                          brief=brief[:500], requires_ticket=True)


def sp(sess: Session, text: str, today=None) -> str:
    """Final spoken form of a line or answer (amounts, dates, times)."""
    return to_spoken(text, _bucket(sess), today)


def facts_summary(f: UrgencyFacts) -> str:
    bits = [f.event_type.replace("_", " ")]
    if f.minutes_to_event is not None:
        bits.append(f"in {f.minutes_to_event} min" if f.minutes_to_event < 120 else f"in {f.minutes_to_event // 60} h")
    if f.blocked:
        bits.append("caller blocked")
    return ", ".join(bits)


# --------------------------------------------------------------------------- emergency (deterministic)
def emergency_plan(sess: Session, ctx: Ctx, text: str, hit: SafetyHit | None, rule: RuleResult,
                   facts: UrgencyFacts | None = None) -> Plan:
    """Fixed script, then ticket (blocking), staff SMS alerts, transfer. Never involves the LLM."""
    sess.pending = None
    category = hit.category if hit else "safety"
    label = {"medical": "Medical", "harassment": "Harassment", "self_harm": "Self-harm", "violence": "Safety"}.get(category, "Safety")
    f = facts or UrgencyFacts(event_type=hit.event_type if hit else "safety", safety_flag=True,
                              affected=hit.affected if hit else None)
    numbers = ", ".join(" ".join(n) for n in ctx.directory.public_numbers())
    plan = Plan("safety", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority, urgency=f,
                priority_reason=f"{rule.rule_id}: {rule.reason}" + (f" ({category} lexicon, matched '{hit.term}')" if hit else " (extracted by LLM)"))
    plan.say(L(sess, "emergency", numbers=numbers))
    summary = f"{label} emergency reported by caller: {redact(text)[:170]}"
    brief = f"EMERGENCY ({category}): {redact(text)[:160]}. Caller on line."
    plan.act(CreateTicketAction(ticket=build_ticket(
        sess, ctx, ttype="EMERGENCY", priority="P1", reason=plan.priority_reason, dept="emergency", summary=summary,
        brief=brief, text=text)), blocking=True)
    for n in ctx.directory.emergency_alert_numbers():
        a = sms_action(sess, ctx, "staff_alert", n, {"ticket_id": TICKET_ID_PLACEHOLDER,
                                                      "summary": f"{label} emergency reported on a live call"}, "staff", plan)
        if a:
            plan.act(a)
    plan.act(_transfer(ctx, "emergency", f"Safety/medical statement ({category})", brief), blocking=True)
    return plan


# --------------------------------------------------------------------------- human request
def human_plan(sess: Session, ctx: Ctx, text: str, rule: RuleResult, *, facts: UrgencyFacts | None = None,
               force_callback: bool = False, note: str = "", dept: str | None = None, topic: str | None = None) -> Plan:
    sess.pending = None
    dept = dept or ctx.directory.resolve(rule.department, text=_topic_text(sess, text))
    is_open = ctx.directory.is_open(dept, ctx.now) and not force_callback
    dname = ctx.directory.name(dept)
    plan = Plan("escalation", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                priority_reason=f"{rule.rule_id}: {rule.reason}" + (f" ({note})" if note else ""), urgency=facts)
    if topic is None:
        topic = redact(text)[:120] if word_count(text) > 6 else ""
    brief = "Caller asked for a human; " + (f"topic: {topic}." if topic else "no topic given.")
    callback = (not is_open) or force_callback
    plan.act(CreateTicketAction(ticket=build_ticket(
        sess, ctx, ttype="HUMAN_REQUEST", priority=rule.priority, reason=plan.priority_reason, dept=dept,
        summary="Caller asked to speak to a person." + (f" {note}" if note else ""),
        callback_number=sess.caller_number if callback else None, callback_requested=callback, brief=brief,
        text=text)), blocking=True)
    if is_open:
        plan.say(L(sess, "human_connect", dept=dname))
        plan.act(_transfer(ctx, dept, "Caller requested a human", brief), blocking=True)
    else:
        sms = sms_action(sess, ctx, "ticket_created", sess.caller_number,
                         {"ticket_id": TICKET_ID_PLACEHOLDER, "dept": dname}, "transactional", plan)
        if sms:
            plan.act(sms)
        said = L(sess, "callback_done" if force_callback else "human_callback", dept=dname)
        plan.say(said + (" " + L(sess, "sms_requested") if sms else ""))
    return plan


def _topic_text(sess: Session, text: str) -> str:
    """Text used to infer a department: the current utterance plus the recent caller turns."""
    recent = " ".join(t for r, t in sess.turns[-4:] if r == "user")
    return f"{text} {recent}"


# --------------------------------------------------------------------------- urgent (P1/P2 from the rule table)
def start_urgent(sess: Session, ctx: Ctx, text: str, rule: RuleResult, facts: UrgencyFacts) -> Plan:
    dept = ctx.directory.resolve(rule.department, text=_topic_text(sess, text), event_type=facts.event_type)
    roll = extract_roll_number(text)
    if roll and roll == (sess.caller_number or "")[-len(roll):]:
        roll = None
    paper = extract_paper(text, roll) if facts.event_type == "exam" and roll else None
    data = {"rule_id": rule.rule_id, "dept": dept, "facts": facts.model_dump(), "roll_no": roll, "paper": paper,
            "origin": redact(text)[:200]}
    flow = Flow("urgent", "collect", data)
    sess.pending = flow
    return _urgent_next(sess, ctx, text, flow)


def _urgent_missing(data: dict) -> list[str]:
    need = ["roll_no"]
    if data["facts"].get("event_type") == "exam":
        need.append("paper")
    return [k for k in need if not data.get(k)]


def _urgent_next(sess: Session, ctx: Ctx, text: str, flow: Flow) -> Plan:
    missing = _urgent_missing(flow.data)
    if missing and flow.asked < MAX_FOLLOWUPS:
        flow.asked += 1
        key = "urgent_ask_both" if len(missing) == 2 else ("urgent_ask_roll" if missing == ["roll_no"] else "urgent_ask_paper")
        rule = ctx.rules.rule(flow.data["rule_id"])
        return Plan("slot_filling", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                    priority_reason=f"{rule.rule_id}: {rule.reason} ({facts_summary(UrgencyFacts(**flow.data['facts']))})",
                    urgency=UrgencyFacts(**flow.data["facts"])).say(L(sess, key))
    return _urgent_finish(sess, ctx, text, flow)


def _urgent_finish(sess: Session, ctx: Ctx, text: str, flow: Flow) -> Plan:
    d = flow.data
    sess.pending = None
    rule = ctx.rules.rule(d["rule_id"])
    facts = UrgencyFacts(**d["facts"])
    dept, dname = d["dept"], ctx.directory.name(d["dept"])
    reason = f"{rule.rule_id}: {rule.reason} ({facts_summary(facts)})"
    mins = facts.minutes_to_event
    what = {"exam": "exam", "fee_deadline": "fee deadline", "admit_card": "admit card problem",
            "form_deadline": "form deadline"}.get(facts.event_type, "urgent matter")
    summary = f"Caller blocked: {what}" + (f" in {mins} minutes" if mins is not None else "") + \
              (f". Paper: {d['paper']}" if d.get("paper") else "") + "."
    brief = (f"URGENT {rule.priority}: {what}" + (f" in {mins} min" if mins is not None else "") +
             ", caller blocked." + (f" Roll {d['roll_no']}." if d.get("roll_no") else "") +
             (f" Paper {d['paper']}." if d.get("paper") else ""))
    open_now = ctx.directory.is_open(dept, ctx.now)
    transfer = rule.action == "transfer_now" or (rule.action == "transfer_if_open_else_callback" and open_now)
    plan = Plan("escalation", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                priority_reason=reason, urgency=facts)
    plan.act(CreateTicketAction(ticket=build_ticket(
        sess, ctx, ttype=rule.ticket_type or "URGENT", priority=rule.priority, reason=reason, dept=dept,
        summary=summary, fields={"roll_no": d.get("roll_no"), "paper": d.get("paper")},
        callback_number=None if transfer else sess.caller_number, callback_requested=not transfer,
        brief=brief, text=text)), blocking=True)
    if transfer:
        plan.say(L(sess, "urgent_connect", dept=dname))
        plan.act(_transfer(ctx, dept, f"{rule.priority} {what}" + (f" within {mins} minutes" if mins is not None else ""),
                           brief), blocking=True)
    else:
        sms = sms_action(sess, ctx, "ticket_created", sess.caller_number,
                         {"ticket_id": TICKET_ID_PLACEHOLDER, "dept": dname}, "transactional", plan)
        if sms:
            plan.act(sms)
        plan.say(L(sess, "urgent_callback", dept=dname) + (" " + L(sess, "sms_requested") if sms else ""))
    return plan


def _urgent_reply(sess: Session, ctx: Ctx, text: str, flow: Flow) -> Plan | None:
    d = flow.data
    roll = extract_roll_number(text)
    if roll and not d.get("roll_no"):
        d["roll_no"] = roll
    if not d.get("paper") and d["facts"].get("event_type") == "exam":
        paper = extract_paper(text, roll or d.get("roll_no"))
        if paper:
            d["paper"] = paper
    return _urgent_next(sess, ctx, text, flow)


# --------------------------------------------------------------------------- complaint
def start_complaint(sess: Session, ctx: Ctx, text: str, rule: RuleResult, facts: UrgencyFacts) -> Plan:
    data = {"details": redact(text)[:200], "category": infer_category(text), "location": extract_location(text),
            "callback": None, "fixes": 0, "rule_id": rule.rule_id, "facts": facts.model_dump(),
            "dept": ctx.directory.resolve(rule.department, text=_topic_text(sess, text))}
    flow = Flow("complaint", "start", data)
    sess.pending = flow
    return _complaint_next(sess, ctx, text, flow)


def _complaint_plan(sess: Session, ctx: Ctx, flow: Flow, text: str) -> Plan:
    rule = ctx.rules.rule(flow.data["rule_id"])
    return Plan("slot_filling", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                priority_reason=f"{rule.rule_id}: {rule.reason}", urgency=UrgencyFacts(**flow.data["facts"]))


def _complaint_summary(sess: Session, d: dict) -> str:
    cat = _CATEGORY_LABEL.get(d.get("category") or "", d.get("category") or "general")
    loc = f", {d['location']}" if d.get("location") else ""
    return f"{cat} problem{loc}"


def _complaint_ticket_summary(sess: Session, d: dict) -> str:
    det = d.get("details") or ""
    det = det if len(det) <= 120 else det[:117] + "..."
    return f"{_complaint_summary(sess, d)}. {det}".strip()


def _complaint_next(sess: Session, ctx: Ctx, text: str, flow: Flow) -> Plan:
    d = flow.data
    plan = _complaint_plan(sess, ctx, flow, text)
    if flow.step in ("start", "collect") and (not d.get("location") or not d.get("category")) and flow.asked < MAX_FOLLOWUPS:
        flow.asked += 1
        flow.step, flow.reprompts = "collect", 0
        return plan.say(L(sess, "complaint_ask" if d.get("category") else "complaint_ask_what"))
    if not d.get("category"):
        d["category"] = "other"
    if d.get("callback") is None and flow.step != "callback_done":
        flow.reprompts = 0
        if sess.caller_number:
            flow.step = "callback_confirm"
            return plan.say(L(sess, "complaint_confirm_number", last4=spoken_digits(last4_spoken(sess.caller_number), _bucket(sess))))
        flow.step = "callback_number"
        return plan.say(L(sess, "ask_number"))
    flow.step, flow.reprompts = "readback", 0
    return plan.say(L(sess, "complaint_readback", summary=_complaint_summary(sess, d)))


def _complaint_create(sess: Session, ctx: Ctx, text: str, flow: Flow) -> Plan:
    d = flow.data
    sess.pending = None
    rule = ctx.rules.rule(d["rule_id"])
    dept = ctx.directory.resolve(rule.department, text=f"{d.get('details', '')} {d.get('location', '')} {d.get('category', '')}")
    dname = ctx.directory.name(dept)
    facts = UrgencyFacts(**d["facts"])
    reason = f"{rule.rule_id}: {rule.reason}"
    cb = d.get("callback")
    plan = Plan("slot_filling", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                priority_reason=reason, urgency=facts)
    plan.act(CreateTicketAction(ticket=build_ticket(
        sess, ctx, ttype=rule.ticket_type or "COMPLAINT", priority=rule.priority, reason=reason, dept=dept,
        summary=_complaint_ticket_summary(sess, d), fields={"category": d.get("category"), "location": d.get("location"),
                                                    "callback_number": cb},
        callback_number=cb, callback_requested=False,
        brief=_complaint_ticket_summary(sess, d)[:200], text=d.get("details", ""))), blocking=True)
    sms = sms_action(sess, ctx, "ticket_created", cb or None,
                     {"ticket_id": TICKET_ID_PLACEHOLDER, "dept": dname}, "transactional", plan)
    if sms:
        plan.act(sms)
    plan.say(L(sess, "complaint_done") + (" " + L(sess, "sms_requested") if sms else ""))
    plan.awaiting = "anything_else"
    return plan


def _complaint_reply(sess: Session, ctx: Ctx, text: str, flow: Flow) -> Plan | None:
    d, step = flow.data, flow.step
    yn = yes_no(text)
    phone = extract_phone(text)
    if step == "collect":
        loc = extract_location(text)
        if loc and not d.get("location"):
            d["location"] = loc
        elif not d.get("location") and word_count(text) <= 8 and yn is None and not looks_like_identity(text):
            d["location"] = redact(text).strip(" .,")[:60]
        cat = infer_category(text)
        if cat and not d.get("category"):
            d["category"] = cat
        if word_count(text) >= 5 and not loc:
            d["details"] = (d["details"] + " " + redact(text))[:240]
        return _complaint_next(sess, ctx, text, flow)
    if step in ("callback_confirm", "callback_number"):
        if phone:
            d["callback"] = phone
        elif step == "callback_confirm" and yn is True:
            d["callback"] = sess.caller_number
        elif step == "callback_confirm" and yn is False:
            flow.step, flow.reprompts = "callback_number", 0
            return _complaint_plan(sess, ctx, flow, text).say(L(sess, "ask_number"))
        elif flow.reprompts < 1:
            flow.reprompts += 1
            return _complaint_plan(sess, ctx, flow, text).say(L(sess, "yes_no_reprompt") if step == "callback_confirm" else L(sess, "ask_number"))
        else:
            d["callback"] = ""  # give up on a callback number; the ticket is still created
        flow.step = "callback_done"
        return _complaint_next(sess, ctx, text, flow)
    if step in ("readback", "readback2"):
        if yn is True:
            return _complaint_create(sess, ctx, text, flow)
        if yn is None and flow.reprompts < 1:
            flow.reprompts += 1
            return _complaint_plan(sess, ctx, flow, text).say(L(sess, "yes_no_reprompt"))
        if step == "readback2" or d.get("fixes", 0) >= 1:  # second "no": hand over to a person
            rule = ctx.rules.rule("R-HUMAN")
            return human_plan(sess, ctx, text, rule, note="complaint details could not be confirmed")
        d["fixes"] = d.get("fixes", 0) + 1
        flow.step, flow.reprompts = "fix", 0
        return _complaint_plan(sess, ctx, flow, text).say(L(sess, "complaint_fix"))
    if step == "fix":
        loc = extract_location(text)
        cat = infer_category(text)
        as_place = False
        if loc:
            d["location"] = loc
        elif not phone and not cat and word_count(text) <= 8 and not looks_like_identity(text):   # a plain place name ("Central library second floor")
            d["location"] = redact(text).strip(" .,")[:60]
            as_place = True
        if phone:
            d["callback"] = phone
        if cat:
            d["category"] = cat
        if word_count(text) >= 3 and not as_place and not (loc and word_count(text) <= 6):
            d["details"] = redact(text)[:200]
        flow.step, flow.reprompts = "readback2", 0
        return _complaint_plan(sess, ctx, flow, text).say(L(sess, "complaint_readback", summary=_complaint_summary(sess, d)))
    return None


# --------------------------------------------------------------------------- unknown question
def start_unknown(sess: Session, ctx: Ctx, text: str, rule: RuleResult, facts: UrgencyFacts | None,
                  cited_depts: list[str] | None = None) -> Plan:
    sess.unknown_count += 1
    dept = ctx.directory.resolve(rule.department, text=text, cited_depts=cited_depts)
    reason = f"{rule.rule_id}: {rule.reason}"
    plan = Plan("escalation", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                priority_reason=reason, urgency=facts)
    if sess.unknown_count >= 2:  # second unanswered question in one call: offer a human instead of another ticket
        sess.pending = Flow("human_offer", "offer", {"question": redact(text)[:200], "dept": dept})
        return plan.say(L(sess, "human_offer"))
    sess.pending = Flow("unknown", "offer", {"question": redact(text)[:200], "dept": dept, "rule_id": rule.rule_id,
                                              "callback": None})
    dname = ctx.directory.name(dept)
    plan.say(L(sess, "unknown_offer" if sess.caller_number else "unknown_offer_ask_number", dept=dname))
    return plan


def _unknown_create(sess: Session, ctx: Ctx, text: str, flow: Flow, callback: str | None) -> Plan:
    d = flow.data
    sess.pending = None
    rule = ctx.rules.rule(d["rule_id"])
    dept, dname = d["dept"], ctx.directory.name(d["dept"])
    reason = f"{rule.rule_id}: {rule.reason}"
    lang = Lang(sess.lang) if not isinstance(sess.lang, Lang) else sess.lang
    plan = Plan("escalation", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                priority_reason=reason)
    plan.act(CreateTicketAction(ticket=build_ticket(
        sess, ctx, ttype=rule.ticket_type or "KNOWLEDGE_GAP", priority=rule.priority, reason=reason, dept=dept,
        summary=f"Caller question not covered by approved documents: {d['question'][:200]}",
        fields={"callback_number": callback} if callback else None, callback_number=callback, callback_requested=True,
        brief=f"Question not in KB: {d['question'][:200]}. Call back" + (" on the caller number." if callback == sess.caller_number else "."),
        text=d["question"])), blocking=True)
    plan.act(LogGapAction(question=d["question"], lang=lang, department_guess=dept))
    sms = sms_action(sess, ctx, "ticket_created", callback, {"ticket_id": TICKET_ID_PLACEHOLDER, "dept": dname}, "transactional", plan)
    if sms:
        plan.act(sms)
    same = callback and callback == sess.caller_number
    plan.say(L(sess, "unknown_done" if same else "unknown_done_nosms", dept=dname))
    plan.awaiting = "anything_else"
    return plan


def _unknown_decline(sess: Session, ctx: Ctx, flow: Flow) -> Plan:
    d = flow.data
    sess.pending = None
    lang = Lang(sess.lang) if not isinstance(sess.lang, Lang) else sess.lang
    plan = Plan("escalation", Tier.escalate, interruptable=True, rule_id=d.get("rule_id"), priority="P3",
                priority_reason="R-UNANSWERED: caller declined a ticket; gap logged only")
    plan.act(LogGapAction(question=d["question"], lang=lang, department_guess=d["dept"]))
    plan.say(L(sess, "unknown_declined"))
    plan.awaiting = "anything_else"
    return plan


def _unknown_reply(sess: Session, ctx: Ctx, text: str, flow: Flow):
    phone = extract_phone(text)
    yn = yes_no(text)
    if flow.step == "offer":
        if phone:
            return _unknown_create(sess, ctx, text, flow, phone)
        if yn is True:
            if sess.caller_number:
                return _unknown_create(sess, ctx, text, flow, sess.caller_number)
            flow.step, flow.reprompts = "number", 0
            return Plan("escalation", Tier.escalate, False, rule_id=flow.data["rule_id"], priority="P3",
                        priority_reason="R-UNANSWERED: collecting callback number").say(L(sess, "ask_number"))
        if yn is False:
            return _unknown_decline(sess, ctx, flow)
    elif flow.step == "number":
        if phone:
            return _unknown_create(sess, ctx, text, flow, phone)
        if yn is False:
            return _unknown_decline(sess, ctx, flow)
    if flow.reprompts < 1 and word_count(text) < 3:
        flow.reprompts += 1
        return Plan("escalation", Tier.escalate, False, rule_id=flow.data["rule_id"], priority="P3",
                    priority_reason="R-UNANSWERED: waiting for yes/no").say(
            L(sess, "yes_no_reprompt") if flow.step == "offer" else L(sess, "ask_number"))
    # The caller moved on to something else: log the gap and treat this utterance as a new question.
    lang = Lang(sess.lang) if not isinstance(sess.lang, Lang) else sess.lang
    sess.pending = None
    return ("abandon", LogGapAction(question=flow.data["question"], lang=lang, department_guess=flow.data["dept"]))


# --------------------------------------------------------------------------- human offer (second unknown / unclear)
def start_human_offer(sess: Session, ctx: Ctx, text: str, speech_key: str, dept: str | None = None) -> Plan:
    dept = dept or ctx.directory.default
    sess.pending = Flow("human_offer", "offer", {"question": redact(text)[:200], "dept": dept})
    return Plan("escalation", Tier.escalate, interruptable=False, priority="P4").say(
        L(sess, speech_key, dept=ctx.directory.name(dept)))


def _human_offer_reply(sess: Session, ctx: Ctx, text: str, flow: Flow):
    yn = yes_no(text)
    if yn is True:
        return human_plan(sess, ctx, text, ctx.rules.rule("R-HUMAN"), note="accepted offer of a person",
                          dept=flow.data.get("dept"), topic=flow.data.get("question") or "")
    if yn is False:
        sess.pending = None
        q = flow.data.get("question")
        plan = Plan("escalation", Tier.escalate, True, priority="P4")
        if q and flow.data.get("dept"):
            lang = Lang(sess.lang) if not isinstance(sess.lang, Lang) else sess.lang
            plan.act(LogGapAction(question=q, lang=lang, department_guess=flow.data["dept"]))
        plan.say(L(sess, "human_offer_declined"))
        plan.awaiting = "anything_else"
        return plan
    if flow.reprompts < 1 and word_count(text) < 3:
        flow.reprompts += 1
        return Plan("escalation", Tier.escalate, False, priority="P4").say(L(sess, "yes_no_reprompt"))
    sess.pending = None
    return None


# --------------------------------------------------------------------------- dispatcher
def handle_pending(sess: Session, ctx: Ctx, text: str):
    """Process the caller's reply to an open flow.

    Returns a ``Plan``; or ``None`` to say "flow abandoned, handle this utterance normally"; or a tuple:
    ``("merge", combined_text)`` (clarify: re-run the pipeline on origin + reply) or
    ``("abandon", LogGapAction)`` (unknown flow dropped: log the gap, then handle the utterance normally).
    """
    flow = sess.pending
    if flow is None:
        return None
    if flow.name == "urgent":
        return _urgent_reply(sess, ctx, text, flow)
    if flow.name == "complaint":
        return _complaint_reply(sess, ctx, text, flow)
    if flow.name == "unknown":
        return _unknown_reply(sess, ctx, text, flow)
    if flow.name == "human_offer":
        return _human_offer_reply(sess, ctx, text, flow)
    if flow.name == "clarify":
        origin = flow.data.get("origin", "")
        sess.pending = None
        return ("merge", f"{origin} {text}".strip())
    sess.pending = None
    return None


def end_call_action(reason: str) -> EndCallAction:
    return EndCallAction(reason=reason)
