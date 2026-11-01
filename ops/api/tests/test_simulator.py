"""dev/simulate_calls.py + dev/sim_lib: replays every brain-stream fixture against an in-process app."""
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from resolvix_ops.orm import Call, Ticket, TicketEvent, Turn

from _m2 import drain, settle

DEV_DIR = Path(__file__).parent.parent / "dev"
STREAMS = Path(__file__).parent.parent.parent.parent / "contracts" / "fixtures" / "brain_streams"
SERVICE_KEY = "test-service-key-12345"

if str(DEV_DIR) not in sys.path:
    sys.path.insert(0, str(DEV_DIR))
spec = importlib.util.spec_from_file_location("dev_simulate_calls", DEV_DIR / "simulate_calls.py")
sim_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim_cli)
from sim_lib import load_scenarios, run_simulation  # noqa: E402
from sim_lib.runner import PACING  # noqa: E402

EXPECTED_OUTCOMES = {
    "01_faq_answer_hi": "answered", "02_llm_answer_en": "answered", "03_unknown_ticket_hinglish": "escalated",
    "04_urgent_exam_transfer": "transferred", "05_emergency_safety": "emergency", "06_complaint_confirmed": "escalated",
    "07_human_request": "transferred", "08_llm_failure_fallback": "failed", "09_partial_answer": "answered",
}
ROLL_NUMBER = "2400271549999"


def fixture_actions():
    """[(file stem, action dict)] straight from the fixture files."""
    out = []
    for path in sorted(STREAMS.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            data = json.loads(line)
            if data.get("type") == "action":
                out.append((path.stem, data["action"]))
    return out


def run(client, **kwargs):
    lines = []
    kwargs.setdefault("speed", 0)
    results = run_simulation(client, out=lines.append, **kwargs)
    return results, lines


class GapMissingClient:
    """Wraps a client and answers POST /v1/gaps with 404, as before the gap endpoints exist."""

    def __init__(self, inner):
        self.inner = inner
        self.posts = []

    def get(self, url, **kw):
        return self.inner.get(url, **kw)

    def post(self, url, **kw):
        self.posts.append(url)
        if url == "/v1/gaps":
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}})
        return self.inner.post(url, **kw)


class LiveModeClient(GapMissingClient):
    def get(self, url, **kw):
        if url == "/healthz":
            return httpx.Response(200, json={"status": "ok", "notify_mode": "live"})
        return self.inner.get(url, **kw)


def test_all_fixtures_replay_and_end_with_the_expected_outcome(service_client):
    results, lines = run(service_client)
    assert [r.name for r in results] == list(EXPECTED_OUTCOMES)
    assert all(r.ok for r in results), [r.notes for r in results if not r.ok]
    assert {r.name: r.outcome for r in results} == EXPECTED_OUTCOMES
    assert len(lines) == len(results)
    ai = {}
    for result in results:
        body = service_client.get(f"/v1/calls/{result.call_id}").json()["call"]  # detail is {call, turns}
        assert body["outcome"] == result.outcome and body["ended_at"] is not None
        assert body["turns_count"] >= 1
        assert result.call_id.startswith("sim-") and result.name.split("_", 1)[1].replace("_", "-") in result.call_id
        ai[result.name] = body["ai_resolved"]
    assert ai["01_faq_answer_hi"] and ai["02_llm_answer_en"]
    assert not ai["09_partial_answer"] and not ai["04_urgent_exam_transfer"]


def test_counts_match_the_fixtures(ops_app, service_client):
    results, _ = run(service_client)
    actions = fixture_actions()
    tickets = [a for _, a in actions if a["kind"] == "create_ticket"]
    transfers = [a for _, a in actions if a["kind"] == "transfer"]
    with ops_app.state.session_factory() as db:
        assert db.query(Call).count() == len(list(STREAMS.glob("*.jsonl"))) == 9
        assert db.query(Call).filter(Call.ended_at.is_(None)).count() == 0
        assert db.query(Turn).count() == 9  # one done summary per fixture
        assert db.query(Ticket).count() == len(tickets) == sum(len(r.tickets) for r in results)
        kinds = [e.kind for e in db.query(TicketEvent).all() if e.kind.startswith("transfer_")]
        assert sorted(kinds) == sorted(["transfer_attempted", "transfer_connected"] * len(transfers))
    assert sum(r.turns for r in results) == 9
    assert sum(r.sms for r in results) == len([1 for _, a in actions if a["kind"] == "send_sms"])


