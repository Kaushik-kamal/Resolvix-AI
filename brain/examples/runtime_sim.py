"""Reference runtime + in-memory ops service: a *worked example* of how Member A drives the Brain and how Member C's
ops-api reacts. It is NOT Member A's or Member C's code and does not replace either; it exists so that

  * Member A can copy the patterns (ticket-first executor, placeholder substitution, barge-in handling, SSE shape),
  * the Brain's integration behaviour can be tested today, before voice-runtime/ and ops/ exist.

Everything here is a MOCK of those two components (see docs/INTEGRATION_TEST_PLAN.md: "mocked integration").
Only depends on resolvix_contracts and resolvix_brain.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from resolvix_contracts import TICKET_ID_PLACEHOLDER, speak_ticket_id
from resolvix_contracts.models import (
    CallContext, CallChannel, DepartmentsConfig, GapCreate, SmsRequest, SmsResult, TicketCreate, TicketEvent,
    TurnRequest, TurnSummary,
)

# runtime_lines.yaml equivalents (Member A owns the real ones)
RUNTIME_LINES = {
    "registered_no_id": {"hi": "Aapki request darj ho gayi hai, staff aapse jald sampark karega.",
                         "en": "Your request has been registered, staff will contact you soon."},
    "transfer_failed": {"hi": "Staff abhi uplabdh nahi hain. Aapka request {id} khula hai, aapko jaldi contact kiya jayega.",
                        "en": "Staff are not available right now. Your request {id} is open and you will be contacted soon."},
    "transfer_simulated": {"hi": "Test mode: transfer dikhaya gaya hai.", "en": "Test mode: transfer simulated."},
}


class OpsDown(Exception):
    pass


# =========================================================================== mock of Member C's ops-api
class FakeOps:
    """In-memory stand-in for ops-api: idempotent tickets (id = <dept prefix>-<seq from 1001>), SMS policy-lite with
    dedupe, gaps, ticket events, turn log, and the SSE events the dashboard would receive (alert.p1 etc.)."""

    SMS_TEMPLATES = {"ticket_created", "status_change", "answer_copy", "staff_alert"}

    def __init__(self, departments: DepartmentsConfig, down: bool = False, latency_s: float = 0.0):
        self.prefix = {d.key: d.ticket_prefix for d in departments.departments}
        self.seq = 1000
        self.down, self.latency = down, latency_s
        self.tickets: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.sms: dict[str, dict] = {}
        self.sms_duplicates: list[str] = []
        self.gaps: list[dict] = []
        self.events: list[tuple[str, dict]] = []      # (ticket_id, TicketEvent-like)
        self.turns: dict[tuple[str, int], dict] = {}
        self.calls: dict[str, dict] = {}
        self.stream: list[tuple[str, dict]] = []      # SSE: (event name, data)

    async def _gate(self) -> None:
        if self.latency:
            await asyncio.sleep(self.latency)
        if self.down:
            raise OpsDown("ops-api unreachable")

    async def post_call(self, payload: dict) -> None:
        await self._gate()
        self.calls.setdefault(payload["call_id"], payload)
        self.stream.append(("call.started", payload))

    async def create_ticket(self, t: TicketCreate) -> tuple[str, bool]:
        await self._gate()
        TicketCreate.model_validate_json(t.model_dump_json())       # the payload is valid per the frozen contract
        if t.idempotency_key in self.by_key:
            return self.by_key[t.idempotency_key], False
        self.seq += 1
        tid = f"{self.prefix.get(t.department, 'HD')}-{self.seq}"
        row = {**json.loads(t.model_dump_json()), "ticket_id": tid, "status": "open", "notes": [], "assignee": None}
        self.tickets[tid] = row
        self.by_key[t.idempotency_key] = tid
        self.stream.append(("ticket.created", row))
        if t.priority == "P1":
            self.stream.append(("alert.p1", row))
        return tid, True

    async def post_sms(self, req: SmsRequest) -> SmsResult:
        await self._gate()
        SmsRequest.model_validate_json(req.model_dump_json())
        if req.idempotency_key in self.sms:           # duplicate key: return the original result, send nothing
            self.sms_duplicates.append(req.idempotency_key)
            return SmsResult.model_validate(self.sms[req.idempotency_key]["result"])
        if req.template_id not in self.SMS_TEMPLATES or TICKET_ID_PLACEHOLDER in json.dumps(req.vars):
            res = SmsResult(message_id="-", status="suppressed", mode="mock", reason="template/placeholder")
        else:
            res = SmsResult(message_id=f"mock-{len(self.sms) + 1}", status="queued", mode="mock")
        self.sms[req.idempotency_key] = {"result": res.model_dump(), "request": json.loads(req.model_dump_json())}
        return res

    async def post_gap(self, g: GapCreate) -> None:
        await self._gate()
        self.gaps.append(json.loads(g.model_dump_json()))
        self.stream.append(("gap.created", self.gaps[-1]))

    async def post_event(self, ticket_id: str, kind: str, payload: dict | None = None, at=None) -> None:
        """POST /v1/tickets/{id}/events. The frozen TicketEvent requires ``at``; the real ops-api answers 422 without it."""
        await self._gate()
        ev = TicketEvent(kind=kind, payload=payload or {}, actor="runtime", at=at)   # raises if kind/at/payload are invalid
        self.events.append((ticket_id, json.loads(ev.model_dump_json())))

    async def post_turn(self, summary: TurnSummary) -> None:
        await self._gate()
        self.turns.setdefault((summary.call_id, summary.turn_index), json.loads(summary.model_dump_json()))
        self.stream.append(("call.turn", self.turns[(summary.call_id, summary.turn_index)]))

    def dashboard_rows(self) -> list[dict]:
        """What GET /v1/tickets returns for the dashboard: P1 first, then newest first."""
        return sorted(self.tickets.values(), key=lambda t: (t["priority"], -int(t["ticket_id"].split("-")[1])))


class FakeTelephony:
    def __init__(self, answers: bool = True):
        self.answers, self.dialed = answers, []

    async def transfer(self, call_id: str, to_number: str) -> bool:
        self.dialed.append((call_id, to_number))
        return self.answers


# =========================================================================== reference runtime (what Member A builds)
@dataclass
class TurnResult:
    spoken: list[str] = field(default_factory=list)
    sse: list[str] = field(default_factory=list)
    meta: Any = None
    ticket_id: str | None = None
    ended: bool = False
    refused_transfers: int = 0


def sse_line(obj: dict | str) -> str:
    return "data: " + (obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))) + "\n\n"


class ReferenceRuntime:
    """Minimal single-process runtime. Patterns worth copying are marked with  # PATTERN."""

    def __init__(self, brain, ops: FakeOps, telephony: FakeTelephony, channel: str = "pstn", speech_delay_s: float = 0.0):
        self.brain, self.ops, self.tel, self.channel = brain, ops, telephony, channel
        self.speech_delay = speech_delay_s              # simulated time the TTS needs to speak a chunk
        self.counters: dict[str, int] = {}
        self.active: dict[str, asyncio.Task] = {}      # PATTERN: one active stream per call -> barge-in
        self.retry_queue: list[TicketCreate] = []

    # ---- call lifecycle
    async def start_call(self, call_id: str, caller_number: str | None):
        ctx = CallContext(call_id=call_id, channel=CallChannel(self.channel), caller_number=caller_number,
                          started_at=_now())
        plan = await self.brain.start_call(ctx)           # pins the KB version, returns greeting + consent line
        try:
            await self.ops.post_call({"call_id": call_id, "channel": self.channel, "caller_number": caller_number,
                                      "started_at": ctx.started_at.isoformat(), "kb_version": plan.kb_version})
        except OpsDown:
            pass                                           # PATTERN: ops outage never blocks the call
        self.counters[call_id] = 0
        return plan

    async def end_call(self, call_id: str) -> None:
        await self.brain.end_call(call_id)

    # ---- barge-in: a new request for a call cancels the stream that is still running
    def start_turn(self, call_id: str, text: str, **kw) -> asyncio.Task:
        old = self.active.get(call_id)
        if old and not old.done():
            old.cancel()                                   # PATTERN
        task = asyncio.create_task(self.turn(call_id, text, **kw))
        self.active[call_id] = task
        return task

    async def turn(self, call_id: str, text: str, *, received_at=None, dtmf: str | None = None, history=None) -> TurnResult:
        self.counters[call_id] = self.counters.get(call_id, 0) + 1
        req = TurnRequest(call_id=call_id, turn_index=self.counters[call_id], user_text=text, history=history or [],
                          dtmf=dtmf, received_at=received_at or _now())
        res = TurnResult()
        agen: AsyncIterator = self.brain.handle_turn(req)
        lang = "hi"
        try:
            async for ev in agen:
                if ev.type == "meta":
                    res.meta, lang = ev, ("en" if ev.lang == "en" else "hi")
                    res.sse.append(sse_line(_chunk(call_id, req.turn_index, "chat.completion.custom_metadata",
                                                   metadata={"interruptable": ev.interruptable})))
                elif ev.type == "speech":
                    await self._speak(ev.text, res, call_id, req.turn_index, lang)
                elif ev.type == "action":
                    # PATTERN: once the brain has handed you an action you own it. Shield it from barge-in cancellation,
                    # otherwise a cancelled turn can lose a P1 ticket that the brain believes was delivered.
                    await asyncio.shield(self._execute(ev, res, call_id, lang))
                else:  # done
                    try:
                        await self.ops.post_turn(ev.summary)
                    except OpsDown:
                        pass
        finally:
            await agen.aclose()      # PATTERN: ALWAYS close the generator so the brain records exactly what was delivered
        res.sse.append(sse_line(_chunk(call_id, req.turn_index, "chat.completion.chunk", delta={}, finish="stop")))
        res.sse.append(sse_line("[DONE]"))
        return res

    async def _speak(self, text: str, res: TurnResult, call_id: str, idx: int, lang: str) -> None:
        if TICKET_ID_PLACEHOLDER in text:
            if res.ticket_id is None or res.ticket_id.startswith("TMP-"):
                # PATTERN: ops was unreachable: drop the sentence that needs the id, say the "registered" line instead
                keep = [s for s in re.split(r"(?<=[.!?])\s+", text) if TICKET_ID_PLACEHOLDER not in s]
                text = " ".join(keep + [RUNTIME_LINES["registered_no_id"][lang]])
            else:
                text = text.replace(TICKET_ID_PLACEHOLDER, speak_ticket_id(res.ticket_id, lang))   # PATTERN
        res.spoken.append(text)
        res.sse.append(sse_line(_chunk(call_id, idx, "chat.completion.chunk",
                                       delta={"role": "assistant", "content": text})))
        if self.speech_delay:
            await asyncio.sleep(self.speech_delay)          # TTS playing; a barge-in can arrive here

    async def _execute(self, ev, res: TurnResult, call_id: str, lang: str) -> None:
        a = ev.action
        if a.kind == "create_ticket":
            try:
                res.ticket_id, _ = await self.ops.create_ticket(a.ticket)
            except OpsDown:
                res.ticket_id = f"TMP-{abs(hash(a.ticket.idempotency_key)) % 9000 + 1000}"   # PATTERN: local id + retry queue
                self.retry_queue.append(a.ticket)
        elif a.kind == "transfer":
            if a.requires_ticket and not res.ticket_id:    # PATTERN: ticket-first is enforced by the runtime too
                res.refused_transfers += 1
                return
            await self._safe_event(res.ticket_id, "transfer_attempted", {"to": a.to_number})
            if self.channel in ("web", "test"):
                await self._safe_event(res.ticket_id, "transfer_failed", {"reason": "simulated"})
                return
            ok = await self.tel.transfer(call_id, a.to_number)
            await self._safe_event(res.ticket_id, "transfer_connected" if ok else "transfer_failed", {})
            if not ok:  # PATTERN: the ticket stays open and the caller is told
                msg = RUNTIME_LINES["transfer_failed"][lang].replace(
                    "{id}", speak_ticket_id(res.ticket_id, lang) if res.ticket_id and not res.ticket_id.startswith("TMP") else "")
                await self._speak(msg, res, call_id, 0, lang)
        elif a.kind == "send_sms":
            vars_ = {k: (v.replace(TICKET_ID_PLACEHOLDER, res.ticket_id or "") if isinstance(v, str) else v) for k, v in a.vars.items()}
            try:
                await self.ops.post_sms(SmsRequest(
                    idempotency_key=a.idempotency_key, to_number=a.to_number, template_id=a.template_id, vars=vars_,
                    consent=a.consent, call_id=call_id, ticket_id=res.ticket_id))
            except OpsDown:
                pass
        elif a.kind == "log_gap":
            try:
                await self.ops.post_gap(GapCreate(question=a.question, lang=a.lang, department_guess=a.department_guess,
                                                  call_id=call_id, ticket_id=res.ticket_id))
            except OpsDown:
                pass
        elif a.kind == "end_call":
            res.ended = True

    async def _safe_event(self, ticket_id: str | None, kind: str, payload: dict) -> None:
        if ticket_id and not ticket_id.startswith("TMP-"):
            try:
                await self.ops.post_event(ticket_id, kind, payload, at=_now())    # PATTERN: the runtime stamps `at`
            except OpsDown:
                pass

    async def flush_retry_queue(self) -> int:
        """PATTERN: every ~5 s; idempotency keys make replays safe."""
        sent = 0
        for t in list(self.retry_queue):
            try:
                await self.ops.create_ticket(t)
                self.retry_queue.remove(t)
                sent += 1
            except OpsDown:
                break
        return sent


def _now():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _chunk(call_id: str, idx: int, obj: str, *, delta: dict | None = None, finish: str | None = None,
           metadata: dict | None = None) -> dict:
    base = {"id": f"resolvix-{call_id}-{idx}", "object": obj, "created": int(time.time()), "model": "resolvix-brain"}
    if obj == "chat.completion.custom_metadata":
        return {**base, "choices": [], "metadata": metadata or {}}
    return {**base, "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
