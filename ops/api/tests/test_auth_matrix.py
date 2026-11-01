"""Every /v1/* route except POST /v1/auth/login must reject unauthenticated requests with a 401 envelope."""
import re

import pytest
from fastapi.routing import APIRoute

from resolvix_ops.app import create_app

# Login is public by design. The Twilio status callback has no service key or session either;
# it is protected by the X-Twilio-Signature check instead (see test_status_callback_is_public_but_signature_checked).
PUBLIC = {("POST", "/v1/auth/login"), ("POST", "/v1/notifications/sms/status")}


def v1_routes(app):
    routes = []
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/v1/"):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                routes.append((m, r.path))
    return sorted(routes)


@pytest.fixture
def routes(test_settings):
    app = create_app(test_settings)
    yield v1_routes(app)
    app.state.engine.dispose()


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "some-id", path)


def test_route_inventory_is_not_trivially_empty(routes):
    assert len(routes) >= 17
    assert ("GET", "/v1/stream") in routes and ("POST", "/v1/auth/login") in routes


def test_every_v1_route_requires_credentials(client, routes):
    protected = [(m, p) for m, p in routes if (m, p) not in PUBLIC]
    assert protected
    failures = []
    for method, path in protected:
        r = client.request(method, concrete(path), json={} if method in {"POST", "PATCH", "PUT"} else None)
        if r.status_code != 401 or r.json().get("error", {}).get("code") != "unauthorized":
            failures.append((method, path, r.status_code))
    assert not failures, failures


def test_login_is_public(client):
    r = client.post("/v1/auth/login", json={"email": "nobody@demo", "password": "x"})
    assert r.status_code == 401  # reaches the handler (bad credentials), not the auth gate
    assert r.json()["error"]["message"] == "Invalid credentials"


def test_wrong_service_key_and_bad_cookie_are_rejected(client):
    assert client.get("/v1/tickets", headers={"X-Service-Key": "wrong"}).status_code == 401
    assert client.get("/v1/tickets", cookies={"resolvix_session": "garbage"}).status_code == 401


def test_service_key_is_accepted_on_every_get(client, auth, routes):
    for method, path in routes:
        if method == "GET" and "{" not in path and path != "/v1/stream" and path != "/v1/auth/me":
            assert client.get(path, headers=auth).status_code == 200, path


def test_method_not_allowed_uses_error_envelope(client, auth):
    r = client.delete("/v1/tickets", headers=auth)
    assert r.status_code == 405 and r.json()["error"]["code"] == "not_found"  # contract has no method_not_allowed


def test_status_callback_is_public_but_signature_checked(client, auth):
    # no credentials needed to reach it, but without a valid signature it answers 403 (not 401, not 200)
    r = client.post("/v1/notifications/sms/status", data={"MessageSid": "SM1", "MessageStatus": "delivered"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized"
    # a service key does not replace the signature
    r = client.post("/v1/notifications/sms/status", data={"MessageSid": "SM1", "MessageStatus": "delivered"},
                    headers=auth)
    assert r.status_code == 403


def test_admin_only_kb_routes_refuse_staff_and_service(staff_client, service_client, admin_client):
    for who in (staff_client, service_client):
        r = who.post("/v1/kb/entries/FEE-001/status", json={"status": "approved"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized"
        r = who.post("/v1/kb/publish")
        assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized"
    # admin passes the gate (unknown entry -> 404, publish in mock mode -> 200)
    assert admin_client.post("/v1/kb/entries/FEE-001/status", json={"status": "approved"}).status_code == 404
    assert admin_client.post("/v1/kb/publish").status_code == 200


def test_gap_and_kb_reads_work_for_every_authenticated_principal(staff_client, service_client, admin_client):
    for who in (staff_client, service_client, admin_client):
        for path in ("/v1/gaps/clusters", "/v1/kb/entries", "/v1/kb/export", "/v1/kb/publishes"):
            assert who.get(path).status_code == 200, path
