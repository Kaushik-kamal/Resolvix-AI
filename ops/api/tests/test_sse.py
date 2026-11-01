"""SSE: hub unit tests, publish-after-commit behaviour, and a real streaming integration over uvicorn."""
import asyncio
import json
import threading
import time

import httpx

from _m2 import drain, make_ticket_body, settle
from resolvix_ops.sse import SSEHub


# ------------------------------------------------------------------ hub unit tests
def test_hub_preserves_order_and_adds_ts():
    async def scenario():
        hub = SSEHub()
        hub.set_loop(asyncio.get_running_loop())
        _, q = hub.subscribe()
        await asyncio.to_thread(lambda: [hub.publish("ticket.created", {"n": i}) for i in range(10)])
        events = [await asyncio.wait_for(q.get(), 2) for _ in range(10)]
        assert [d["n"] for _, d in events] == list(range(10))
        assert all(name == "ticket.created" and d["ts"].endswith("+00:00") for name, d in events)

    asyncio.run(scenario())


def test_hub_queue_is_bounded_and_drops_oldest():
    async def scenario():
        hub = SSEHub()
        hub.set_loop(asyncio.get_running_loop())
        _, q = hub.subscribe()
        await asyncio.to_thread(lambda: [hub.publish("e", {"n": i}) for i in range(150)])
        await asyncio.sleep(0.2)
        assert q.qsize() == 100
        items = [q.get_nowait()[1]["n"] for _ in range(100)]
        assert items == list(range(50, 150))  # oldest 50 dropped, order kept

    asyncio.run(scenario())


def test_hub_slow_subscriber_does_not_block_others():
    async def scenario():
        hub = SSEHub()
        hub.set_loop(asyncio.get_running_loop())
        _, slow = hub.subscribe()  # never drained
        _, fast = hub.subscribe()
        await asyncio.to_thread(lambda: [hub.publish("e", {"n": i}) for i in range(300)])
        got = []
        while len(got) < 100:
            got.append(await asyncio.wait_for(fast.get(), 2))
        assert slow.qsize() == 100

    asyncio.run(scenario())


def test_hub_subscribe_unsubscribe_count():
    hub = SSEHub()
    ids = [hub.subscribe()[0] for _ in range(3)]
    assert hub.subscriber_count() == 3
    for i in ids:
        hub.unsubscribe(i)
    hub.unsubscribe(999)  # unknown id is harmless
    assert hub.subscriber_count() == 0


def test_hub_publish_without_loop_or_after_loop_closed_never_raises():
    hub = SSEHub()
    assert hub.publish("e", {}) is False
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    loop.close()
    assert hub.publish("e", {}) is False


