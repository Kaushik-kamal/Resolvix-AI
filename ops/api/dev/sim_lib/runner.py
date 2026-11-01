"""Replays the brain-stream fixtures against the Ops API, the way the voice runtime (Member A) would.

run_simulation(client, ...) takes any object with .post(url, json=...) and .get(url) returning httpx-style
responses (httpx.Client or a Starlette TestClient). The client carries the base URL and the X-Service-Key header.

Output rules: one line per scenario with the scenario name, call id, ticket ids and outcome. Phone numbers, summaries,
transcripts and response bodies are never printed.
"""
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from resolvix_contracts import (
    TICKET_ID_PLACEHOLDER, CallEnd, CallStart, GapCreate, SmsRequest, TicketCreate, TicketEvent, TurnSummary)

from .scenarios import Scenario, load_scenarios

IST = timezone(timedelta(hours=5, minutes=30))

# Nominal pauses in seconds at --speed 1.0 (a speed of 10 divides them by 10; speed <= 0 never sleeps).
PACING = {
    "call_setup": 0.8,         # between POST /v1/calls and the first action
    "action": 0.7,             # between two actions of the stream
    "speech_per_char": 0.025,  # simulated time the agent spends speaking, per character
    "speech_max": 3.0,
    "transfer_ring": 2.0,      # between transfer_attempted and transfer_connected / transfer_failed
    "before_end": 1.0,         # between the last step and POST /v1/calls/{id}/end
    "between_scenarios": 1.5,
}

NOT_YET_BUILT = {404, 405}  # gap / KB endpoints may be missing while other agents build them


class StepError(Exception):
    """A required endpoint answered with an unexpected status (the message never contains a body)."""


@dataclass
class ScenarioResult:
    name: str
    call_id: str
    tickets: list[str] = field(default_factory=list)
    outcome: str | None = None
    ok: bool = True
    notes: list[str] = field(default_factory=list)
    turns: int = 0
    events: int = 0
    sms: int = 0
    gaps: int = 0
    skipped_gaps: int = 0


def _now() -> datetime:
    return datetime.now(IST)


def _error_code(response) -> str:
    try:
        return str(response.json().get("error", {}).get("code", "?"))
    except Exception:
        return "?"


def _fill(value: str, ticket_id: str | None) -> str:
    return value.replace(TICKET_ID_PLACEHOLDER, ticket_id) if ticket_id else value


