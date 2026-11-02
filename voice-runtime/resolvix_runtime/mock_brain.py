from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from pydantic import TypeAdapter
from resolvix_contracts.models import (
    BrainEvent,
    CallContext,
    CallStartPlan,
    KBSource,
    KBVersionInfo,
    Lang,
    TurnRequest,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "brain_streams"
BRAIN_EVENT_ADAPTER = TypeAdapter(BrainEvent)

SCENARIOS_MAP = [
    (lambda t: ("exam" in t and "minute" in t) or "2400271549999" in t or "data structures" in t, "04_urgent_exam_transfer.jsonl"),
    (lambda t: "behosh" in t or "ambulance" in t, "05_emergency_safety.jsonl"),
    (lambda t: "hostel gate" in t, "02_llm_answer_en.jsonl"),
    (lambda t: "bus" in t or "route" in t or "isi number par call" in t, "03_unknown_ticket_hinglish.jsonl"),
    (lambda t: "complaint" in t or "wifi" in t or "haan sahi hai" in t, "06_complaint_confirmed.jsonl"),
    (lambda t: "insaan" in t or "human" in t, "07_human_request.jsonl"),
    (lambda t: "fail" in t or ("admission" in t and "document" in t), "08_llm_failure_fallback.jsonl"),
    (lambda t: "re-evaluation" in t or "reevaluation" in t, "09_partial_answer.jsonl"),
    (lambda t: "fee" in t or "fees" in t, "01_faq_answer_hi.jsonl"),
]



class MockBrain:
    """Replays contracts/fixtures/brain_streams/*.jsonl according to the Brain protocol."""

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = fixtures_dir or FIXTURES_DIR
        self.active_kb_version = "mock-kb-1.0.0"
        self.sessions: dict[str, CallContext] = {}

    async def start_call(self, ctx: CallContext) -> CallStartPlan:
        self.sessions[ctx.call_id] = ctx
        return CallStartPlan(
            kb_version=self.active_kb_version,
            greeting_text="Namaste, aap college helpline par hain. Main AI sahayak hoon, yeh call record ho sakti hai. Batayiye, kya madad karun?",
            greeting_lang=Lang.hinglish,
            interruptable=False,
        )

    def _select_scenario_file(self, req: TurnRequest) -> Path:
        all_text = req.user_text + " " + " ".join(m.content for m in req.history)
        normalized = all_text.lower()
        for predicate, filename in SCENARIOS_MAP:
            if predicate(normalized):
                return self.fixtures_dir / filename
        return self.fixtures_dir / "01_faq_answer_hi.jsonl"

    async def handle_turn(self, req: TurnRequest) -> AsyncIterator[BrainEvent]:
        fixture_file = self._select_scenario_file(req)

        if not fixture_file.exists():
            raise FileNotFoundError(f"Fixture file not found: {fixture_file}")

        lines = fixture_file.read_text(encoding="utf-8").strip().splitlines()
        # line 0 is _request, remaining lines are events
        for raw_line in lines[1:]:
            if not raw_line.strip():
                continue
            data = json.loads(raw_line)

            # Rewrite call_id and turn_index to match live request
            if data.get("type") == "action":
                action = data.get("action", {})
                kind = action.get("kind")
                if kind == "create_ticket":
                    ticket = action.get("ticket", {})
                    ticket["call_id"] = req.call_id
                    ticket_type = ticket.get("type", "URGENT")
                    ticket["idempotency_key"] = f"{req.call_id}:{req.turn_index}:{ticket_type}"
                elif kind == "send_sms":
                    template_id = action.get("template_id", "ticket_created")
                    to_number = action.get("to_number", "")
                    action["idempotency_key"] = f"{req.call_id}:{template_id}:{to_number}"

            elif data.get("type") == "done":
                summary = data.get("summary", {})
                summary["call_id"] = req.call_id
                summary["turn_index"] = req.turn_index

            event = BRAIN_EVENT_ADAPTER.validate_python(data)
            yield event

    async def end_call(self, call_id: str) -> None:
        self.sessions.pop(call_id, None)

    async def reload_kb(self, source: KBSource) -> KBVersionInfo:
        if source.kind == "file":
            path = Path(source.location)
            if not path.exists():
                raise ValueError(f"KB file not found at {source.location}")
        elif source.kind == "url":
            if not source.location.startswith(("http://", "https://")):
                raise ValueError(f"Invalid KB url: {source.location}")

        self.active_kb_version = "reloaded-" + datetime.now(timezone.utc).strftime("%H%M%S")
        return KBVersionInfo(
            kb_version=self.active_kb_version,
            entry_count=15,
            faq_count=6,
            token_count=1850,
            activated_at=datetime.now(timezone.utc),
            warnings=[],
        )

    def health(self) -> dict:
        return {
            "status": "ok",
            "kb_version": self.active_kb_version,
            "llm": "ok",
            "contract_version": "1.0.0",
        }
