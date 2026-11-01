"""Twilio mode with the HTTP layer mocked by respx. Nothing here can reach the real network:
respx is run with assert_all_mocked, so any request that is not explicitly routed raises."""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from _m2 import make_ticket_body, sms_rows
from resolvix_ops.app import create_app

SID, TOKEN, FROM = "ACtest0000000000", "test-auth-token", "+15005550006"
PUBLIC = "https://ops.example.test"
MESSAGES = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
CALLBACK_URL = f"{PUBLIC}/v1/notifications/sms/status"
NUMBER = "+919000000004"


@pytest.fixture
def twilio_settings(test_settings):
    return test_settings.model_copy(update=dict(
        notify_mode="twilio", twilio_account_sid=SID, twilio_auth_token=TOKEN, twilio_from_number=FROM,
        ops_public_url=PUBLIC))


@pytest.fixture
def tw(twilio_settings):
    app = create_app(twilio_settings)
    with TestClient(app) as c:
        yield c
    app.state.engine.dispose()


@pytest.fixture
def http():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


def ok(sid="SM0001", status="queued"):
    return httpx.Response(201, json={"sid": sid, "status": status})


def sign(params: dict) -> dict:
    return {"X-Twilio-Signature": RequestValidator(TOKEN).compute_signature(CALLBACK_URL, params)}


def send(tw, auth, fixture_json, **kw):
    return tw.post("/v1/notifications/sms", json=dict(fixture_json("sms_request"), **kw), headers=auth)


# ------------------------------------------------------------------ sending
def test_success_stores_provider_id_and_reports_live(tw, http, auth, fixture_json):
    route = http.post(MESSAGES).mock(return_value=ok("SM123"))
    r = send(tw, auth, fixture_json)
    assert r.status_code == 202 and r.json()["status"] == "sent" and r.json()["mode"] == "live"
    assert r.json()["message_id"].startswith("msg-") and NUMBER not in r.text
    (row,) = sms_rows(tw)
    assert (row.provider_id, row.mode, row.status, row.flagged, row.to_number) == ("SM123", "live", "sent", False, NUMBER)
    assert route.call_count == 1
    sent = route.calls[0].request
    form = dict(pair.split("=", 1) for pair in sent.content.decode().split("&"))
    assert form["To"] == "%2B919000000004" and form["From"] == "%2B15005550006"
    assert form["StatusCallback"].startswith("https%3A%2F%2Fops.example.test%2Fv1%2Fnotifications%2Fsms%2Fstatus")
    assert sent.headers["authorization"].startswith("Basic ")
    assert tw.get("/healthz").json()["notify_mode"] == "live"


def test_failure_then_success_on_retry(tw, http, auth, fixture_json):
    route = http.post(MESSAGES).mock(side_effect=[httpx.Response(500), ok("SM9")])
    r = send(tw, auth, fixture_json)
    assert r.json()["status"] == "sent" and route.call_count == 2
    assert sms_rows(tw)[0].provider_id == "SM9"


def test_failure_twice_is_failed_and_flagged_with_ticket_event(tw, http, auth, fixture_json):
    tid = tw.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
    route = http.post(MESSAGES).mock(return_value=httpx.Response(503))
    r = send(tw, auth, fixture_json, ticket_id=tid)
    assert r.status_code == 202
    assert r.json()["status"] == "failed" and r.json()["reason"] == "provider_http_503"
    assert route.call_count == 2  # one attempt + exactly one retry
    (row,) = sms_rows(tw)
    assert row.status == "failed" and row.flagged is True
    events = tw.get(f"/v1/tickets/{tid}/events", headers=auth).json()["items"]
    assert [e["kind"] for e in events] == ["sms_failed"]
    assert events[0]["payload"]["mode"] == "live" and events[0]["payload"]["reason"] == "provider_http_503"
    assert NUMBER not in str(events)
    # the failed record is also the answer to a repeated key: no second attempt
    again = send(tw, auth, fixture_json)
    assert again.status_code == 200 and again.json()["status"] == "failed" and route.call_count == 2


