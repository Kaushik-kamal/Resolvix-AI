"""SMS ordering per ticket and the ticket.updated that follows a background send."""
import threading

from fastapi.testclient import TestClient

from _m2 import CountingProvider, drain, make_ticket_body, sms_rows
from resolvix_ops.app import create_app
from resolvix_ops.services.notify import ShardedExecutor
from test_sms_async import SlowProvider, wait_for


def test_sharded_executor_keeps_fifo_per_key():
    ex = ShardedExecutor(2, "sms-test")
    seen = {"A": [], "B": []}
    gate = threading.Event()
    futures = [ex.submit("A", gate.wait, 2)]
    futures += [ex.submit("A", seen["A"].append, i) for i in range(30)]
    futures += [ex.submit("B", seen["B"].append, i) for i in range(30)]
    gate.set()
    for f in futures:
        f.result(timeout=5)
    ex.shutdown()
    assert seen["A"] == list(range(30)) and seen["B"] == list(range(30))


def test_same_key_always_lands_on_the_same_worker():
    ex = ShardedExecutor(2, "sms-test2")
    names = {ex.submit("EX-1001", lambda: threading.current_thread().name).result(timeout=5) for _ in range(10)}
    ex.shutdown()
    assert len(names) == 1


def test_quick_status_changes_reach_the_provider_in_order(test_settings, auth, fixture_json):
    provider = CountingProvider()
    app = create_app(test_settings.model_copy(update={"notify_async": True}))
    app.state.sms.provider = provider
    with TestClient(app) as c:
        tid = c.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
        for status in ("in_progress", "resolved", "closed"):
            c.patch(f"/v1/tickets/{tid}", json={"status": status}, headers=auth)
        assert wait_for(lambda: len(provider.sent) == 3)
    app.state.engine.dispose()
    assert [b.rsplit("is now ", 1)[1] for _, b, _ in provider.sent] == ["in progress.", "resolved.", "closed."]


def test_ticket_updated_is_published_when_a_background_sms_finishes(test_settings, auth, fixture_json):
    app = create_app(test_settings.model_copy(update={"notify_async": True}))
    provider = SlowProvider()
    app.state.sms.provider = provider
    with TestClient(app) as c:
        tid = c.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
        _, q = app.state.sse_hub.subscribe()
        c.patch(f"/v1/tickets/{tid}", json={"status": "in_progress"}, headers=auth)
        assert [n for n, _ in drain(q, 1)] == ["ticket.updated"]  # from the PATCH itself
        assert provider.started.wait(5) and sms_rows(c)[0].status == "queued"
        provider.release.set()
        second = drain(q, 1, timeout=5)  # from the finished send
        assert [n for n, _ in second] == ["ticket.updated"] and second[0][1]["ticket_id"] == tid
        assert wait_for(lambda: sms_rows(c)[0].status == "sent")
        kinds = [e["kind"] for e in c.get(f"/v1/tickets/{tid}/events", headers=auth).json()["items"]]
        assert "sms_sent" in kinds
    app.state.engine.dispose()


def test_synchronous_mock_mode_publishes_only_the_patch_event(sms_client, auth, fixture_json):
    tid = sms_client.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
    _, q = sms_client.app.state.sse_hub.subscribe()
    sms_client.patch(f"/v1/tickets/{tid}", json={"status": "in_progress"}, headers=auth)
    assert [n for n, _ in drain(q, 2, timeout=1.0)] == ["ticket.updated"]
