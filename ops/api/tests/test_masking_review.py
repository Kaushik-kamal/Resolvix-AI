"""Numbers never leave in full: event payloads, access log, department numbers for staff, list reveal."""
import logging

from _m2 import make_ticket_body
from resolvix_ops.logfilter import PhoneMaskFilter, mask_numbers_in_text


def test_ticket_event_payload_numbers_are_masked(service_client, staff_client, fixture_json):
    tid = service_client.post("/v1/tickets", json=make_ticket_body(fixture_json, "k", department="exam_cell")).json()["ticket_id"]
    ev = {"kind": "transfer_failed",
          "payload": {"to_number": "+910000000101", "reason": "no_answer_20s", "caller": "caller +919876540002 called"},
          "actor": "system", "at": "2026-10-23T10:15:00+05:30"}
    assert service_client.post(f"/v1/tickets/{tid}/events", json=ev).status_code == 201
    for who in (service_client, staff_client):
        items = who.get(f"/v1/tickets/{tid}/events").json()["items"]
        text = str(items)
        assert "910000000101" not in text and "919876540002" not in text
        assert items[-1]["payload"]["to_number"] == "+91•••••0101"
        assert items[-1]["payload"]["reason"] == "no_answer_20s"


def test_access_log_masks_phone_numbers():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:1", "GET", "/v1/tickets?caller_number=%2B919876540002&status=open", "1.1", 200),
                            None)
    PhoneMaskFilter().filter(rec)
    out = rec.getMessage()
    assert "9876540002" not in out and "•••••0002" in out
    assert "status=open" in out and "/v1/tickets" in out
    assert mask_numbers_in_text("tickets 12345 and +919876540002") == "tickets 12345 and +91•••••0002"


def test_access_log_filter_is_installed_on_the_app(ops_app):
    assert any(isinstance(f, PhoneMaskFilter) for f in logging.getLogger("uvicorn.access").filters)


def test_departments_numbers_masked_for_staff_but_not_admin_or_service(staff_client, admin_client, service_client):
    def numbers(client):
        d = client.get("/v1/departments").json()
        out = [n for dep in d["departments"] for n in dep["sms_alert_numbers"] + dep["transfer_numbers"]]
        return out + d["emergency"].get("sms_alert_numbers", []) + d["emergency"].get("transfer_numbers", [])

    assert numbers(staff_client) and all("•" in n for n in numbers(staff_client))
    for who in (admin_client, service_client):
        assert any(n.startswith("+910000000101") for n in numbers(who))
    assert staff_client.get("/v1/departments").json()["emergency"]["public_numbers"]


def test_reveal_is_rejected_on_lists_and_allowed_on_details(service_client, staff_client, fixture_json):
    tid = service_client.post("/v1/tickets", json=make_ticket_body(fixture_json, "k", department="exam_cell")).json()["ticket_id"]
    assert staff_client.get("/v1/tickets?reveal=true").status_code == 422
    assert staff_client.get("/v1/calls?reveal=true").status_code == 422
    r = staff_client.get(f"/v1/tickets/{tid}?reveal=true")
    assert r.status_code == 200 and r.json()["caller_number"].startswith("+9190")


def test_500_log_has_no_exception_message(test_settings, caplog):
    from fastapi.testclient import TestClient
    from resolvix_ops.app import create_app
    app = create_app(test_settings)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret " + "+9198" + "76540002" + " in message")  # built at runtime: the source line holds no number

    caplog.set_level(logging.ERROR)
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/boom").status_code == 500
    app.state.engine.dispose()
    assert "RuntimeError" in caplog.text and "919876540002" not in caplog.text