def test_timeout_path(tw, http, auth, fixture_json):
    route = http.post(MESSAGES).mock(side_effect=httpx.ConnectTimeout("slow"))
    r = send(tw, auth, fixture_json)
    assert r.json()["status"] == "failed" and r.json()["reason"] == "provider_timeout"
    assert route.call_count == 2 and sms_rows(tw)[0].flagged is True


def test_connection_error_reason(tw, http, auth, fixture_json):
    http.post(MESSAGES).mock(side_effect=httpx.ConnectError("down"))
    assert send(tw, auth, fixture_json).json()["reason"] == "provider_unreachable"


def test_suppressed_request_never_reaches_twilio(tw, http, auth, fixture_json):
    route = http.post(MESSAGES).mock(return_value=ok())
    r = send(tw, auth, fixture_json, consent="staff")
    assert r.json()["status"] == "suppressed" and r.json()["mode"] == "live" and route.call_count == 0


def test_provider_timeout_setting_is_five_seconds(twilio_settings):
    assert twilio_settings.sms_send_timeout_s == 5.0


# ------------------------------------------------------------------ startup validation
@pytest.mark.parametrize("missing", ["twilio_account_sid", "twilio_auth_token", "twilio_from_number"])
def test_twilio_mode_fails_fast_when_credentials_missing(twilio_settings, missing):
    settings = twilio_settings.model_copy(update={missing: ""})
    with pytest.raises(RuntimeError) as exc:
        create_app(settings)
    message = str(exc.value)
    assert {"twilio_account_sid": "TWILIO_ACCOUNT_SID", "twilio_auth_token": "TWILIO_AUTH_TOKEN",
            "twilio_from_number": "TWILIO_FROM"}[missing] in message
    assert TOKEN not in message and SID not in message and FROM not in message  # names only, never values


def test_unknown_notify_mode_fails_fast(test_settings):
    with pytest.raises(RuntimeError):
        create_app(test_settings.model_copy(update={"notify_mode": "carrier-pigeon"}))


def test_live_is_an_alias_for_twilio(twilio_settings):
    app = create_app(twilio_settings.model_copy(update={"notify_mode": "live"}))
    assert app.state.sms.provider.mode == "live"
    app.state.engine.dispose()


def test_mock_mode_needs_no_credentials(test_settings):
    app = create_app(test_settings.model_copy(update={"twilio_auth_token": ""}))
    assert app.state.sms.provider.mode == "mock"
    app.state.engine.dispose()


# ------------------------------------------------------------------ status callback
def callback(tw, params, headers=None):
    return tw.post("/v1/notifications/sms/status", data=params, headers=headers or sign(params))


def test_callback_valid_signature_marks_delivered(tw, http, auth, fixture_json):
    http.post(MESSAGES).mock(return_value=ok("SM55"))
    send(tw, auth, fixture_json)
    r = callback(tw, {"MessageSid": "SM55", "MessageStatus": "delivered"})
    assert r.status_code == 200
    (row,) = sms_rows(tw)
    assert row.status == "delivered" and row.flagged is False
    assert send(tw, auth, fixture_json).json()["status"] == "delivered"  # duplicate shows current state


def test_callback_failed_flags_record_and_writes_ticket_event(tw, http, auth, fixture_json):
    tid = tw.post("/v1/tickets", json=make_ticket_body(fixture_json, "k"), headers=auth).json()["ticket_id"]
    http.post(MESSAGES).mock(return_value=ok("SM66"))
    send(tw, auth, fixture_json, ticket_id=tid)
    params = {"MessageSid": "SM66", "MessageStatus": "undelivered", "ErrorCode": "30003"}
    assert callback(tw, params).status_code == 200
    (row,) = sms_rows(tw)
    assert row.status == "failed" and row.flagged is True and row.reason == "provider_undelivered_30003"
    kinds = [e["kind"] for e in tw.get(f"/v1/tickets/{tid}/events", headers=auth).json()["items"]]
    assert kinds == ["sms_sent", "sms_failed"]


