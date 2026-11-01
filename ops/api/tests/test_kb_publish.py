"""POST /v1/kb/publish (mock + live with respx) and GET /v1/kb/publishes (agent K).
Live mode talks to a respx-mocked voice runtime; assert_all_mocked makes any unrouted request raise."""
import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from respx.models import AllMockedAssertionError
from resolvix_contracts import KBSource, KBVersionInfo

from _m2 import audit_rows, load_fixture
from helpers.fixtures import SERVICE_KEY, _login
from resolvix_ops.orm import KBPublish

from test_kb import approve, entry, save

RELOAD = "http://runtime.test/admin/kb/reload"
TIMEOUT_S = 7.5


@pytest.fixture
def live_app(test_settings):
    from resolvix_ops.app import create_app
    app = create_app(test_settings.model_copy(update=dict(
        seed_users_on_startup=True, runtime_mode="real", runtime_url="http://runtime.test/",
        kb_publish_timeout_s=TIMEOUT_S)))
    with TestClient(app):
        yield app
    app.state.engine.dispose()


@pytest.fixture
def live_admin(live_app):
    return _login(live_app, "admin@demo")


@pytest.fixture
def runtime():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


def publishes(client):
    with client.app.state.session_factory() as db:
        return [(r.kb_version, r.mode, r.actor, r.info_json) for r in db.query(KBPublish).order_by(KBPublish.id).all()]


# ------------------------------------------------------------------ mock mode
def test_mock_publish_returns_fixture_with_fresh_activated_at(admin_client, freeze_clock):
    freeze_clock(datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc))
    r = admin_client.post("/v1/kb/publish")
    assert r.status_code == 200, r.text
    info = KBVersionInfo.model_validate(r.json())
    fx = KBVersionInfo.model_validate(load_fixture("kb_version_info"))
    assert (info.kb_version, info.token_count) == (fx.kb_version, fx.token_count)
    assert info.activated_at == datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc) != fx.activated_at
    assert any("mock" in w for w in info.warnings)


def test_mock_publish_counts_exportable_entries_truthfully(admin_client, freeze_clock):
    freeze_clock(datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc))
    save(admin_client, id="FEE-101", is_faq=True)
    save(admin_client, id="FEE-102", is_faq=False)
    save(admin_client, id="FEE-103", valid_until="2026-11-01")   # expired
    save(admin_client, id="FEE-104")                              # stays draft
    for eid in ("FEE-101", "FEE-102", "FEE-103"):
        approve(admin_client, eid)
    info = admin_client.post("/v1/kb/publish").json()
    assert (info["entry_count"], info["faq_count"]) == (2, 1)


def test_mock_publish_with_no_entries_reports_zero(admin_client):
    info = admin_client.post("/v1/kb/publish").json()
    assert (info["entry_count"], info["faq_count"]) == (0, 0)


def test_mock_publish_makes_no_http_call(admin_client, runtime):
    assert admin_client.post("/v1/kb/publish").status_code == 200
    assert len(runtime.calls) == 0


def test_mock_success_is_stored_and_audited(admin_client):
    info = admin_client.post("/v1/kb/publish").json()
    ((version, mode, actor, stored_info),) = publishes(admin_client)
    assert (version, mode, actor) == (info["kb_version"], "mock", "admin@demo")
    assert KBVersionInfo.model_validate(stored_info) == KBVersionInfo.model_validate(info)
    ((a_actor, action, entity, entity_id, details),) = audit_rows(admin_client, "kb_published")
    assert (a_actor, entity, entity_id) == ("admin@demo", "kb_publish", info["kb_version"])
    assert details["mode"] == "mock" and details["entry_count"] == info["entry_count"]


# ------------------------------------------------------------------ auth
def test_publish_requires_admin_session(staff_client, service_client, anon_client, admin_client):
    for c, code in ((staff_client, 403), (service_client, 403), (anon_client, 401)):
        r = c.post("/v1/kb/publish")
        assert r.status_code == code and r.json()["error"]["code"] == "unauthorized"
    assert publishes(admin_client) == []
    assert audit_rows(admin_client, "kb_published") == []


def test_forbidden_publish_never_reaches_the_runtime(live_app, runtime):
    staff = _login(live_app, "exam@demo")
    service = TestClient(live_app, headers={"X-Service-Key": SERVICE_KEY})
    assert staff.post("/v1/kb/publish").status_code == 403 and service.post("/v1/kb/publish").status_code == 403
    assert len(runtime.calls) == 0


