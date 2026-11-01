"""Async status-change SMS: the PATCH answers while a slow send is still pending."""
import threading
import time

from fastapi.testclient import TestClient

from _m2 import CountingProvider, make_ticket_body, sms_rows
from resolvix_ops.app import create_app
from resolvix_ops.services.notify import SmsNotifier


class SlowProvider(CountingProvider):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def send(self, to_number, body, status_callback):
        self.started.set()
        assert self.release.wait(10), "test never released the send"
        return super().send(to_number, body, status_callback)


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def sms_threads():
    return [t for t in threading.enumerate() if t.name.startswith("sms") and t.is_alive()]


def test_async_defaults(test_settings):
    assert test_settings.sms_async is False  # mock stays synchronous
    live = test_settings.model_copy(update={"notify_mode": "twilio"})
    assert live.sms_async is True
    assert live.model_copy(update={"notify_async": False}).sms_async is False
    assert test_settings.model_copy(update={"notify_async": True}).sms_async is True


def test_mock_mode_default_notifier_is_synchronous(client):
    assert client.app.state.notifier.executor is None


def test_patch_returns_while_slow_send_is_pending_then_sms_appears(test_settings, auth, fixture_json):
    app = create_app(test_settings.model_copy(update={"notify_async": True}))
    provider = SlowProvider()
    app.state.sms.provider = provider
    with TestClient(app) as c:
        assert isinstance(app.state.notifier, SmsNotifier) and app.state.notifier.executor is not None
        tid = c.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
        t0 = time.monotonic()
        r = c.patch(f"/v1/tickets/{tid}", json={"status": "in_progress"}, headers=auth)
        elapsed = time.monotonic() - t0
        assert r.status_code == 200 and r.json()["status"] == "in_progress"
        assert provider.started.wait(5)  # the worker is inside send()...
        assert elapsed < 2.0 and provider.sent == []  # ...and the PATCH did not wait for it
        (row,) = sms_rows(c)
        assert row.status == "queued"

        # a second PATCH to the same status while the first send is pending creates no second SMS
        c.patch(f"/v1/tickets/{tid}", json={"status": "in_progress"}, headers=auth)

        provider.release.set()
        assert wait_for(lambda: sms_rows(c)[0].status == "sent")
        assert len(sms_rows(c)) == 1 and len(provider.sent) == 1
        kinds = [e["kind"] for e in c.get(f"/v1/tickets/{tid}/events", headers=auth).json()["items"]]
        assert kinds == ["status_changed", "sms_sent"]
    app.state.engine.dispose()
    assert wait_for(lambda: sms_threads() == [], 5), "SMS worker threads leaked after shutdown"


def test_async_failure_is_logged_not_raised(test_settings, auth, fixture_json, caplog):
    class Exploding(CountingProvider):
        def send(self, *a, **k):
            raise RuntimeError("boom")

    app = create_app(test_settings.model_copy(update={"notify_async": True}))
    app.state.sms.provider = Exploding()
    with TestClient(app) as c:
        tid = c.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
        assert c.patch(f"/v1/tickets/{tid}", json={"status": "resolved"}, headers=auth).status_code == 200
        assert wait_for(lambda: "status-change SMS failed" in caplog.text)
    app.state.engine.dispose()


def test_shutdown_waits_for_in_flight_send(test_settings, auth, fixture_json):
    app = create_app(test_settings.model_copy(update={"notify_async": True}))
    provider = SlowProvider()
    app.state.sms.provider = provider
    with TestClient(app) as c:
        tid = c.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
        c.patch(f"/v1/tickets/{tid}", json={"status": "in_progress"}, headers=auth)
        assert provider.started.wait(5)
        threading.Timer(0.3, provider.release.set).start()
    # leaving the context ran lifespan shutdown: it waited for the send, so the record is final
    assert len(provider.sent) == 1
    assert sms_rows(c)[0].status == "sent"
    app.state.engine.dispose()