class _Replay:
    def __init__(self, client, scenario: Scenario, run_id: str, sleep: Callable[[float], None],
                 speed: float, fail_transfers: bool, send_sms: bool):
        self.client, self.sc, self.run_id = client, scenario, run_id
        self._sleep, self.speed = sleep, speed
        self.fail_transfers, self.send_sms = fail_transfers, send_sms
        self.old_call_id = scenario.original_call_id
        self.call_id = f"sim-{scenario.short_name.replace('_', '-')}-{run_id}"
        self.result = ScenarioResult(name=scenario.name, call_id=self.call_id)
        self.ticket_id: str | None = None
        self.ticket_type: str | None = None
        self.transferred = False
        self.transfer_department: str | None = None
        self.ended_early = False
        meta = next((e for e in scenario.events if e.get("type") == "meta"), {})
        self.meta = meta
        self.lang = meta.get("lang", "hinglish")

    # ---------------------------------------------------------------- helpers
    def pause(self, seconds: float):
        if self.speed > 0 and seconds > 0:
            self._sleep(seconds / self.speed)

    def rekey(self, key: str) -> str:
        """Fresh idempotency key per run: same shape as the fixture's, with the new call id and the run id."""
        return f"{key.replace(self.old_call_id, self.call_id)}:{self.run_id}"

    def post(self, path: str, body: dict, ok: set[int]):
        response = self.client.post(path, json=body)
        if response.status_code not in ok:
            raise StepError(f"POST {path} -> {response.status_code} {_error_code(response)}")
        return response

    # ---------------------------------------------------------------- stream steps
    def start_call(self):
        number = next((e["action"]["ticket"].get("caller_number") for e in self.sc.events
                       if e.get("type") == "action" and e["action"].get("kind") == "create_ticket"), None)
        number = number or f"+9190000011{self.sc.index:02d}"
        body = CallStart(call_id=self.call_id, channel="pstn", caller_number=number, started_at=_now(),
                         kb_version="a1b2c3d4e5f6", lang=self.lang).model_dump(mode="json")
        self.post("/v1/calls", body, {200, 201})

    def create_ticket(self, action: dict):
        data = dict(action["ticket"])
        data["idempotency_key"] = self.rekey(data["idempotency_key"])
        data["call_id"] = self.call_id
        body = TicketCreate.model_validate(data).model_dump(mode="json")
        response = self.post("/v1/tickets", body, {200, 201})
        self.ticket_id = response.json()["ticket_id"]
        self.ticket_type = data["type"]
        self.result.tickets.append(self.ticket_id)

    def ticket_event(self, kind: str, payload: dict[str, str]):
        if not self.ticket_id:
            raise StepError(f"{kind} before any ticket exists")
        body = TicketEvent(kind=kind, payload={k: str(v) for k, v in payload.items()}, actor="system",
                           at=_now()).model_dump(mode="json")
        self.post(f"/v1/tickets/{self.ticket_id}/events", body, {200, 201})
        self.result.events += 1

    def transfer(self, action: dict):
        base = {"to_number": action["to_number"], "department": action["department"], "mode": "simulated"}
        self.ticket_event("transfer_attempted", {**base, "reason": action["reason"]})
        self.pause(PACING["transfer_ring"])
        if self.fail_transfers:
            self.ticket_event("transfer_failed", {**base, "reason": "no_answer_20s"})
        else:
            self.ticket_event("transfer_connected", base)
            self.transferred = True
        self.transfer_department = action["department"]

    def send_sms_action(self, action: dict):
        if not self.send_sms:
            self.result.notes.append("sms skipped (server is in live SMS mode)")
            return
        variables = {k: _fill(v, self.ticket_id) for k, v in action["vars"].items()}
        if any(TICKET_ID_PLACEHOLDER in v for v in variables.values()):
            raise StepError("send_sms needs a ticket id but no ticket exists yet")
        body = SmsRequest(
            idempotency_key=self.rekey(action["idempotency_key"]), to_number=action["to_number"],
            template_id=action["template_id"], vars=variables, consent=action["consent"],
            call_id=self.call_id, ticket_id=self.ticket_id).model_dump(mode="json")
        response = self.post("/v1/notifications/sms", body, {200, 202})
        self.result.sms += 1
        status = response.json().get("status")
        if status == "suppressed":
            self.result.notes.append(f"sms suppressed ({response.json().get('reason')})")

    def log_gap(self, action: dict):
        body = GapCreate(question=action["question"], lang=action["lang"],
                         department_guess=action.get("department_guess"), call_id=self.call_id,
                         ticket_id=self.ticket_id).model_dump(mode="json")
        response = self.client.post("/v1/gaps", json=body)
        if response.status_code in NOT_YET_BUILT:
            self.result.skipped_gaps += 1
            self.result.notes.append(f"gap skipped ({response.status_code}: endpoint not available yet)")
            return
        if response.status_code not in {200, 201}:
            raise StepError(f"POST /v1/gaps -> {response.status_code} {_error_code(response)}")
        self.result.gaps += 1

    def schedule_callback(self, action: dict):
        self.ticket_event("callback_scheduled", {"reason": action["reason"], "mode": "simulated"})

    def post_turn(self, summary: dict):
        data = dict(summary)
        data["call_id"] = self.call_id
        data["assistant_text"] = _fill(data["assistant_text"], self.ticket_id)
        data["created_at"] = _now().isoformat()
        body = TurnSummary.model_validate(data).model_dump(mode="json")
        self.post(f"/v1/calls/{self.call_id}/turns", body, {200, 201})
        self.result.turns += 1
        self.turn_index = body["turn_index"]

    def _fail(self, exc: Exception):
        self.result.ok = False
        self.result.notes.append(str(exc) if isinstance(exc, StepError) else f"{type(exc).__name__} (see fixture/server)")

    def derive_outcome(self) -> str:
        path = self.meta.get("path")
        if self.transferred and (self.ticket_type == "EMERGENCY" or self.transfer_department == "emergency"
                                 or path == "safety"):
            return "emergency"
        if self.transferred:
            return "transferred"
        if self.ticket_type == "SYSTEM_FAILURE" or path == "fallback":
            return "failed"
        if self.result.tickets:
            return "escalated"
        return "answered"

    def end_call(self):
        outcome = self.derive_outcome()
        self.result.outcome = outcome
        ai_resolved = outcome == "answered" and self.meta.get("tier") == "confident"
        body = CallEnd(ended_at=_now(), outcome=outcome, ai_resolved=ai_resolved,
                       turns_count=getattr(self, "turn_index", self.sc.turn_index) + 1).model_dump(mode="json")
        self.post(f"/v1/calls/{self.call_id}/end", body, {200})

    # ---------------------------------------------------------------- the scenario
    def run(self) -> ScenarioResult:
        try:
            self.start_call()
            self.pause(PACING["call_setup"])
            for event in self.sc.events:
                kind = event.get("type")
                if kind == "speech":
                    self.pause(min(PACING["speech_max"], len(event.get("text", "")) * PACING["speech_per_char"]))
                elif kind == "action":
                    action = event["action"]
                    step = action["kind"]
                    if step == "create_ticket":
                        self.create_ticket(action)
                    elif step == "transfer":
                        self.transfer(action)
                    elif step == "send_sms":
                        self.send_sms_action(action)
                    elif step == "log_gap":
                        self.log_gap(action)
                    elif step == "schedule_callback":
                        self.schedule_callback(action)
                    elif step == "end_call":
                        self.ended_early = True
                    self.pause(PACING["action"])
                elif kind == "done":
                    self.post_turn(event["summary"])
                if self.ended_early:
                    break
            self.pause(PACING["before_end"])
        except Exception as exc:  # StepError, a fixture that fails model validation, a dropped connection
            self._fail(exc)
        try:
            self.end_call()  # always try to close the call so the dashboard never shows a stuck live call
        except Exception as exc:
            self._fail(exc)
        return self.result