# ------------------------------------------------------------------ live mode
def test_live_publish_posts_kb_source_with_service_key_and_returns_a_info(live_admin, runtime, fixture_json):
    fx = fixture_json("kb_version_info")
    route = runtime.post(RELOAD).mock(return_value=httpx.Response(200, json=fx))
    r = live_admin.post("/v1/kb/publish")
    assert r.status_code == 200, r.text
    assert KBVersionInfo.model_validate(r.json()) == KBVersionInfo.model_validate(fx)

    assert route.call_count == 1
    sent = route.calls.last.request
    assert sent.headers["X-Service-Key"] == SERVICE_KEY
    body = json.loads(sent.content)
    assert KBSource.model_validate(body).kind == "url"
    assert body == fixture_json("kb_source")  # default OPS_PUBLIC_URL is http://localhost:8100
    assert sent.extensions["timeout"]["read"] == TIMEOUT_S
    assert len(runtime.calls) == 1


def test_live_publish_location_follows_ops_public_url(test_settings, runtime):
    from resolvix_ops.app import create_app
    app = create_app(test_settings.model_copy(update=dict(
        seed_users_on_startup=True, runtime_mode="live", runtime_url="http://runtime.test",
        ops_public_url="https://ops.example.test/", session_cookie_secure=False)))
    with TestClient(app):
        client = _login(app, "admin@demo")
        route = runtime.post(RELOAD).mock(return_value=httpx.Response(200, json=load_fixture("kb_version_info")))
        assert client.post("/v1/kb/publish").status_code == 200
        assert json.loads(route.calls.last.request.content) == {
            "kind": "url", "location": "https://ops.example.test/v1/kb/export"}
    app.state.engine.dispose()


def test_live_success_is_stored_with_mode_live_and_audited(live_admin, runtime, fixture_json):
    runtime.post(RELOAD).mock(return_value=httpx.Response(200, json=fixture_json("kb_version_info")))
    live_admin.post("/v1/kb/publish")
    ((version, mode, actor, info),) = publishes(live_admin)
    assert (version, mode, actor) == ("a1b2c3d4e5f6", "live", "admin@demo") and info["entry_count"] == 12
    assert audit_rows(live_admin, "kb_published")[0][4]["mode"] == "live"
    assert audit_rows(live_admin, "kb_publish_failed") == []


def test_live_422_returns_422_with_a_problems(live_admin, runtime):
    problems = {"FEE-001": "answer too long", "FEE-002": "unknown department"}
    runtime.post(RELOAD).mock(return_value=httpx.Response(422, json={"error": {
        "code": "validation_error", "message": "KB compile failed", "retryable": False, "details": problems}}))
    r = live_admin.post("/v1/kb/publish")
    assert r.status_code == 422
    err = r.json()["error"]
    assert (err["code"], err["message"], err["details"]) == ("validation_error", "KB compile failed", problems)
    assert publishes(live_admin) == []
    ((_, _, _, _, details),) = audit_rows(live_admin, "kb_publish_failed")
    assert details["status_code"] == 422 and details["details"] == problems


def test_live_422_with_unparseable_body_still_reports_something(live_admin, runtime):
    runtime.post(RELOAD).mock(return_value=httpx.Response(422, text="bad kb"))
    r = live_admin.post("/v1/kb/publish")
    assert r.status_code == 422 and r.json()["error"]["details"] == {"problems": "bad kb"}


@pytest.mark.parametrize("effect", [
    httpx.ConnectError("refused"), httpx.ConnectTimeout("slow"), httpx.ReadTimeout("slow"),
    httpx.RemoteProtocolError("dropped"),
])
def test_live_unreachable_or_timeout_is_502_upstream_error(live_admin, runtime, effect):
    runtime.post(RELOAD).mock(side_effect=effect)
    r = live_admin.post("/v1/kb/publish")
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "upstream_error" and err["retryable"] is True
    assert publishes(live_admin) == []
    ((actor, _, _, _, details),) = audit_rows(live_admin, "kb_publish_failed")
    assert actor == "admin@demo" and details["status_code"] == 502 and details["mode"] == "live"


