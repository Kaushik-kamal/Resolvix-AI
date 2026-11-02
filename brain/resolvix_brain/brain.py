"""The Brain: implements ``resolvix_contracts.Brain`` (start_call / handle_turn / end_call / reload_kb / health).

Turn pipeline (PRD FR-B2, fixed order)::

    session -> safety lexicon -> pending flow -> human request -> [personal-record guard, chit-chat,
    deterministic urgency pre-check] -> unclear input -> FAQ cache -> LLM (CAG) -> validators -> urgency rules
    -> plan -> events

The three bracketed steps are additions to the PRD order (see docs/DECISIONS.md): they are deterministic, cheap
and run before the FAQ cache so an urgent sentence is never answered by a semantically-close FAQ entry.

``handle_turn`` never raises: any internal error becomes the fallback plan (ticket + "we will call you back").
Planning happens on a *copy* of the session; the copy is committed when the first content event is yielded, so a
cancellation (barge-in) leaves the session consistent and critical actions not yet emitted are re-emitted at the
start of the next turn (``Session.deferred``).
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from datetime import datetime
from typing import AsyncIterator

import numpy as np
from resolvix_contracts.models import (
    ActionEvent, BrainEvent, CallContext, CallStartPlan, DoneEvent, KBSource, KBVersionInfo, Lang, MetaEvent,
    SpeechEvent, Tier, TurnRequest, TurnSummary, UrgencyFacts, CONTRACT_VERSION, CreateTicketAction, LogGapAction,
    SendSmsAction,
)

from . import flows
from .embeddings import Embedder, create_embedder
from .flows import Ctx, Plan, L
from .kb.compiler import KBCompileError
from .kb.store import KBStore, KBVersion
from .lines import greeting
from .llm import LLMService, LLMUnavailable, create_llm
from .routing import Directory
from .rules import RuleResult, RuleTable
from .safety import Lexicon
from .session import Flow, Session, SessionStore
from .settings import BrainSettings
from .speech import to_spoken
from .text import detect_lang, normalize, redact, reply_lang, script_of, tokens, word_count, yes_no
from .urgency import extract_facts as det_facts, has_phrase, merge_facts
from .validate import clean_text, lang_ok, validate

log = logging.getLogger("resolvix_brain")

_GREETING = frozenset("hello hi hey hii namaste namaskar namaskaar good morning afternoon evening नमस्ते नमस्कार हैलो हेलो".split())
_THANKS = frozenset("thanks thank thankyou dhanyavaad dhanyawad shukriya shukria धन्यवाद शुक्रिया".split())
_BYE = frozenset("bye goodbye alvida tata".split())
_FILLER = frozenset("you very much a lot ji sir madam ok okay so aapka bahut".split())
_NOTHING = frozenset("bas nothing enough done kuch nahi".split())
_PERSONAL = ("fees baaki", "fee due", "fee dues", "baaki fees", "baki fees", "pending fees", "pending fee", "my marks",
             "mere marks", "mera result", "my result", "my attendance", "meri attendance", "mera cgpa", "my cgpa",
             "mera sgpa", "my sgpa", "my backlog", "mera backlog", "meri marksheet", "my marksheet", "mera grade",
             "my grade", "mere number kitne", "my dues", "meri dues", "mera percentage", "my percentage")


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


class ResolvixBrain:
    def __init__(self, settings: BrainSettings, *, llm_client=None, embedder: Embedder | None = None):
        self.s = settings
        self.tz = settings.tz
        self.directory = Directory.from_file(settings.departments_file)
        self.rules = RuleTable.from_file(settings.urgency_rules_file)
        self.lexicon = Lexicon.from_rules_file(settings.urgency_rules_file)
        self.sessions = SessionStore(settings.session_ttl_s)
        if llm_client is not None:
            from .llm import LLMService as _S
            self.llm_client, self.llm = llm_client, _S(llm_client, settings)
        else:
            self.llm_client, self.llm = create_llm(settings)
        self.embedder: Embedder | None = embedder
        self.store: KBStore | None = None
        self._init_lock = asyncio.Lock()
        self._init_error: str | None = None
        self.turns_total = 0
        self._refreshing = False
        self._bg: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ lifecycle
    async def _ensure_store(self) -> KBStore:
        if self.store is None:
            if self.embedder is None:
                self.embedder = await asyncio.to_thread(create_embedder, self.s)
            self.store = KBStore(self.s, self.directory, self.embedder)
        return self.store

    async def ready(self) -> None:
        """Load the embedder and the default KB (``KB_SOURCE``). Idempotent; call once at startup to avoid paying
        the model-load cost on the first call. ``start_call`` also calls it."""
        async with self._init_lock:
            store = await self._ensure_store()
            if store.active is None and self._init_error is None:
                try:
                    await store.reload(self.s.default_kb_source(), warmup=self.llm.warmup)
                except KBCompileError as exc:
                    self._init_error = f"default KB failed to compile: {exc}"
                    log.error(self._init_error)

    async def aclose(self) -> None:
        await self.llm_client.aclose()

    async def start_call(self, ctx: CallContext) -> CallStartPlan:
        await self.ready()
        active = self.store.active if self.store else None
        version = active.kb.kb_version if active else "none"
        sess = Session(call_id=ctx.call_id, kb_version=version, channel=str(getattr(ctx.channel, "value", ctx.channel)),
                       caller_number=ctx.caller_number, open_tickets=list(ctx.open_tickets))
        self.sessions.put(sess)
        return CallStartPlan(kb_version=version, greeting_text=greeting("hi"), greeting_lang=Lang.hinglish,
                             interruptable=False)

    async def end_call(self, call_id: str) -> None:
        self.sessions.drop(call_id)

    async def reload_kb(self, source: KBSource) -> KBVersionInfo:
        """Compile + atomically activate. Raises ``KBCompileError`` (old version stays active) on failure."""
        store = await self._ensure_store()
        info = await store.reload(source, in_use=self.sessions.pinned_versions(), warmup=self.llm.warmup)
        self._init_error = None
        return info

    def _maybe_refresh(self) -> None:
        """Entries expire by date but the KB is compiled once. On the first turn of a new day (IST) recompile from the
        same source in the background; meanwhile expiry is also enforced at answer time (FAQ hit and citation checks)."""
        active = self.store.active if self.store else None
        src = self.store.last_source if self.store else None
        if not (active and src) or self._refreshing or active.kb.compiled_on in (None, self.s.today()):
            return
        self._refreshing = True

        async def go() -> None:
            try:
                await self.reload_kb(src)
                log.info("daily KB refresh done")
            except Exception as exc:  # keep serving the old version (expiry still enforced per answer)
                log.error("daily KB refresh failed: %s", type(exc).__name__)
            finally:
                self._refreshing = False

        task = asyncio.create_task(go())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def health(self) -> dict:
        active = self.store.active if self.store else None
        llm_down = self.llm.is_down or self.s.llm_mode == "live" and not self.s.groq_api_key
        degraded = (active is None) or llm_down or bool(self.embedder and self.embedder.degraded)
        return {"status": "degraded" if degraded else "ok", "kb_version": active.kb.kb_version if active else "none",
                "llm": "down" if llm_down else "ok", "contract_version": CONTRACT_VERSION,
                "embedder": getattr(self.embedder, "name", "not loaded"), "sessions": len(self.sessions),
                "llm_mode": self.s.llm_mode, "init_error": self._init_error}

    # ------------------------------------------------------------------ the turn
    async def handle_turn(self, req: TurnRequest) -> AsyncIterator[BrainEvent]:
        t0 = time.perf_counter()
        self.turns_total += 1
        orig: Session | None = None
        work: Session | None = None
        failed_lang: Lang | None = None
        plan: Plan
        try:
            await self.ready()
            self._maybe_refresh()
            orig = self.sessions.get(req.call_id) or self._adhoc_session(req)
            work = orig.clone()
            work.deferred = []
            plan = await self._plan(work, req, t0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never raise to Member A
            log.exception("turn failed: %s", type(exc).__name__)
            # The fallback is *spoken* from the half-planned copy (so it keeps the language detected this turn), but what is
            # committed is a fresh copy of the session as it was before the turn: whatever the failed planning changed
            # (flow state, SMS keys recorded by sms_action, ...) is rolled back with the discarded plan.
            plan = self._safe_fallback(work or orig, req, ["internal_error", type(exc).__name__], t0)
            failed_lang = work.lang if work is not None else None
            if orig is not None:
                work = orig.clone()
                work.deferred = []
        plan.latency["brain_total"] = _ms(t0)
        lang = Lang(failed_lang or work.lang) if work is not None else Lang.hinglish
        committed = False
        spoken: list[str] = []
        pending_deferred = list(orig.deferred) if orig is not None else []
        emitted = 0
        try:
            yield MetaEvent(path=plan.path, tier=plan.tier, lang=lang, interruptable=plan.interruptable)
            for ev in list(pending_deferred):
                yield ev
                if orig is not None and orig.deferred:
                    orig.deferred.pop(0)
            for ev in plan.events:
                if not committed:
                    committed = self._commit(orig, work, plan)
                emitted += 1                      # handed to the runtime at the yield below, even if it closes us there
                if isinstance(ev, SpeechEvent):
                    spoken.append(ev.text)
                yield ev
            if not committed:
                committed = self._commit(orig, work, plan)
            yield DoneEvent(summary=self._summary(plan, req, lang))
        except (GeneratorExit, asyncio.CancelledError):
            # barge-in: keep critical actions the runtime never received, and the speech it did receive
            if committed and orig is not None:
                lost = [e for e in plan.events[emitted:] if isinstance(e, ActionEvent) and
                        isinstance(e.action, (CreateTicketAction, SendSmsAction, LogGapAction))]
                orig.deferred.extend(lost)
            raise
        finally:
            if committed and orig is not None and spoken:
                orig.add_turn("assistant", " ".join(spoken))

    # ------------------------------------------------------------------ helpers
    def _adhoc_session(self, req: TurnRequest) -> Session:
        """A turn for a call we have no session for (runtime restarted): create one pinned to the active KB."""
        active = self.store.active if self.store else None
        s = Session(call_id=req.call_id, kb_version=active.kb.kb_version if active else "none")
        self.sessions.put(s)
        return s

    def _commit(self, orig: Session | None, work: Session | None, plan: Plan) -> bool:
        if orig is not None and work is not None:
            work.awaiting = plan.awaiting
            keep_deferred = orig.deferred
            orig.adopt(work)
            orig.deferred = keep_deferred
        return True

    def _summary(self, plan: Plan, req: TurnRequest, lang: Lang) -> TurnSummary:
        return TurnSummary(
            call_id=req.call_id, turn_index=req.turn_index, path=plan.path, tier=plan.tier, lang=lang,
            kb_ids=plan.kb_ids, urgency=plan.urgency, priority=plan.priority, priority_reason=plan.priority_reason,
            rule_id=plan.rule_id, user_text_redacted=redact(req.user_text), assistant_text=plan.spoken,
            validator_flags=plan.flags, latency_ms=plan.latency, cached_tokens=plan.cached_tokens,
            created_at=datetime.now(self.tz))

    def _rule(self, rule_id: str) -> RuleResult:
        try:
            return self.rules.rule(rule_id)
        except KeyError:  # rule file edited without it: sane defaults so the safety/fallback paths still work
            defaults = {"R-SAFETY": RuleResult("R-SAFETY", "P1", "EMERGENCY", "emergency", "transfer_now", "Safety, medical or harassment statement"),
                        "R-FALLBACK": RuleResult("R-FALLBACK", "P3", "SYSTEM_FAILURE", "from_topic_or_default", "ticket_and_callback", "System failure"),
                        "R-HUMAN": RuleResult("R-HUMAN", "P3", "HUMAN_REQUEST", "from_topic_or_default", "transfer_if_open_else_callback", "Caller asked for a person")}
            return defaults[rule_id]

    def _ctx(self, req: TurnRequest) -> Ctx:
        return Ctx(self.directory, self.rules, self.lexicon, req.received_at, req.call_id, req.turn_index)

    # ------------------------------------------------------------------ fallback
    def _safe_fallback(self, sess: Session | None, req: TurnRequest, flags: list[str], t0: float) -> Plan:
        try:
            s = sess.clone() if sess is not None else Session(call_id=req.call_id, kb_version="none")
            return self._fallback_plan(s, req, flags, t0)
        except Exception:  # last resort: static plan, no dependency on anything that might be broken
            log.exception("fallback construction failed")
            p = Plan("fallback", Tier.escalate, interruptable=False, rule_id="R-FALLBACK", priority="P3",
                     priority_reason="R-FALLBACK: internal error", flags=flags)
            p.act(CreateTicketAction(ticket=flows.TicketCreate(
                idempotency_key=f"{req.call_id}:{req.turn_index}:SYSTEM_FAILURE", call_id=req.call_id,
                type="SYSTEM_FAILURE", priority="P3", priority_reason="R-FALLBACK: internal error",
                department="helpdesk", summary="Agent failed internally; call back the caller.",
                callback_requested=True)), blocking=True)
            p.say("Sorry, we are having a technical problem. I have noted your call, ticket number {{ticket_id}}. You will receive a call back.")
            return p

    def _fallback_plan(self, sess: Session, req: TurnRequest, flags: list[str], t0: float) -> Plan:
        ctx = self._ctx(req)
        sess.pending = None
        rule = self._rule("R-FALLBACK")
        text = req.user_text or ""
        if "llm_timeout" in flags:
            why = "LLM timeout after retry"
        elif any(f.startswith("llm_") for f in flags):
            why = "LLM error after retry"
        else:
            why = "internal error"
        dept = ctx.directory.default
        reason = f"{rule.rule_id}: {why}"
        plan = Plan("fallback", Tier.escalate, interruptable=False, rule_id=rule.rule_id, priority=rule.priority,
                    priority_reason=reason, flags=list(flags))
        snippet = redact(text)[:150]
        plan.act(CreateTicketAction(ticket=flows.build_ticket(
            sess, ctx, ttype="SYSTEM_FAILURE", priority=rule.priority, reason=reason, dept=dept,
            summary=f"Agent could not answer ({why}). Caller said: {snippet}",
            callback_number=sess.caller_number, callback_requested=True,
            brief=f"System failure during call. Call back about: {snippet}", text=text)), blocking=True)
        plan.say(L(sess, "fallback"))
        return plan

    # ------------------------------------------------------------------ planning
    async def _embed(self, text: str) -> np.ndarray:
        vec = await asyncio.to_thread(self.embedder.embed_queries, [text])
        return vec[0]

    def _kb(self, sess: Session) -> KBVersion:
        v = self.store.get(sess.kb_version) if self.store else None
        if v is None:
            raise RuntimeError("no active knowledge base")
        return v

    async def _plan(self, sess: Session, req: TurnRequest, t0: float) -> Plan:
        text = (req.user_text or "").strip()
        ctx = self._ctx(req)
        lat: dict[str, int] = {}
        if not sess.turns and req.history:
            for m in req.history[-8:]:
                if m.role in ("user", "assistant"):
                    sess.add_turn(m.role, m.content)
        detected = detect_lang(text)
        if detected is not None:
            sess.lang = detected
        if tokens(text) and any(c.isalpha() for c in text):
            sess.script = script_of(text)

        plan = await self._pipeline(sess, req, ctx, text, lat, t0)
        plan.latency = {**lat, **plan.latency}
        if plan.lang is None:
            plan.lang = Lang(sess.lang)
        sess.add_turn("user", text)
        return plan

    async def _pipeline(self, sess: Session, req: TurnRequest, ctx: Ctx, text: str, lat: dict[str, int], t0: float) -> Plan:
        # 1. safety lexicon: always first, even inside a pending flow. Never touches the LLM.
        ts = time.perf_counter()
        hit = self.lexicon.safety_hit(text)
        lat["safety"] = max(1, _ms(ts)) if hit else _ms(ts)
        if hit:
            plan = flows.emergency_plan(sess, ctx, text, hit, self._rule("R-SAFETY"))
            plan.latency = {"safety": lat["safety"]}
            return plan

        # 2. pending flow
        pre_actions: list = []
        if sess.pending is not None:
            res = flows.handle_pending(sess, ctx, text)
            if isinstance(res, Plan):
                return res
            if isinstance(res, tuple):
                kind, val = res
                if kind == "merge":
                    text = val
                else:
                    pre_actions.append(val)
        awaiting, sess.awaiting = sess.awaiting, None

        # follow-up to "anything else?"
        if awaiting == "anything_else":
            p = self._anything_else_reply(sess, text)
            if p is not None:
                return p

        # 3. human request (lexicon, DTMF 0)
        if self.lexicon.human_request(text, req.dtmf):
            return flows.human_plan(sess, ctx, text, self._rule("R-HUMAN"))

        # 3a. personal records are out of scope: decline politely, offer a person
        if has_phrase(text, _PERSONAL):
            dept = ctx.directory.resolve("from_topic_or_default", text=text)
            return flows.start_human_offer(sess, ctx, text, "personal_decline", dept)

        # 3b. greetings / thanks / goodbye (no LLM needed)
        kind = self._chitchat_kind(text)
        if kind:
            return self._chitchat_plan(sess, kind)

        # 3c. deterministic urgency pre-check (facts only; the rule table decides)
        det = det_facts(text)
        if det["event_type"] != "none":
            facts = merge_facts(det)
            rr = self.rules.evaluate({**facts.model_dump(), "intent": "other", "tier": "confident"})
            if rr.rule_id in ("R-EXAM-60", "R-DEADLINE-24H"):
                return flows.start_urgent(sess, ctx, text, rr, facts)
            if rr.rule_id == "R-COMPLAINT":
                return flows.start_complaint(sess, ctx, text, rr, facts)

        # 4/5. FAQ cache (and the "unclear" decision, which needs it)
        kbv = self._kb(sess)
        faq = None
        if text:
            tf = time.perf_counter()
            qvec = await self._embed(text)
            faq = kbv.faq.lookup(qvec, self.s.faq_tau_hit, self.s.faq_tau_soft)
            lat["faq"] = _ms(tf)
        if word_count(text) < 2 and not (faq and faq.hit):
            sess.unclear_count += 1
            if sess.unclear_count >= 2:
                sess.unclear_count = 0
                return flows.start_human_offer(sess, ctx, text, "unclear_second")
            return Plan("slot_filling", Tier.clarify, True, priority="P4").say(L(sess, "unclear_first"))
        sess.unclear_count = 0
        if faq and faq.hit and kbv.kb.is_expired(faq.hit.entry_id, self.s.today()):
            faq = dataclasses.replace(faq, hit=None)       # expired since compile: never serve it from the cache
        if faq and faq.hit:
            plan = self._faq_plan(sess, kbv, faq.hit.entry_id)
            plan.latency.update(lat)
            return self._with_pre(plan, pre_actions)

        # 6/7. LLM (CAG) + validators
        plan = await self._llm_plan(sess, req, ctx, text, kbv, faq, det, lat)
        return self._with_pre(plan, pre_actions)

    @staticmethod
    def _with_pre(plan: Plan, pre: list) -> Plan:
        for a in reversed(pre):
            plan.events.insert(0, ActionEvent(action=a, blocking=False))
        return plan

    # ------------------------------------------------------------------ small plans
    def _chitchat_kind(self, text: str) -> str | None:
        toks = tokens(text)
        if not toks or len(toks) > 4:
            return None
        allowed = _GREETING | _THANKS | _BYE | _FILLER
        if not all(t in allowed for t in toks):
            return None
        if any(t in _BYE for t in toks):
            return "bye"
        if any(t in _THANKS for t in toks):
            return "thanks"
        return "greeting"

    def _chitchat_plan(self, sess: Session, kind: str) -> Plan:
        if kind == "bye":
            return self._goodbye(sess)
        plan = Plan("faq", Tier.chitchat, True, priority="P4")
        plan.say(L(sess, "chitchat_greeting" if kind == "greeting" else "chitchat_thanks"))
        if kind == "thanks":
            plan.awaiting = "anything_else"
        return plan

    def _goodbye(self, sess: Session) -> Plan:
        plan = Plan("faq", Tier.chitchat, False, priority="P4")
        plan.say(L(sess, "goodbye"))
        plan.act(flows.end_call_action("caller finished"))
        return plan

    def _anything_else_reply(self, sess: Session, text: str) -> Plan | None:
        toks = tokens(text)
        if not toks or len(toks) > 4:
            return None
        yn = yes_no(text)
        if yn is False or any(t in _NOTHING for t in toks) or self._chitchat_kind(text) in ("thanks", "bye"):
            return self._goodbye(sess)
        if yn is True:
            return Plan("faq", Tier.chitchat, True, priority="P4").say(L(sess, "go_ahead"))
        return None

    def _faq_plan(self, sess: Session, kbv: KBVersion, entry_id: str) -> Plan:
        e = kbv.kb.entries[entry_id]
        lang = reply_lang(sess.lang)
        answer = e.answer_hi if (lang == "hi" and e.answer_hi) else e.answer_en
        today = datetime.now(self.tz).date()
        plan = Plan("faq", Tier.confident, True, kb_ids=[entry_id], priority="P4")
        plan.say(to_spoken(answer, lang, today) + " " + L(sess, "source_mention", source=e.source_title))
        plan.say(L(sess, "anything_else"))
        plan.awaiting = "anything_else"
        sess.clarify_count = 0
        return plan

    # ------------------------------------------------------------------ LLM path
    def _messages(self, kbv: KBVersion, sess: Session, req: TurnRequest, text: str, faq) -> list[dict[str, str]]:
        now = req.received_at.astimezone(self.tz)
        dyn = ["CURRENT CONTEXT (not part of the knowledge base)",
               f"Now: {now.strftime('%A %d %B %Y, %H:%M')} IST",
               f"Departments open now: {', '.join(self.directory.open_departments(req.received_at)) or 'none'}",
               f"Caller language guess: {getattr(sess.lang, 'value', sess.lang)}"]
        if faq and faq.hints:
            dyn.append("FAQ hints (closest entries by similarity; verify against the KB): " +
                       ", ".join(f"{m.entry_id} ({m.score:.2f})" for m in faq.hints))
        if sess.slots:
            dyn.append("Known caller details: " + ", ".join(f"{k}={v}" for k, v in sess.slots.items()))
        if sess.open_tickets:
            dyn.append("Open tickets for this caller: " + "; ".join(
                f"{t.ticket_id} ({t.type}, {t.status}, {t.department})" for t in sess.open_tickets[:3]))
        msgs = [{"role": "system", "content": kbv.kb.prefix}, {"role": "system", "content": "\n".join(dyn)}]
        for role, t in sess.turns[-8:]:
            msgs.append({"role": "user" if role == "user" else "assistant", "content": redact(t)})
        msgs.append({"role": "user", "content": redact(text)})
        return msgs

    async def _llm_plan(self, sess: Session, req: TurnRequest, ctx: Ctx, text: str, kbv: KBVersion, faq, det: dict,
                        lat: dict[str, int]) -> Plan:
        lang_key = str(getattr(sess.lang, "value", sess.lang))

        def soft_check(meta, spoken: str) -> str | None:
            if str(getattr(meta.tier, "value", meta.tier)) in ("confident", "partial") and \
                    not lang_ok(clean_text(spoken)[0], lang_key):
                return "language_mismatch"
            return None

        try:
            outcome = await self.llm.run(self._messages(kbv, sess, req, text, faq), soft_check)
        except LLMUnavailable as exc:
            plan = self._fallback_plan(sess, req, exc.flags, time.perf_counter())
            plan.latency["llm_total"] = exc.elapsed_ms
            return plan
        meta, spoken = outcome.meta, outcome.spoken
        lat["llm_ttft"], lat["llm_total"] = outcome.response.ttft_ms, outcome.elapsed_ms
        if meta.lang and detect_lang(text) is None:
            sess.lang = Lang(meta.lang)
        v = validate(meta, spoken, kbv.kb, getattr(sess.lang, "value", str(sess.lang)), self.s.today())
        flags = outcome.flags + v.flags
        facts = merge_facts(det, meta.urgency_facts)
        intent = "human_request" if meta.intent == "callback_request" else meta.intent
        rr = self.rules.evaluate({**facts.model_dump(), "intent": intent, "tier": v.tier.value})
        cached = outcome.response.cached_tokens

        def finish(p: Plan) -> Plan:
            p.flags = flags + [f for f in p.flags if f not in flags]
            p.cached_tokens = cached
            p.kb_ids = p.kb_ids or v.kb_ids
            p.latency.update(lat)
            if p.urgency is None and facts.event_type != "none":
                p.urgency = facts
            return p

        if rr.rule_id == "R-SAFETY":
            p = flows.emergency_plan(sess, ctx, text, None, rr, facts)
            return finish(p)
        if rr.rule_id in ("R-EXAM-60", "R-DEADLINE-24H"):
            return finish(flows.start_urgent(sess, ctx, text, rr, facts))
        if rr.rule_id == "R-HUMAN":
            return finish(flows.human_plan(sess, ctx, text, rr, facts=facts,
                                           force_callback=(meta.intent == "callback_request")))
        if rr.rule_id == "R-COMPLAINT":
            return finish(flows.start_complaint(sess, ctx, text, rr, facts))
        if rr.rule_id == "R-UNANSWERED":
            cited = [kbv.kb.entries[i].department for i in v.kb_ids if i in kbv.kb.entries]
            p = flows.start_unknown(sess, ctx, text, rr, facts if facts.event_type != "none" else None, cited)
            return finish(p)
        # routine: speak the validated answer
        p = self._answer_plan(sess, ctx, kbv, v, text, flags)
        if sess.pending is not None and sess.pending.name == "clarify":
            sess.pending.data["origin"] = text
        return finish(p)

    def _answer_plan(self, sess: Session, ctx: Ctx, kbv: KBVersion, v, text: str, flags: list[str]) -> Plan:
        lang = reply_lang(sess.lang)
        today = datetime.now(self.tz).date()
        body = to_spoken(v.text, lang, today)
        if v.tier == Tier.clarify:
            if sess.clarify_count >= 2:  # third failure escalates (PRD): treat as unanswered
                flags.append("clarify_limit")
                return flows.start_unknown(sess, ctx, text, self._rule_or_unanswered(), None)
            sess.clarify_count += 1
            sess.pending = Flow("clarify", "answer", {"origin": ""})
            plan = Plan("llm", Tier.clarify, True, priority="P4").say(body)
            return plan
        if v.tier == Tier.chitchat:
            return Plan("llm", Tier.chitchat, True, priority="P4").say(body)
        sess.clarify_count = 0
        plan = Plan("llm", v.tier, True, kb_ids=v.kb_ids, priority="P4")
        plan.say(body)
        if v.tier == Tier.partial:
            dept = kbv.kb.entries[v.kb_ids[0]].department if v.kb_ids else ctx.directory.default
            if "?" not in v.text:
                plan.say(L(sess, "partial_offer", dept=ctx.directory.name(dept)))
            sess.pending = Flow("human_offer", "offer", {"question": redact(text)[:200], "dept": dept})
        else:
            plan.say(L(sess, "anything_else"))
            plan.awaiting = "anything_else"
        return plan

    def _rule_or_unanswered(self) -> RuleResult:
        return self.rules.rule("R-UNANSWERED")
