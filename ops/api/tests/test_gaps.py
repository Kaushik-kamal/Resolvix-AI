"""Gap endpoints: POST /v1/gaps, GET /v1/gaps/clusters, PATCH /v1/gaps/clusters/{id}."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from resolvix_contracts import ErrorEnvelope, GapCluster, GapCreate

from _m2 import SERVICE_KEY, audit_rows, drain, load_fixture, settle
from resolvix_ops.app import create_app
from resolvix_ops.orm import Gap, GapCluster as GapClusterRow

STATUSES = ["new", "needs_document", "answered", "ignored"]


def post_gap(client, auth, question="Hostel fee kab tak jama karni hai?", dept="accounts", **extra):
    body = {"question": question, "lang": "hinglish", "department_guess": dept, **extra}
    return client.post("/v1/gaps", json=body, headers=auth)


def clusters(client, auth, **params):
    r = client.get("/v1/gaps/clusters", params=params, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ------------------------------------------------------------------ contract fixtures
def test_gap_fixtures_validate_against_the_models():
    GapCreate.model_validate(load_fixture("gap_create"))
    GapCluster.model_validate(load_fixture("gap_cluster"))


def test_post_contract_fixture_201_and_listed_cluster_matches_model(client, auth, fixture_json):
    body = fixture_json("gap_create")
    r = client.post("/v1/gaps", json=body, headers=auth)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "ok" and out["cluster_id"] == "gc-1" and out["count"] == 1 and out["gap_id"] == 1

    items = clusters(client, auth)
    assert len(items) == 1
    cluster = GapCluster.model_validate(items[0])  # exact GapCluster fields, Strict model rejects extras
    assert set(items[0]) == set(GapCluster.model_fields)
    assert cluster.cluster_id == "gc-1"
    assert cluster.department == "transport"
    assert cluster.count == 1
    assert cluster.examples == [body["question"]]
    assert cluster.status == "new"
    assert cluster.last_seen.tzinfo is not None
    assert items[0]["last_seen"].endswith("+00:00")
    assert cluster.label  # keyword label, e.g. "Bus Noida"

    with client.app.state.session_factory() as db:
        gap = db.query(Gap).one()
        assert (gap.question, gap.lang, gap.department_guess) == (body["question"], "hinglish", "transport")
        assert (gap.call_id, gap.ticket_id, gap.cluster_id) == ("call-unknown", "TR-1041", "gc-1")


def test_post_with_only_required_fields(client, auth):
    r = client.post("/v1/gaps", json={"question": "Library timings?", "lang": "en"}, headers=auth)
    assert r.status_code == 201
    (c,) = clusters(client, auth)
    assert c["department"] is None
    with client.app.state.session_factory() as db:
        row = db.query(GapClusterRow).one()
        assert row.cluster_key == "unknown|library|timings"


# ------------------------------------------------------------------ auth
def test_401_without_credentials(client):
    for r in (
        client.post("/v1/gaps", json={"question": "q", "lang": "en"}),
        client.get("/v1/gaps/clusters"),
        client.patch("/v1/gaps/clusters/gc-1", json={"status": "ignored"}),
    ):
        assert r.status_code == 401
        assert ErrorEnvelope.model_validate(r.json()).error.code == "unauthorized"


def test_401_with_wrong_service_key(client):
    r = client.get("/v1/gaps/clusters", headers={"X-Service-Key": "nope"})
    assert r.status_code == 401


def test_session_users_can_use_gap_endpoints(admin_client, staff_client):
    # department scoping: exam_cell staff only work on exam_cell clusters
    body = {"question": "Bus route kya hai", "lang": "hinglish", "department_guess": "exam_cell"}
    assert admin_client.post("/v1/gaps", json=body).status_code == 201
    assert staff_client.get("/v1/gaps/clusters").status_code == 200
    assert staff_client.patch("/v1/gaps/clusters/gc-1", json={"status": "needs_document"}).status_code == 200


# ------------------------------------------------------------------ validation
@pytest.mark.parametrize("body", [
    {"lang": "en"},                                             # question missing
    {"question": "q"},                                          # lang missing
    {"question": "q", "lang": "fr"},                            # lang outside the enum
    {"question": "q", "lang": "en", "unexpected": 1},           # Strict model: extra field
    {"question": 5, "lang": "en"},                              # wrong type
    {"question": "   ", "lang": "en"},                          # blank question
    {"question": "", "lang": "en"},
])
def test_post_validation_errors_are_422_envelopes(client, auth, body):
    r = client.post("/v1/gaps", json=body, headers=auth)
    assert r.status_code == 422
    assert ErrorEnvelope.model_validate(r.json()).error.code == "validation_error"
    assert clusters(client, auth) == []


def test_post_invalid_json_is_422(client, auth):
    r = client.post("/v1/gaps", content=b"{not json", headers={**auth, "Content-Type": "application/json"})
    assert r.status_code == 422


# ------------------------------------------------------------------ clustering through the endpoint
def test_same_topic_increments_one_cluster(client, auth):
    ids = []
    for q in ("Hostel fee kab tak jama karni hai?", "fee hostel kab", "What is the hostel fee?"):
        r = post_gap(client, auth, q)
        assert r.status_code == 201
        ids.append(r.json()["cluster_id"])
    assert ids == ["gc-1"] * 3
    (c,) = clusters(client, auth)
    assert c["count"] == 3
    assert c["label"] == "Fee Hostel"
    assert c["department"] == "accounts"


def test_different_topics_and_departments_make_different_clusters(client, auth):
    a = post_gap(client, auth, "hostel fee", "accounts").json()["cluster_id"]
    b = post_gap(client, auth, "hostel fee", "hostel").json()["cluster_id"]
    c = post_gap(client, auth, "hostel fee", None).json()["cluster_id"]
    d = post_gap(client, auth, "exam date", "accounts").json()["cluster_id"]
    assert len({a, b, c, d}) == 4
    assert {i["cluster_id"]: i["department"] for i in clusters(client, auth)} == {
        a: "accounts", b: "hostel", c: None, d: "accounts"}


def test_devanagari_question_clusters(client, auth):
    post_gap(client, auth, "छात्रावास की फीस कब तक जमा करनी है?")
    r = post_gap(client, auth, "फीस छात्रावास कब")
    assert r.json()["count"] == 2
    (c,) = clusters(client, auth)
    assert c["label"] == "छात्रावास फीस"


def test_blank_department_string_clusters_as_unknown(client, auth):
    r1 = post_gap(client, auth, "hostel fee", "")
    r2 = post_gap(client, auth, "hostel fee", None)
    assert r1.json()["cluster_id"] == r2.json()["cluster_id"]
    assert clusters(client, auth)[0]["department"] is None


# ------------------------------------------------------------------ examples
def test_examples_are_last_five_newest_last(client, auth):
    for i in range(8):
        post_gap(client, auth, f"hostel fee variant{i}")
    # every question has hostel/fee/variantN all freq 1 -> first two by occurrence = hostel, fee
    (c,) = clusters(client, auth)
    assert c["count"] == 8
    assert c["examples"] == [f"hostel fee variant{i}" for i in range(3, 8)]


def test_identical_examples_are_deduped_and_move_to_the_end(client, auth):
    for q in ("hostel fee a", "hostel fee b", "hostel fee a", "hostel fee c"):
        post_gap(client, auth, q)
    (c,) = clusters(client, auth)
    assert c["count"] == 4  # every post counts
    assert c["examples"] == ["hostel fee b", "hostel fee a", "hostel fee c"]


def test_example_text_is_stripped(client, auth):
    post_gap(client, auth, "  hostel fee  ")
    post_gap(client, auth, "hostel fee")
    (c,) = clusters(client, auth)
    assert c["examples"] == ["hostel fee"]


# ------------------------------------------------------------------ ordering and filter
def test_sorted_by_count_desc_then_last_seen_desc(service_client, freeze_clock):
    def at(minute):
        freeze_clock(datetime(2026, 10, 23, 10, minute, tzinfo=timezone.utc))

    def add(q, dept="accounts"):
        assert service_client.post("/v1/gaps", json={"question": q, "lang": "en", "department_guess": dept}).status_code == 201

    at(0)
    add("alpha topic")           # count 1, oldest
    at(1)
    add("bravo topic")           # count 1
    at(2)
    add("charlie topic")         # count 1, newest of the singles
    at(3)
    add("delta topic")
    at(4)
    add("delta topic")
    at(5)
    add("delta topic")           # count 3
    at(6)
    add("echo topic")
    at(7)
    add("echo topic")            # count 2
    at(8)
    add("alpha topic")           # alpha -> count 2, now seen latest

    items = service_client.get("/v1/gaps/clusters").json()["items"]
    assert [(i["label"], i["count"]) for i in items] == [
        ("Delta Topic", 3), ("Alpha Topic", 2), ("Echo Topic", 2), ("Charlie Topic", 1), ("Bravo Topic", 1)]
    assert items[1]["last_seen"] == "2026-10-23T10:08:00+00:00"
    assert items[2]["last_seen"] == "2026-10-23T10:07:00+00:00"


def test_status_filter_is_additive_and_validated(client, auth):
    post_gap(client, auth, "alpha beta")
    post_gap(client, auth, "gamma delta")
    assert client.patch("/v1/gaps/clusters/gc-2", json={"status": "answered"}, headers=auth).status_code == 200
    assert [i["cluster_id"] for i in clusters(client, auth)] == ["gc-2", "gc-1"]  # equal counts: newest first
    assert [i["cluster_id"] for i in clusters(client, auth, status="answered")] == ["gc-2"]
    assert [i["cluster_id"] for i in clusters(client, auth, status="new")] == ["gc-1"]
    assert clusters(client, auth, status="ignored") == []
    assert client.get("/v1/gaps/clusters", params={"status": "bogus"}, headers=auth).status_code == 422


def test_empty_list(client, auth):
    assert clusters(client, auth) == []


# ------------------------------------------------------------------ PATCH
@pytest.mark.parametrize("new_status", STATUSES)
def test_patch_sets_every_contract_status(client, auth, new_status):
    post_gap(client, auth)
    r = client.patch("/v1/gaps/clusters/gc-1", json={"status": new_status}, headers=auth)
    assert r.status_code == 200, r.text
    assert GapCluster.model_validate(r.json()).status == new_status
    assert clusters(client, auth)[0]["status"] == new_status


def test_patch_writes_an_audit_row_with_the_actor(client, auth):
    post_gap(client, auth)
    client.patch("/v1/gaps/clusters/gc-1", json={"status": "needs_document"}, headers=auth)
    client.patch("/v1/gaps/clusters/gc-1", json={"status": "answered"}, headers=auth)
    rows = audit_rows(client, "gap_cluster_updated")
    assert [(a, e, i) for a, _, e, i, _ in rows] == [("service", "gap_cluster", "gc-1")] * 2
    assert [d["status"] for *_, d in rows] == [
        {"from": "new", "to": "needs_document"}, {"from": "needs_document", "to": "answered"}]


def test_patch_audit_actor_is_the_user_email(staff_client, service_client):
    service_client.post("/v1/gaps", json={"question": "bus route", "lang": "en", "department_guess": "exam_cell"})
    staff_client.patch("/v1/gaps/clusters/gc-1", json={"status": "ignored"})
    rows = audit_rows(staff_client, "gap_cluster_updated")
    assert rows[0][0] == "exam@demo"


def test_patch_unknown_cluster_is_404_envelope(client, auth):
    r = client.patch("/v1/gaps/clusters/gc-99", json={"status": "ignored"}, headers=auth)
    assert r.status_code == 404
    assert ErrorEnvelope.model_validate(r.json()).error.code == "not_found"
    assert audit_rows(client, "gap_cluster_updated") == []


@pytest.mark.parametrize("body", [{"status": "open"}, {"status": ""}, {"status": 3}, {}, {"status": None}])
def test_patch_invalid_status_is_422_and_changes_nothing(client, auth, body):
    post_gap(client, auth)
    r = client.patch("/v1/gaps/clusters/gc-1", json=body, headers=auth)
    assert r.status_code == 422
    assert ErrorEnvelope.model_validate(r.json()).error.code == "validation_error"
    assert clusters(client, auth)[0]["status"] == "new"
    assert audit_rows(client, "gap_cluster_updated") == []


@pytest.mark.parametrize("closed", ["ignored", "answered"])
def test_new_gap_in_closed_cluster_counts_but_does_not_reopen(client, auth, closed):
    post_gap(client, auth, "hostel fee")
    client.patch("/v1/gaps/clusters/gc-1", json={"status": closed}, headers=auth)
    r = post_gap(client, auth, "fee hostel kab")
    assert r.status_code == 201 and r.json() == {"status": "ok", "gap_id": 2, "cluster_id": "gc-1", "count": 2}
    (c,) = clusters(client, auth)
    assert c["count"] == 2 and c["status"] == closed
    assert c["examples"] == ["hostel fee", "fee hostel kab"]


def test_new_gap_in_needs_document_cluster_keeps_that_status(client, auth):
    post_gap(client, auth, "hostel fee")
    client.patch("/v1/gaps/clusters/gc-1", json={"status": "needs_document"}, headers=auth)
    post_gap(client, auth, "hostel fee")
    assert clusters(client, auth)[0]["status"] == "needs_document"


# ------------------------------------------------------------------ concurrency
def test_20_concurrent_posts_to_one_key_count_20(live_server):
    headers = {"X-Service-Key": SERVICE_KEY}
    barrier = threading.Barrier(20)

    def worker(i):
        with httpx.Client(base_url=live_server.base_url, timeout=30) as c:
            barrier.wait(timeout=10)
            r = c.post("/v1/gaps", json={"question": f"Hostel fee kab jama hogi {i}?", "lang": "hinglish",
                                         "department_guess": "accounts"}, headers=headers)
            return r.status_code, r.json()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(worker, range(20)))
    assert [s for s, _ in results] == [201] * 20, results
    assert {b["cluster_id"] for _, b in results} == {"gc-1"}
    assert sorted(b["count"] for _, b in results) == list(range(1, 21))  # each POST saw a distinct count

    with httpx.Client(base_url=live_server.base_url, timeout=30) as c:
        items = c.get("/v1/gaps/clusters", headers=headers).json()["items"]
    assert len(items) == 1 and items[0]["count"] == 20
    assert len(items[0]["examples"]) == 5
    with live_server.app.state.session_factory() as db:
        assert db.query(Gap).count() == 20
        assert db.query(GapClusterRow).count() == 1


def test_concurrent_posts_to_different_keys_make_distinct_clusters(live_server):
    headers = {"X-Service-Key": SERVICE_KEY}
    topics = ["alpha topic", "bravo topic", "charlie topic", "delta topic"]
    barrier = threading.Barrier(20)

    def worker(i):
        with httpx.Client(base_url=live_server.base_url, timeout=30) as c:
            barrier.wait(timeout=10)
            return c.post("/v1/gaps", json={"question": topics[i % 4], "lang": "en"}, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        assert list(pool.map(worker, range(20))) == [201] * 20
    with httpx.Client(base_url=live_server.base_url, timeout=30) as c:
        items = c.get("/v1/gaps/clusters", headers=headers).json()["items"]
    assert sorted(i["cluster_id"] for i in items) == ["gc-1", "gc-2", "gc-3", "gc-4"]
    assert [i["count"] for i in items] == [5, 5, 5, 5]


# ------------------------------------------------------------------ SSE gap.created
def test_gap_created_fires_once_per_post_with_the_documented_payload(client, auth):
    _, q = client.app.state.sse_hub.subscribe()
    r1 = post_gap(client, auth, "hostel fee", call_id="call-1")
    r2 = post_gap(client, auth, "fee hostel kab", call_id="call-2")
    events = drain(q, 2) + settle(q)
    assert [n for n, _ in events] == ["gap.created", "gap.created"]
    first, second = (d for _, d in events)
    assert first["gap_id"] == r1.json()["gap_id"] and second["gap_id"] == r2.json()["gap_id"]
    assert (first["count"], second["count"]) == (1, 2)
    assert first["cluster_id"] == second["cluster_id"] == "gc-1"
    assert first["label"] == "Fee Hostel"
    assert first["department_guess"] == "accounts"
    assert first["ts"].endswith("+00:00")
    assert set(first) == {"gap_id", "cluster_id", "label", "department_guess", "count", "ts"}


def test_gap_created_has_no_phone_numbers_or_call_data(client, auth):
    _, q = client.app.state.sse_hub.subscribe()
    post_gap(client, auth, "call me on +91 90000 00001 about fees", call_id="call-9")
    (name, data), = drain(q, 1)
    assert name == "gap.created"
    assert "+91" not in repr(data) and "9000000001" not in repr(data) and "90000" not in repr(data)
    assert "question" not in data and "call_id" not in data
    (c,) = clusters(client, auth)  # neither the label nor the example shown on the dashboard carries the number
    assert "9000" not in repr(c)
    assert c["examples"] == ["call me on ••• about fees"]
    with client.app.state.session_factory() as db:
        assert "9000" not in db.query(Gap).one().question


def test_gap_created_not_emitted_for_rejected_requests(client, auth):
    _, q = client.app.state.sse_hub.subscribe()
    assert client.post("/v1/gaps", json={"question": "x", "lang": "xx"}, headers=auth).status_code == 422
    assert client.post("/v1/gaps", json={"question": "x", "lang": "en"}).status_code == 401
    assert settle(q) == []


def test_gap_created_not_emitted_and_nothing_stored_when_commit_fails(test_settings, auth, fail_next_commit):
    app = create_app(test_settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        _, q = app.state.sse_hub.subscribe()
        fail_next_commit()
        assert post_gap(c, auth).status_code == 500
        assert settle(q) == []
        assert clusters(c, auth) == []  # gap and cluster rolled back together
        with app.state.session_factory() as db:
            assert db.query(Gap).count() == 0
        # the next request works and is the first event
        assert post_gap(c, auth).status_code == 201
        events = drain(q, 1) + settle(q)
        assert [n for n, _ in events] == ["gap.created"]
        assert events[0][1]["count"] == 1
    app.state.engine.dispose()


def test_patch_emits_no_gap_event(client, auth):
    post_gap(client, auth)
    _, q = client.app.state.sse_hub.subscribe()
    client.patch("/v1/gaps/clusters/gc-1", json={"status": "answered"}, headers=auth)
    assert settle(q) == []