def test_ticket_prefixes_and_global_sequence(ops_app, service_client):
    results, _ = run(service_client)
    prefixes = {d.key: d.ticket_prefix for d in ops_app.state.departments_config.departments}
    fixture_departments = {}
    for stem, action in fixture_actions():
        if action["kind"] == "create_ticket":
            fixture_departments[stem] = action["ticket"]["department"]
    numbers = []
    for result in results:
        for ticket_id in result.tickets:
            ticket = service_client.get(f"/v1/tickets/{ticket_id}").json()
            assert ticket["department"] == fixture_departments[result.name]
            assert ticket_id.startswith(prefixes[ticket["department"]] + "-")
            assert ticket["call_id"] == result.call_id
            numbers.append(int(ticket_id.split("-")[1]))
    assert numbers == list(range(1001, 1001 + len(numbers)))  # one global sequence, in replay order
    assert len(numbers) == len(fixture_departments) == 6


def test_p1_fixtures_raise_alert_p1(ops_app, service_client):
    _, queue = ops_app.state.sse_hub.subscribe()
    results, _ = run(service_client)
    events = drain(queue, 1) + settle(queue, 0.5)
    names = [name for name, _ in events]
    alerts = [data for name, data in events if name == "alert.p1"]
    p1_tickets = {t for r in results if r.name in ("04_urgent_exam_transfer", "05_emergency_safety") for t in r.tickets}
    assert {a["ticket_id"] for a in alerts} == p1_tickets and len(alerts) == 2
    assert names.count("call.started") == 9 and names.count("call.ended") == 9 and names.count("call.turn") == 9
    assert names.count("ticket.created") == 6
    assert all(d["outcome"] for n, d in events if n == "call.ended")


def test_rerun_creates_new_calls_and_tickets_without_errors(ops_app, service_client):
    first, _ = run(service_client)
    second, _ = run(service_client)
    assert all(r.ok for r in first + second)
    assert {r.call_id for r in first}.isdisjoint({r.call_id for r in second})
    assert {t for r in first for t in r.tickets}.isdisjoint({t for r in second for t in r.tickets})
    with ops_app.state.session_factory() as db:
        assert db.query(Call).count() == 18 and db.query(Ticket).count() == 12


def test_same_run_id_is_idempotent(ops_app, service_client):
    first, _ = run(service_client, run_id="fixed1")
    second, _ = run(service_client, run_id="fixed1")
    assert all(r.ok for r in second)
    assert [r.call_id for r in first] == [r.call_id for r in second]
    assert [r.tickets for r in first] == [r.tickets for r in second]
    with ops_app.state.session_factory() as db:
        assert db.query(Call).count() == 9 and db.query(Ticket).count() == 6 and db.query(Turn).count() == 9


def test_transfer_events_are_simulated_string_payloads(service_client):
    results, _ = run(service_client, only="urgent_exam_transfer")
    assert [r.name for r in results] == ["04_urgent_exam_transfer"]
    events = service_client.get(f"/v1/tickets/{results[0].tickets[0]}/events").json()["items"]
    assert [e["kind"] for e in events][:2] == ["transfer_attempted", "transfer_connected"]
    for event in events[:2]:
        assert event["payload"]["mode"] == "simulated" and event["payload"]["department"] == "exam_cell"
        assert all(isinstance(v, str) for v in event["payload"].values())


def test_fail_transfers_flag_reports_transfer_failed(service_client):
    results, _ = run(service_client, only="human_request", fail_transfers=True)
    events = service_client.get(f"/v1/tickets/{results[0].tickets[0]}/events").json()["items"]
    assert [e["kind"] for e in events][:2] == ["transfer_attempted", "transfer_failed"]
    assert events[1]["payload"]["reason"] == "no_answer_20s"
    assert results[0].outcome == "escalated" and results[0].ok


def test_sms_goes_through_the_policy_and_is_recorded(service_client):
    results, _ = run(service_client, only="complaint_confirmed")
    result = results[0]
    assert result.sms == 1 and not [n for n in result.notes if "suppressed" in n]
    events = service_client.get(f"/v1/tickets/{result.tickets[0]}/events").json()["items"]
    sent = [e for e in events if e["kind"] == "sms_sent"]
    assert len(sent) == 1 and sent[0]["payload"].get("mode") == "mock"
    # the emergency staff alert passes the whitelist (consent staff, department sms_alert number)
    emergency, _ = run(service_client, only="emergency_safety")
    assert emergency[0].sms == 1 and not emergency[0].notes


def test_ticket_id_placeholder_is_replaced_in_the_turn_text(service_client):
    results, _ = run(service_client, only="unknown_ticket")
    result = results[0]
    turn = service_client.get(f"/v1/calls/{result.call_id}").json()["turns"][0]
    assert "{{ticket_id}}" not in turn["assistant_text"] and result.tickets[0] in turn["assistant_text"]


