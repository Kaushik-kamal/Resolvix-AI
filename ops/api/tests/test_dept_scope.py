"""Department scoping: staff see only their department; admin and service see everything (PRD P1-07)."""
import time

import pytest
from fastapi.testclient import TestClient

from _m2 import make_ticket_body
from helpers.fixtures import _login


@pytest.fixture
def world(ops_app, service_client, fixture_json):
    """exam ticket + accounts ticket (each with its own call), two gap clusters, and logged-in clients."""
    def call(call_id):
        body = fixture_json("call_start")
        body["call_id"] = call_id
        assert service_client.post("/v1/calls", json=body).status_code == 201

    call("c-exam")
    call("c-acct")
    call("c-none")  # answered by the AI: no ticket
    ids = {}
    for key, dept, call_id in (("exam", "exam_cell", "c-exam"), ("acct", "accounts", "c-acct")):
        r = service_client.post("/v1/tickets", json=make_ticket_body(fixture_json, key, department=dept, call_id=call_id))
        ids[key] = r.json()["ticket_id"]
    for q, dept in (("exam hall ticket?", "exam_cell"), ("fee receipt?", "accounts"), ("unknown thing here", None)):
        service_client.post("/v1/gaps", json={"question": q, "lang": "en", "department_guess": dept})
    return {
        "ids": ids, "service": service_client,
        "admin": _login(ops_app, "admin@demo"), "exam": _login(ops_app, "exam@demo"),
        "acct": _login(ops_app, "accounts@demo"),
    }


def test_ticket_list_is_scoped(world):
    ids = world["ids"]
    assert [t["ticket_id"] for t in world["exam"].get("/v1/tickets").json()["items"]] == [ids["exam"]]
    assert [t["ticket_id"] for t in world["acct"].get("/v1/tickets").json()["items"]] == [ids["acct"]]
    for who in ("admin", "service"):
        assert {t["ticket_id"] for t in world[who].get("/v1/tickets").json()["items"]} == set(ids.values())


def test_staff_cannot_filter_their_way_out_of_scope(world):
    items = world["exam"].get("/v1/tickets?department=accounts").json()["items"]
    assert items == []


def test_ticket_detail_patch_and_events_outside_scope_are_404(world):
    other = world["ids"]["acct"]
    exam = world["exam"]
    for r in (exam.get(f"/v1/tickets/{other}"), exam.get(f"/v1/tickets/{other}?reveal=true"),
              exam.patch(f"/v1/tickets/{other}", json={"status": "resolved"}),
              exam.get(f"/v1/tickets/{other}/events")):
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert world["service"].get(f"/v1/tickets/{other}").json()["status"] == "open"  # untouched
    own = world["ids"]["exam"]
    assert exam.patch(f"/v1/tickets/{own}", json={"status": "in_progress"}).status_code == 200
    assert exam.get(f"/v1/tickets/{own}/events").status_code == 200


def test_calls_are_limited_to_calls_with_a_ticket_in_the_department(world):
    exam, admin = world["exam"], world["admin"]
    assert [c["call_id"] for c in exam.get("/v1/calls").json()["items"]] == ["c-exam"]
    assert {c["call_id"] for c in admin.get("/v1/calls").json()["items"]} == {"c-exam", "c-acct", "c-none"}
    assert exam.get("/v1/calls/c-exam").status_code == 200
    for hidden in ("c-acct", "c-none"):
        assert exam.get(f"/v1/calls/{hidden}").status_code == 404
    assert admin.get("/v1/calls/c-none").status_code == 200


def test_gap_clusters_are_scoped_by_department(world):
    exam = world["exam"]
    items = exam.get("/v1/gaps/clusters").json()["items"]
    assert {c["department"] for c in items} == {"exam_cell"}
    assert {c["department"] for c in world["admin"].get("/v1/gaps/clusters").json()["items"]} == {"exam_cell", "accounts", None}
    other = [c for c in world["admin"].get("/v1/gaps/clusters").json()["items"] if c["department"] == "accounts"][0]
    assert exam.patch(f"/v1/gaps/clusters/{other['cluster_id']}", json={"status": "ignored"}).status_code == 404
    mine = items[0]
    assert exam.patch(f"/v1/gaps/clusters/{mine['cluster_id']}", json={"status": "needs_document"}).status_code == 200


def test_staff_without_a_department_sees_nothing(ops_app, service_client, fixture_json):
    from resolvix_ops.auth import hash_password
    from resolvix_ops.orm import User
    with ops_app.state.session_factory() as db:
        db.add(User(email="nodept@demo", password_hash=hash_password(ops_app.state.settings.seed_password),
                    role="staff", department=None))
        db.commit()
    service_client.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"))
    assert _login(ops_app, "nodept@demo").get("/v1/tickets").json()["items"] == []


def test_scope_can_be_switched_off(app_factory, fixture_json):
    app = app_factory(seed_users_on_startup=True, staff_scope_enabled=False)
    with TestClient(app) as svc:
        svc.headers["X-Service-Key"] = "test-service-key-12345"
        svc.post("/v1/tickets", json=make_ticket_body(fixture_json, "k", department="accounts"))
        assert len(_login(app, "exam@demo").get("/v1/tickets").json()["items"]) == 1


def test_stream_events_are_filtered_per_subscriber(ops_app, service_client, fixture_json):
    hub = ops_app.state.sse_hub
    from resolvix_ops.scope import event_visible
    _, q_exam = hub.subscribe(lambda n, d: event_visible("exam_cell", n, d))
    _, q_all = hub.subscribe()
    service_client.post("/v1/calls", json=fixture_json("call_start"))
    service_client.post("/v1/tickets", json=make_ticket_body(fixture_json, "a", department="accounts", priority="P1"))
    service_client.post("/v1/tickets", json=make_ticket_body(fixture_json, "e", department="exam_cell", priority="P1"))
    service_client.post("/v1/gaps", json={"question": "fee receipt?", "lang": "en", "department_guess": "accounts"})
    time.sleep(0.5)

    def names(q):
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    exam_events = names(q_exam)
    assert [n for n, _ in exam_events] == ["ticket.created", "alert.p1"]
    assert all(d["department"] == "exam_cell" for _, d in exam_events)
    assert len(names(q_all)) == 6  # call.started + 2x(ticket.created, alert.p1) + gap.created (the subscriber without a filter sees all)


def test_event_visible_rules():
    from resolvix_ops.scope import event_visible
    assert event_visible(None, "call.started", {}) is True
    assert event_visible("exam_cell", "call.started", {}) is False
    assert event_visible("exam_cell", "ticket.updated", {"department": "exam_cell"}) is True
    assert event_visible("exam_cell", "ticket.updated", {"department": "hostel"}) is False
    assert event_visible("exam_cell", "gap.created", {"department_guess": None}) is False
    assert event_visible("exam_cell", "something.else", {}) is False
