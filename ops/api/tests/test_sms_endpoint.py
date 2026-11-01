"""POST /v1/notifications/sms in mock mode."""
import logging

from resolvix_contracts import SmsRequest, SmsResult

from _m2 import make_ticket_body, sms_rows

URL = "/v1/notifications/sms"
NUMBER = "+919000000004"


def post(client, auth, body):
    return client.post(URL, json=body, headers=auth)


def test_fixture_request_accepted_in_mock_mode(sms_client, auth, fixture_json):
    SmsRequest.model_validate(fixture_json("sms_request"))
    r = post(sms_client, auth, fixture_json("sms_request"))
    assert r.status_code == 202
    result = SmsResult.model_validate(r.json())
    assert result.mode == "mock" and result.status == "sent" and result.reason is None
    assert result.message_id.startswith("mock-")
    assert set(r.json()) == set(fixture_json("sms_result"))  # same shape as the contract example
    assert len(sms_client.app.state.sms.provider.sent) == 1
    assert NUMBER not in r.text  # response carries no number at all


def test_stored_record_is_labelled_mock_and_holds_full_number(sms_client, auth, fixture_json):
    post(sms_client, auth, fixture_json("sms_request"))
    (row,) = sms_rows(sms_client)
    assert row.mode == "mock" and row.status == "sent" and row.provider_id.startswith("mock-")
    assert row.to_number == NUMBER and row.flagged is False
    assert row.vars_json == {"ticket_id": "HS-1044", "dept": "Hostel Office"}


def test_sent_text_is_the_rendered_template(sms_client, auth, fixture_json):
    post(sms_client, auth, fixture_json("sms_request"))
    to, body, callback = sms_client.app.state.sms.provider.sent[0]
    assert to == NUMBER and callback is None
    assert body == "College Helpline: your request HS-1044 has been registered with Hostel Office. You will be contacted soon."


def test_duplicate_key_returns_original_with_200_and_sends_nothing(sms_client, auth, fixture_json):
    first = post(sms_client, auth, fixture_json("sms_request"))
    second = post(sms_client, auth, fixture_json("sms_request"))
    assert first.status_code == 202 and second.status_code == 200
    assert second.json() == first.json()
    assert len(sms_client.app.state.sms.provider.sent) == 1
    assert len(sms_rows(sms_client)) == 1


def test_duplicate_key_with_different_body_still_returns_original(sms_client, auth, fixture_json):
    first = post(sms_client, auth, fixture_json("sms_request"))
    other = dict(fixture_json("sms_request"), to_number="+919000000099")
    again = post(sms_client, auth, other)
    assert again.status_code == 200 and again.json() == first.json()
    assert len(sms_client.app.state.sms.provider.sent) == 1


def test_suppressed_request_is_stored_and_its_duplicate_returns_the_same_result(sms_client, auth, fixture_json):
    body = dict(fixture_json("sms_request"), idempotency_key="pii-1", template_id="answer_copy",
                consent="offer_accepted",
                vars={"summary": "Your marks are 82", "source": "Results", "url": "https://college.example/r"})
    first = post(sms_client, auth, body)
    assert first.status_code == 202
    assert first.json()["status"] == "suppressed" and first.json()["reason"] == "pii_in_vars"
    assert first.json()["mode"] == "mock"
    second = post(sms_client, auth, body)
    assert second.status_code == 200 and second.json() == first.json()
    assert sms_client.app.state.sms.provider.sent == []
    (row,) = sms_rows(sms_client)
    assert row.status == "suppressed" and row.vars_json == {}  # PII is not persisted


def test_each_suppression_reason_through_the_endpoint(sms_client, auth, fixture_json):
    base = fixture_json("sms_request")
    cases = {
        "consent_not_allowed": dict(base, idempotency_key="c1", consent="staff"),
        "invalid_e164": dict(base, idempotency_key="c2", to_number="12345"),
        "staff_number_not_allowed": dict(base, idempotency_key="c3", template_id="staff_alert", consent="staff",
                                         vars={"ticket_id": "EX-1", "summary": "help"}),
        "missing_vars": dict(base, idempotency_key="c4", vars={"ticket_id": "HS-1"}),
        "url_not_allowed": dict(base, idempotency_key="c5", template_id="answer_copy", consent="caller_requested",
                                vars={"summary": "s", "source": "x", "url": "https://evil.example/"}),
    }
    for reason, body in cases.items():
        r = post(sms_client, auth, body)
        assert (r.status_code, r.json()["status"], r.json()["reason"]) == (202, "suppressed", reason), reason
    assert sms_client.app.state.sms.provider.sent == []


def test_staff_alert_to_department_number_is_sent(sms_client, auth, fixture_json):
    body = dict(fixture_json("sms_request"), idempotency_key="sa", template_id="staff_alert", consent="staff",
                to_number="+910000000101", vars={"ticket_id": "EX-1001", "summary": "Exam room not found"})
    r = post(sms_client, auth, body)
    assert r.status_code == 202 and r.json()["status"] == "sent"
    assert sms_client.app.state.sms.provider.sent[0][1].startswith("RESOLVIX ALERT: EX-1001")


def test_unknown_template_is_rejected_by_contract_validation(sms_client, auth, fixture_json):
    r = post(sms_client, auth, dict(fixture_json("sms_request"), template_id="made_up"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert sms_rows(sms_client) == []


def test_requires_credentials(sms_client, fixture_json):
    r = sms_client.post(URL, json=fixture_json("sms_request"))
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert sms_client.app.state.sms.provider.sent == []


def test_number_never_appears_in_logs(sms_client, auth, fixture_json, caplog):
    caplog.set_level(logging.DEBUG)
    post(sms_client, auth, fixture_json("sms_request"))
    post(sms_client, auth, dict(fixture_json("sms_request"), idempotency_key="x", to_number="bad"))
    text = "\n".join(f"{r.name} {r.getMessage()}" for r in caplog.records)
    assert "9000000004" not in text and "Hostel Office" not in text


def test_ticket_events_carry_mode_and_masked_number(sms_client, auth, fixture_json):
    tid = sms_client.post("/v1/tickets", json=make_ticket_body(fixture_json, "k", callback_requested=False),
                          headers=auth).json()["ticket_id"]
    sent = dict(fixture_json("sms_request"), ticket_id=tid, idempotency_key="e1", to_number=NUMBER)
    bad = dict(sent, idempotency_key="e2", consent="staff")
    post(sms_client, auth, sent)
    post(sms_client, auth, bad)
    events = sms_client.get(f"/v1/tickets/{tid}/events", headers=auth).json()["items"]
    assert [e["kind"] for e in events] == ["sms_sent", "sms_suppressed"]
    assert events[0]["payload"]["mode"] == "mock" and events[0]["payload"]["template_id"] == "ticket_created"
    assert events[0]["payload"]["to"] == "+91•••••0004" and events[0]["payload"]["status"] == "sent"
    assert events[1]["payload"]["reason"] == "consent_not_allowed"
    assert NUMBER not in str(events)


def test_sms_for_unknown_ticket_is_recorded_without_event(sms_client, auth, fixture_json):
    r = post(sms_client, auth, dict(fixture_json("sms_request"), ticket_id="ZZ-0000"))
    assert r.status_code == 202 and r.json()["status"] == "sent"


def test_healthz_reports_mock(client):
    assert client.get("/healthz").json()["notify_mode"] == "mock"