def test_gap_is_posted_or_skipped_never_a_failure(service_client):
    results, _ = run(service_client, only="unknown_ticket")
    result = results[0]
    assert result.ok and result.gaps + result.skipped_gaps == 1


def test_gap_404_is_logged_and_skipped(service_client):
    client = GapMissingClient(service_client)
    results, lines = run(client)
    assert all(r.ok for r in results)
    assert sum(r.skipped_gaps for r in results) == 1 and "gap skipped (404" in "\n".join(lines)
    assert client.posts.count("/v1/gaps") == 1


def test_live_sms_mode_skips_all_sms(service_client):
    client = LiveModeClient(service_client)
    results, lines = run(client)
    assert all(r.ok for r in results)
    assert "/v1/notifications/sms" not in client.posts and sum(r.sms for r in results) == 0
    assert any("live" in line for line in lines)


def test_failed_step_marks_scenario_failed_but_still_ends_the_call(ops_app, service_client):
    class Reject(GapMissingClient):
        def post(self, url, **kw):
            if url == "/v1/tickets":
                return httpx.Response(422, json={"error": {"code": "validation_error", "message": "private text"}})
            return self.inner.post(url, **kw)

    results, lines = run(Reject(service_client), only="urgent_exam")
    assert not results[0].ok
    assert "private text" not in "\n".join(lines) and "422 validation_error" in "\n".join(lines)
    with ops_app.state.session_factory() as db:
        assert db.query(Call).filter(Call.ended_at.is_(None)).count() == 0


def test_speed_scales_the_pauses(service_client):
    def total(speed):
        slept = []
        run_simulation(service_client, speed=speed, only="urgent_exam", out=lambda _l: None, sleep=slept.append)
        return sum(slept)

    slow, fast = total(1.0), total(10.0)
    assert slow > 3 and fast == pytest.approx(slow / 10)
    never = []
    run_simulation(service_client, speed=0, out=lambda _l: None, sleep=never.append)
    assert never == []
    assert PACING["between_scenarios"] > 0


def test_scenario_selection_by_name():
    assert load_scenarios("no-such-scenario") == []
    assert [s.name for s in load_scenarios("faq_answer_hi,human")] == ["01_faq_answer_hi", "07_human_request"]
    assert len(load_scenarios()) == 9


def test_output_never_contains_numbers_pii_or_keys(service_client):
    results, lines = run(service_client)
    text = "\n".join(lines)
    for forbidden in ("+91", ROLL_NUMBER, SERVICE_KEY, "Data Structures", "Noida", "fainted", "Wi-Fi"):
        assert forbidden not in text
    assert all(r.call_id in line for r, line in zip(results, lines))


def _factory(ops_app):
    class Ctx:
        def __init__(self, base_url, headers, timeout):
            self.client = TestClient(ops_app, base_url=base_url, headers=headers)

        def __enter__(self):
            return self.client  # do not re-enter the app lifespan (ops_app is already running)

        def __exit__(self, *exc):
            return False

    return Ctx


def test_cli_end_to_end(ops_app, monkeypatch, capsys):
    monkeypatch.setenv("SERVICE_KEY", SERVICE_KEY)
    monkeypatch.setattr(sim_cli.httpx, "Client", _factory(ops_app))
    code = sim_cli.main(["--speed", "0", "--base-url", "http://testserver", "--run-id", "cli1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "9/9 scenarios completed" in out
    assert out.count("call=sim-") == 9 and "outcome=emergency" in out
    for forbidden in ("+91", ROLL_NUMBER, SERVICE_KEY):
        assert forbidden not in out
    with ops_app.state.session_factory() as db:
        assert db.query(Call).count() == 9


def test_cli_only_and_usage_errors(ops_app, monkeypatch, capsys):
    monkeypatch.setenv("SERVICE_KEY", SERVICE_KEY)
    monkeypatch.setattr(sim_cli.httpx, "Client", _factory(ops_app))
    assert sim_cli.main(["--speed", "0", "--only", "faq_answer_hi"]) == 0
    assert capsys.readouterr().out.count("call=sim-") == 1
    assert sim_cli.main(["--only", "nope"]) == 2
    assert "Available:" in capsys.readouterr().out


def test_cli_unreachable_server_exits_2(monkeypatch, capsys):
    monkeypatch.setenv("SERVICE_KEY", SERVICE_KEY)
    code = sim_cli.main(["--speed", "0", "--base-url", "http://127.0.0.1:1", "--only", "faq_answer_hi"])
    assert code == 2 and "Cannot reach" in capsys.readouterr().out