def test_callback_invalid_signature_rejected_and_nothing_updated(tw, http, auth, fixture_json):
    http.post(MESSAGES).mock(return_value=ok("SM77"))
    send(tw, auth, fixture_json)
    params = {"MessageSid": "SM77", "MessageStatus": "delivered"}
    for headers in ({"X-Twilio-Signature": "AAAA"}, {}, sign({"MessageSid": "SM77", "MessageStatus": "failed"})):
        r = tw.post("/v1/notifications/sms/status", data=params, headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized"
    assert sms_rows(tw)[0].status == "sent"


def test_callback_signature_for_wrong_url_rejected(tw, http, auth, fixture_json):
    params = {"MessageSid": "SM1", "MessageStatus": "delivered"}
    bad = {"X-Twilio-Signature": RequestValidator(TOKEN).compute_signature("https://evil.example/x", params)}
    assert callback(tw, params, headers=bad).status_code == 403


def test_callback_for_unknown_sid_or_intermediate_status_changes_nothing(tw, http, auth, fixture_json):
    http.post(MESSAGES).mock(return_value=ok("SM88"))
    send(tw, auth, fixture_json)
    assert callback(tw, {"MessageSid": "SM-unknown", "MessageStatus": "delivered"}).status_code == 200
    assert callback(tw, {"MessageSid": "SM88", "MessageStatus": "sending"}).status_code == 200
    assert sms_rows(tw)[0].status == "sent"


def test_final_status_is_not_overwritten(tw, http, auth, fixture_json):
    http.post(MESSAGES).mock(return_value=ok("SM89"))
    send(tw, auth, fixture_json)
    callback(tw, {"MessageSid": "SM89", "MessageStatus": "delivered"})
    callback(tw, {"MessageSid": "SM89", "MessageStatus": "failed"})
    assert sms_rows(tw)[0].status == "delivered"


# ------------------------------------------------------------------ status poll (no real timers)
class FakeTimer:
    created = []

    def __init__(self, delay, fn, args=()):
        self.delay, self.fn, self.args, self.daemon, self.started = delay, fn, args, False, False
        FakeTimer.created.append(self)

    def start(self):
        self.started = True


def test_poll_is_scheduled_once_when_callback_url_is_local(twilio_settings, http, auth, fixture_json, monkeypatch):
    monkeypatch.setattr("resolvix_ops.sms.service.threading.Timer", FakeTimer)
    FakeTimer.created = []
    settings = twilio_settings.model_copy(update=dict(ops_public_url="http://localhost:8100", sms_poll_enabled=True))
    app = create_app(settings)
    with TestClient(app) as tw:
        route = http.post(MESSAGES).mock(return_value=ok("SM90"))
        http.get(f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages/SM90.json").mock(
            return_value=httpx.Response(200, json={"status": "delivered", "error_code": None}))
        r = send(tw, auth, fixture_json)
        assert r.json()["status"] == "sent"
        assert "StatusCallback" not in route.calls[0].request.content.decode()  # Twilio cannot reach localhost
        (timer,) = FakeTimer.created
        assert timer.delay == 10.0 and timer.started and timer.daemon and timer.args == ("SM90",)
        send(tw, auth, fixture_json)  # duplicate: no second timer
        assert len(FakeTimer.created) == 1
        timer.fn(*timer.args)  # run the poll body by hand
        assert sms_rows(tw)[0].status == "delivered"
    app.state.engine.dispose()


def test_no_timers_when_polling_disabled_or_public_url(tw, http, auth, fixture_json, monkeypatch):
    monkeypatch.setattr("resolvix_ops.sms.service.threading.Timer", FakeTimer)
    FakeTimer.created = []
    http.post(MESSAGES).mock(return_value=ok("SM91"))
    send(tw, auth, fixture_json)  # public URL: Twilio calls back, no poll
    assert FakeTimer.created == [] and tw.app.state.sms.scheduled_polls == []


def test_mock_mode_never_schedules_polls(client, auth, fixture_json, monkeypatch):
    monkeypatch.setattr("resolvix_ops.sms.service.threading.Timer", FakeTimer)
    FakeTimer.created = []
    client.post("/v1/notifications/sms", json=fixture_json("sms_request"), headers=auth)
    assert FakeTimer.created == [] and client.app.state.sms.scheduled_polls == []