@pytest.mark.parametrize("status", [500, 502, 503])
def test_live_5xx_is_502_upstream_error(live_admin, runtime, status):
    runtime.post(RELOAD).mock(return_value=httpx.Response(status, text="boom"))
    r = live_admin.post("/v1/kb/publish")
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error" and r.json()["error"]["retryable"]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_live_other_4xx_is_502_not_retryable(live_admin, runtime, status):
    runtime.post(RELOAD).mock(return_value=httpx.Response(status, json={"error": "x"}))
    r = live_admin.post("/v1/kb/publish")
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error" and r.json()["error"]["retryable"] is False


def test_live_invalid_version_info_is_502(live_admin, runtime):
    runtime.post(RELOAD).mock(return_value=httpx.Response(200, json={"kb_version": "x"}))
    assert live_admin.post("/v1/kb/publish").status_code == 502
    assert publishes(live_admin) == []


def test_live_non_json_200_is_502(live_admin, runtime):
    runtime.post(RELOAD).mock(return_value=httpx.Response(200, text="<html>"))
    assert live_admin.post("/v1/kb/publish").status_code == 502


def test_unrouted_request_raises_instead_of_reaching_the_network(live_admin, runtime):
    runtime.post("http://elsewhere.test/admin/kb/reload").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AllMockedAssertionError):  # RELOAD is not routed; TestClient re-raises the server error
        live_admin.post("/v1/kb/publish")
    assert publishes(live_admin) == []


# ------------------------------------------------------------------ the service key never reaches a log
@pytest.mark.parametrize("answer", [
    httpx.Response(200, json=load_fixture("kb_version_info")),
    httpx.Response(422, json={"error": {"code": "validation_error", "message": "bad", "details": {"a": "b"}}}),
    httpx.Response(503, text="down"),
    httpx.ConnectError("refused"),
    httpx.ReadTimeout("slow"),
])
def test_service_key_is_never_logged(live_admin, runtime, caplog, answer):
    caplog.set_level(logging.DEBUG)
    route = runtime.post(RELOAD)
    route.mock(side_effect=answer) if isinstance(answer, Exception) else route.mock(return_value=answer)
    live_admin.post("/v1/kb/publish")
    assert route.call_count == 1
    assert SERVICE_KEY not in caplog.text
    assert SERVICE_KEY not in json.dumps(audit_rows(live_admin))


def test_service_key_is_not_in_any_response_body(live_admin, runtime):
    runtime.post(RELOAD).mock(return_value=httpx.Response(502, text=f"echo {SERVICE_KEY}"))
    r = live_admin.post("/v1/kb/publish")
    assert r.status_code == 502 and SERVICE_KEY not in r.text


# ------------------------------------------------------------------ GET /v1/kb/publishes
def test_history_is_newest_first_with_mode_actor_and_info(admin_client, freeze_clock):
    from resolvix_ops.clock import FrozenClock
    app = admin_client.app
    for hour in (6, 7, 8):
        app.state.clock = FrozenClock(datetime(2026, 11, 15, hour, 0, tzinfo=timezone.utc), "Asia/Kolkata")
        assert admin_client.post("/v1/kb/publish").status_code == 200
    r = admin_client.get("/v1/kb/publishes")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["at"] for i in items] == ["2026-11-15T08:00:00+00:00", "2026-11-15T07:00:00+00:00",
                                        "2026-11-15T06:00:00+00:00"]
    for i in items:
        assert set(i) == {"kb_version", "info", "mode", "actor", "at"}
        assert (i["mode"], i["actor"], i["kb_version"]) == ("mock", "admin@demo", i["info"]["kb_version"])
        KBVersionInfo.model_validate(i["info"])  # same-version republishes are all kept
    assert len(admin_client.get("/v1/kb/publishes?limit=2").json()["items"]) == 2
    assert admin_client.get("/v1/kb/publishes?limit=0").status_code == 422


def test_history_is_empty_initially_and_visible_to_staff_and_service(staff_client, service_client):
    for c in (staff_client, service_client):
        assert c.get("/v1/kb/publishes").json() == {"items": []}


def test_failed_publish_leaves_history_untouched(live_admin, runtime, fixture_json):
    runtime.post(RELOAD).mock(side_effect=httpx.ConnectError("refused"))
    live_admin.post("/v1/kb/publish")
    assert live_admin.get("/v1/kb/publishes").json() == {"items": []}
    runtime.post(RELOAD).mock(return_value=httpx.Response(200, json=fixture_json("kb_version_info")))
    live_admin.post("/v1/kb/publish")
    (item,) = live_admin.get("/v1/kb/publishes").json()["items"]
    assert item["mode"] == "live"