def format_result(result: ScenarioResult) -> str:
    tickets = ",".join(result.tickets) or "-"
    line = (f"{'ok  ' if result.ok else 'FAIL'} {result.name} call={result.call_id} tickets={tickets} "
            f"outcome={result.outcome or '-'}")
    if result.notes:
        line += " | " + "; ".join(result.notes)
    return line


def run_simulation(client, speed: float = 1.0, only: str | None = None, run_id: str | None = None, *,
                   fail_transfers: bool = False, sleep: Callable[[float], None] = time.sleep,
                   out: Callable[[str], None] = print, scenarios: list[Scenario] | None = None
                   ) -> list[ScenarioResult]:
    """Replay each fixture stream once; returns one ScenarioResult per scenario (ok=False on a real failure).

    A missing gap endpoint (404/405) is logged and skipped, never a failure. If the server reports live SMS mode the
    SMS steps are skipped, so the simulator can never text the (fake but possibly real) fixture numbers.
    """
    run_id = run_id or uuid.uuid4().hex[:6]
    scenarios = scenarios if scenarios is not None else load_scenarios(only)
    send_sms = True
    health = client.get("/healthz")
    if health.status_code == 200 and health.json().get("notify_mode") == "live":
        send_sms = False
        out("note: server NOTIFY mode is live; SMS steps are skipped")
    results = []
    for position, scenario in enumerate(scenarios):
        result = _Replay(client, scenario, run_id, sleep, speed, fail_transfers, send_sms).run()
        out(format_result(result))
        results.append(result)
        if position < len(scenarios) - 1:
            if speed > 0:
                sleep(PACING["between_scenarios"] / speed)
    return results
