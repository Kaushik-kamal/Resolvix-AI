"""Shared helpers and fixtures for the M2 tests (calls, tickets, SSE, fixtures, auth matrix)."""
import copy
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resolvix_ops.app import create_app
from resolvix_ops.orm import AuditLog
from resolvix_ops.services.notify import Notifier

SERVICE_KEY = "test-service-key-12345"
CONTRACT_FIXTURES = Path(__file__).parent.parent.parent.parent / "contracts" / "fixtures" / "ops"


@pytest.fixture
def auth():
    """Service-principal headers (the voice runtime credentials)."""
    return {"X-Service-Key": SERVICE_KEY}


def load_fixture(name: str) -> dict:
    return json.loads((CONTRACT_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture_json():
    """Returns a function giving a fresh deep copy of a contract fixture, so tests can tweak it."""
    return lambda name: copy.deepcopy(load_fixture(name))


class RecordingNotifier(Notifier):
    def __init__(self):
        self.calls = []

    def on_ticket_status_changed(self, db, ticket, old_status, new_status, actor):
        self.calls.append((ticket.ticket_id, old_status, new_status, actor))


@pytest.fixture
def notifier():
    return RecordingNotifier()


@pytest.fixture
def client_n(test_settings, notifier):
    """TestClient whose app uses the recording notifier."""
    app = create_app(test_settings, notifier=notifier)
    with TestClient(app) as c:
        yield c
    app.state.engine.dispose()


def audit_rows(client, action: str | None = None):
    """Audit rows straight from the DB: [(actor, action, entity, entity_id, details)]."""
    with client.app.state.session_factory() as db:
        q = db.query(AuditLog)
        if action:
            q = q.filter(AuditLog.action == action)
        return [(r.actor, r.action, r.entity, r.entity_id, r.details) for r in q.order_by(AuditLog.id).all()]


def make_ticket_body(fixture_json, key: str, **overrides) -> dict:
    body = fixture_json("ticket_create")
    body["idempotency_key"] = key
    body.update(overrides)
    return body


def drain(queue, expect: int, timeout: float = 2.0):
    """Collect `expect` events from a hub subscriber queue (published from other threads)."""
    got = []
    end = time.monotonic() + timeout
    while len(got) < expect and time.monotonic() < end:
        try:
            got.append(queue.get_nowait())
        except Exception:
            time.sleep(0.01)
    return got


def settle(queue, quiet: float = 0.3):
    """Wait a short quiet period, then return everything queued (to assert nothing extra arrived)."""
    time.sleep(quiet)
    got = []
    while True:
        try:
            got.append(queue.get_nowait())
        except Exception:
            return got


# --------------------------------------------------------------------------- live server + failure injection
import socket
import threading

import uvicorn
from sqlalchemy.orm import Session


class LiveServer:
    def __init__(self, app, base_url):
        self.app = app
        self.base_url = base_url


@pytest.fixture
def live_server(test_settings):
    """Real uvicorn on a free port in a thread (TestClient cannot stream SSE or truly run concurrently)."""
    from sse_starlette.sse import AppStatus
    AppStatus.should_exit_event = None  # sse-starlette binds this to the first event loop it sees

    app = create_app(test_settings)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield LiveServer(app, f"http://127.0.0.1:{port}")
    server.should_exit = True
    thread.join(timeout=10)
    app.state.engine.dispose()


@pytest.fixture
def fail_next_commit(monkeypatch):
    """Call the returned function to make the next Session.commit() raise (simulated DB failure)."""
    real_commit = Session.commit
    state = {"armed": False}

    def commit(self):
        if state["armed"]:
            state["armed"] = False
            raise RuntimeError("simulated commit failure")
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", commit)

    def arm():
        state["armed"] = True
    return arm


# --------------------------------------------------------------------------- SMS helpers
from resolvix_ops.sms.providers import MockProvider, ProviderError, SendResult
from resolvix_ops.orm import SmsMessage


class CountingProvider(MockProvider):
    """Mock provider that records every send; `script` is a list of outcomes (exception instance or None) per call."""

    def __init__(self, script=None):
        self.sent = []
        self.script = list(script or [])

    def send(self, to_number, body, status_callback):
        outcome = self.script.pop(0) if self.script else None
        self.sent.append((to_number, body, status_callback))
        if isinstance(outcome, Exception):
            raise outcome
        return super().send(to_number, body, status_callback)


@pytest.fixture
def sms_client(client):
    """Default client with the SMS provider swapped for a counting mock."""
    client.app.state.sms.provider = CountingProvider()
    return client


def sms_rows(client):
    with client.app.state.session_factory() as db:
        return db.query(SmsMessage).order_by(SmsMessage.id).all()
