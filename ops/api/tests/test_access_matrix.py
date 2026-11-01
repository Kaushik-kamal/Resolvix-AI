"""Who may call what: every /v1 route x {no credentials, staff, admin, service key}.

A denied principal gets 401 (no credentials) or 403 (wrong role). An allowed principal gets anything else
(200/201/404/422 depending on the dummy body): the point is that the auth gate lets it through.
"""
import pytest
from fastapi.routing import APIRoute

ALL = {"staff", "admin", "service"}
SYSTEM = {"admin", "service"}      # endpoints the voice runtime calls (admin sessions may too)
USERS = {"staff", "admin"}         # session only
ADMIN = {"admin"}

# (method, path) -> principals that are ALLOWED
MATRIX = {
    ("GET", "/healthz"): None,                                  # public, outside /v1
    ("POST", "/v1/auth/login"): None,                           # public by design
    ("POST", "/v1/notifications/sms/status"): None,             # public, X-Twilio-Signature checked
    ("GET", "/v1/auth/me"): USERS,
    ("POST", "/v1/auth/logout"): ALL,
    ("GET", "/v1/departments"): ALL,
    ("GET", "/v1/urgency-rules"): ALL,
    ("GET", "/v1/stream"): ALL,
    ("GET", "/v1/calls"): ALL,
    ("GET", "/v1/calls/{call_id}"): ALL,
    ("POST", "/v1/calls"): SYSTEM,
    ("POST", "/v1/calls/{call_id}/turns"): SYSTEM,
    ("POST", "/v1/calls/{call_id}/end"): SYSTEM,
    ("GET", "/v1/tickets"): ALL,
    ("GET", "/v1/tickets/{ticket_id}"): ALL,
    ("PATCH", "/v1/tickets/{ticket_id}"): ALL,
    ("POST", "/v1/tickets"): SYSTEM,
    ("GET", "/v1/tickets/{ticket_id}/events"): ALL,
    ("POST", "/v1/tickets/{ticket_id}/events"): SYSTEM,
    ("POST", "/v1/notifications/sms"): SYSTEM,
    ("POST", "/v1/gaps"): SYSTEM,
    ("GET", "/v1/gaps/clusters"): ALL,
    ("PATCH", "/v1/gaps/clusters/{cluster_id}"): ALL,
    ("GET", "/v1/kb/entries"): ALL,
    ("POST", "/v1/kb/entries"): USERS,                          # drafts only; staff cannot overwrite approved
    ("POST", "/v1/kb/entries/{id}/status"): ADMIN,
    ("POST", "/v1/kb/import"): ADMIN,
    ("GET", "/v1/kb/export"): ALL,
    ("POST", "/v1/kb/publish"): ADMIN,
    ("GET", "/v1/kb/publishes"): ALL,
}
PRINCIPALS = ["anon", "staff", "admin", "service"]


def concrete(path: str) -> str:
    return path.replace("{call_id}", "c1").replace("{ticket_id}", "XX-0001").replace(
        "{cluster_id}", "gc-1").replace("{id}", "FEE-001")


def test_matrix_covers_every_application_route(ops_app):
    actual = set()
    for r in ops_app.routes:
        if isinstance(r, APIRoute) and (r.path.startswith("/v1/") or r.path == "/healthz"):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                actual.add((m, r.path))
    assert actual == set(MATRIX), (actual ^ set(MATRIX))


def test_access(anon_client, staff_client, admin_client, service_client):
    """One app, every route x principal (a parametrized version logged in twice per case and took minutes)."""
    clients = {"anon": anon_client, "staff": staff_client, "admin": admin_client, "service": service_client}
    failures = []
    for route, allowed in sorted(MATRIX.items(), key=lambda kv: kv[0][1] == "/v1/auth/logout"):  # logout revokes the session: last
        method, path = route
        if allowed is None:
            continue
        for principal in PRINCIPALS:
            if path == "/v1/stream":  # an allowed stream never ends: only the gate for anonymous is checked
                if principal == "anon" and clients[principal].get(path).status_code != 401:
                    failures.append((route, principal, "stream not gated"))
                continue
            r = clients[principal].request(method, concrete(path), json={} if method in {"POST", "PATCH"} else None)
            code = r.status_code
            if principal in allowed:
                ok = code not in (401, 403)
            elif principal == "anon" or route == ("GET", "/v1/auth/me"):  # /me wants a user session
                ok = code == 401 and r.json()["error"]["code"] == "unauthorized"
            else:
                ok = code == 403 and r.json()["error"]["code"] == "unauthorized"
            if not ok:
                failures.append((route, principal, code))
    assert not failures, failures


def test_public_routes(anon_client):
    assert anon_client.get("/healthz").status_code == 200
    assert anon_client.post("/v1/auth/login", json={"email": "nobody@demo", "password": "x"}).status_code == 401
    r = anon_client.post("/v1/notifications/sms/status", data={"MessageSid": "SM1", "MessageStatus": "delivered"})
    assert r.status_code == 403  # no valid signature