# ------------------------------------------------------------------ publish only after a successful, non-duplicate commit
def test_ticket_events_not_published_for_duplicate_422_or_failed_commit(
        test_settings, auth, fixture_json, fail_next_commit):
    from fastapi.testclient import TestClient
    from resolvix_ops.app import create_app

    app = create_app(test_settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        _, q = app.state.sse_hub.subscribe()
        p1 = make_ticket_body(fixture_json, "k1", priority="P1")
        assert c.post("/v1/tickets", json=p1, headers=auth).status_code == 201
        assert c.post("/v1/tickets", json=p1, headers=auth).status_code == 200          # duplicate
        bad = make_ticket_body(fixture_json, "k2", priority="P1", department="nope")
        assert c.post("/v1/tickets", json=bad, headers=auth).status_code == 422          # rejected
        fail_next_commit()
        boom = make_ticket_body(fixture_json, "k3", priority="P1")
        assert c.post("/v1/tickets", json=boom, headers=auth).status_code == 500         # rolled back
        events = drain(q, 2) + settle(q)
    app.state.engine.dispose()
    assert [n for n, _ in events] == ["ticket.created", "alert.p1"]  # only the first request published


def test_call_events_not_published_when_commit_fails(test_settings, auth, fixture_json, fail_next_commit):
    from fastapi.testclient import TestClient
    from resolvix_ops.app import create_app

    app = create_app(test_settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        _, q = app.state.sse_hub.subscribe()
        fail_next_commit()
        assert c.post("/v1/calls", json=fixture_json("call_start"), headers=auth).status_code == 500
        assert settle(q) == []
        assert c.get("/v1/calls", headers=auth).json()["items"] == []  # nothing stored either
    app.state.engine.dispose()


def test_p1_and_non_p1_events_via_hub(client, auth, fixture_json):
    _, q = client.app.state.sse_hub.subscribe()
    client.post("/v1/tickets", json=make_ticket_body(fixture_json, "p1", priority="P1"), headers=auth)
    client.post("/v1/tickets", json=make_ticket_body(fixture_json, "p2", priority="P2"), headers=auth)
    events = drain(q, 3) + settle(q)
    assert [n for n, _ in events] == ["ticket.created", "alert.p1", "ticket.created"]
    for _, d in events:
        assert "ts" in d and d["caller_number"] == "+91•••••0006"


def test_ticket_updated_event_on_patch(client, auth, fixture_json):
    tid = client.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
    _, q = client.app.state.sse_hub.subscribe()
    client.patch(f"/v1/tickets/{tid}", json={"status": "resolved", "assignee": "exam@demo"}, headers=auth)
    (name, data), = drain(q, 1)
    assert name == "ticket.updated"
    assert data["ticket_id"] == tid and data["status"] == "resolved" and data["assignee"] == "exam@demo"
    assert "ts" in data and "caller_number" not in data


# ------------------------------------------------------------------ real streaming integration
class SSEReader:
    """Reads /v1/stream over a real socket in a thread and records (event, data, monotonic_time)."""

    def __init__(self, base_url, headers):
        self.events = []
        self.comments = []
        self.connected = threading.Event()
        self.status = None
        self._client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, read=30.0))
        self._headers = headers
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            with self._client.stream("GET", "/v1/stream", headers=self._headers) as r:
                self.status = r.status_code
                if r.status_code != 200:
                    self.connected.set()
                    return
                event = None
                for line in r.iter_lines():
                    if line.startswith(":"):
                        self.comments.append(line)
                        self.connected.set()
                    elif line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        self.events.append((event, json.loads(line.split(":", 1)[1].strip()), time.monotonic()))
        except httpx.HTTPError:
            self.connected.set()

    def wait_for(self, name, timeout=1.0, start=0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for e in self.events[start:]:
                if e[0] == name:
                    return e
            time.sleep(0.01)
        return None

    def close(self):
        self._client.close()
        self._thread.join(timeout=5)


def test_stream_requires_auth(live_server):
    r = httpx.get(live_server.base_url + "/v1/stream", timeout=5)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_stream_p1_ticket_delivers_created_and_alert_within_1s_masked(live_server, auth, fixture_json):
    hub = live_server.app.state.sse_hub
    reader = SSEReader(live_server.base_url, auth)
    try:
        assert reader.connected.wait(5) and reader.status == 200
        assert hub.subscriber_count() == 1
        with httpx.Client(base_url=live_server.base_url, timeout=10) as api:
            t0 = time.monotonic()
            r = api.post("/v1/tickets", json=make_ticket_body(fixture_json, "p1", priority="P1"), headers=auth)
            assert r.status_code == 201
            created = reader.wait_for("ticket.created", 1.0)
            alert = reader.wait_for("alert.p1", 1.0)
        assert created and alert, reader.events
        assert created[2] - t0 < 1.0 and alert[2] - t0 < 1.0
        for _, data, _ in (created, alert):
            assert data["ticket_id"] == r.json()["ticket_id"]
            assert data["caller_number"] == "+91•••••0006" and "9000000006" not in json.dumps(data)
            assert "ts" in data
    finally:
        reader.close()


def test_stream_p2_ticket_has_no_alert(live_server, auth, fixture_json):
    reader = SSEReader(live_server.base_url, auth)
    try:
        assert reader.connected.wait(5)
        with httpx.Client(base_url=live_server.base_url, timeout=10) as api:
            api.post("/v1/tickets", json=make_ticket_body(fixture_json, "p2", priority="P2"), headers=auth)
        assert reader.wait_for("ticket.created", 1.0)
        time.sleep(0.5)
        assert [e[0] for e in reader.events] == ["ticket.created"]
    finally:
        reader.close()


def test_stream_call_lifecycle_events_and_two_subscribers(live_server, auth, fixture_json):
    r1 = SSEReader(live_server.base_url, auth)
    r2 = SSEReader(live_server.base_url, auth)
    try:
        assert r1.connected.wait(5) and r2.connected.wait(5)
        assert live_server.app.state.sse_hub.subscriber_count() == 2
        turn = fixture_json("turn_summary")
        with httpx.Client(base_url=live_server.base_url, timeout=10) as api:
            api.post("/v1/calls", json=fixture_json("call_start"), headers=auth)
            api.post("/v1/calls/call-urgent-exam/turns", json=turn, headers=auth)
            api.post("/v1/calls/call-urgent-exam/end", json=fixture_json("call_end"), headers=auth)
        for reader in (r1, r2):
            assert reader.wait_for("call.ended", 1.5)
            assert [e[0] for e in reader.events] == ["call.started", "call.turn", "call.ended"]
    finally:
        r1.close()
        r2.close()


def test_stream_disconnect_unsubscribes(live_server, auth):
    hub = live_server.app.state.sse_hub
    reader = SSEReader(live_server.base_url, auth)
    assert reader.connected.wait(5)
    assert hub.subscriber_count() == 1
    reader.close()
    deadline = time.monotonic() + 5
    while hub.subscriber_count() != 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert hub.subscriber_count() == 0


def test_stream_sends_keepalive_pings(live_server, auth, monkeypatch):
    from resolvix_ops.routers import sse_routes
    assert sse_routes.PING_SECONDS == 15  # production value
    monkeypatch.setattr(sse_routes, "PING_SECONDS", 0.3)  # shortened so the test does not wait 15 s
    reader = SSEReader(live_server.base_url, auth)
    try:
        assert reader.connected.wait(5)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any("ping" in c for c in reader.comments):
            time.sleep(0.05)
        assert any("ping" in c for c in reader.comments), reader.comments
    finally:
        reader.close()


def test_stream_closes_after_the_session_is_revoked(live_server, monkeypatch):
    from resolvix_ops.routers import sse_routes
    from resolvix_ops.seed_users import seed_users_if_needed
    monkeypatch.setattr(sse_routes, "PING_SECONDS", 0.3)
    app = live_server.app
    with app.state.session_factory() as db:
        seed_users_if_needed(db, app.state.settings, {d.key for d in app.state.departments_config.departments})
    with httpx.Client(base_url=live_server.base_url, timeout=10) as api:
        r = api.post("/v1/auth/login", json={"email": "admin@demo", "password": app.state.settings.seed_password})
        assert r.status_code == 200
        cookie = api.cookies.get("resolvix_session")
        reader = SSEReader(live_server.base_url, {"Cookie": f"resolvix_session={cookie}"})
        try:
            assert reader.connected.wait(5) and reader.status == 200
            assert live_server.app.state.sse_hub.subscriber_count() == 1
            api.post("/v1/auth/logout")  # revokes the session on the server
            deadline = time.monotonic() + 5
            while live_server.app.state.sse_hub.subscriber_count() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert live_server.app.state.sse_hub.subscriber_count() == 0  # the server closed the stream
        finally:
            reader.close()
