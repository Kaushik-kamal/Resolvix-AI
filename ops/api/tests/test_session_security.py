"""Sessions: logout revokes server side, role/department come from the database, cookie flags, login guards."""
from fastapi.testclient import TestClient

from helpers.fixtures import _login
from resolvix_ops.orm import User


def replay(app, cookie: str) -> TestClient:
    c = TestClient(app)
    c.cookies.set("resolvix_session", cookie)
    return c


def test_logout_revokes_a_copied_cookie(ops_app, staff_client):
    cookie = staff_client.cookies.get("resolvix_session")
    thief = replay(ops_app, cookie)
    assert thief.get("/v1/auth/me").status_code == 200
    assert staff_client.post("/v1/auth/logout").status_code == 200
    assert thief.get("/v1/auth/me").status_code == 401
    assert thief.get("/v1/tickets").status_code == 401


def test_a_new_login_after_logout_works(ops_app, staff_client):
    staff_client.post("/v1/auth/logout")
    again = _login(ops_app, "exam@demo")
    assert again.get("/v1/auth/me").status_code == 200


def test_role_and_department_are_reread_from_the_database(ops_app, staff_client):
    assert staff_client.get("/v1/auth/me").json()["department"] == "exam_cell"
    with ops_app.state.session_factory() as db:
        db.query(User).filter(User.email == "exam@demo").update({"department": "hostel"})
        db.commit()
    assert staff_client.get("/v1/auth/me").json()["department"] == "hostel"  # no 12 h stale copy in the cookie
    with ops_app.state.session_factory() as db:
        db.query(User).filter(User.email == "exam@demo").update({"role": "admin"})
        db.commit()
    assert staff_client.get("/v1/auth/me").json()["role"] == "admin"


def test_deleted_user_loses_access_immediately(ops_app, staff_client):
    with ops_app.state.session_factory() as db:
        db.query(User).filter(User.email == "exam@demo").delete()
        db.commit()
    assert staff_client.get("/v1/tickets").status_code == 401


def test_cookie_without_session_version_is_rejected(ops_app):
    import itsdangerous
    from resolvix_ops.auth import create_session_cookie
    s = ops_app.state.settings
    old = itsdangerous.URLSafeTimedSerializer(s.session_secret).dumps(
        {"email": "admin@demo", "role": "admin", "department": None})  # pre-fix cookie format
    assert replay(ops_app, old).get("/v1/auth/me").status_code == 401
    good = create_session_cookie("admin@demo", "admin", None, s, 0)
    assert replay(ops_app, good).get("/v1/auth/me").status_code == 200


def test_cookie_flags(app_factory):
    app = app_factory(seed_users_on_startup=True, ops_public_url="http://localhost:8100")
    with TestClient(app) as c:
        r = c.post("/v1/auth/login", json={"email": "admin@demo", "password": app.state.settings.seed_password})
        header = r.headers["set-cookie"].lower()
        assert "httponly" in header and "samesite=lax" in header and "max-age=43200" in header
        assert "; secure" not in header
    https = app_factory(seed_users_on_startup=True, ops_public_url="https://ops.example.test")
    with TestClient(https, base_url="https://testserver") as c:
        r = c.post("/v1/auth/login", json={"email": "admin@demo", "password": https.state.settings.seed_password})
        assert "; secure" in r.headers["set-cookie"].lower()


def test_login_length_caps_are_422(client):
    r = client.post("/v1/auth/login", json={"email": "a" * 300, "password": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.post("/v1/auth/login", json={"email": "a@b", "password": "x" * 300})
    assert r.status_code == 422


def test_successful_logins_never_count_towards_the_limit(ops_app):
    pw = ops_app.state.settings.seed_password
    c = TestClient(ops_app)
    for _ in range(12):
        assert c.post("/v1/auth/login", json={"email": "admin@demo", "password": pw}).status_code == 200


def test_failed_attempts_per_account_are_rate_limited_but_other_accounts_are_not(ops_app):
    pw = ops_app.state.settings.seed_password
    c = TestClient(ops_app)
    for _ in range(10):
        assert c.post("/v1/auth/login", json={"email": "exam@demo", "password": "wrong"}).status_code == 401
    blocked = c.post("/v1/auth/login", json={"email": "exam@demo", "password": pw})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    assert "retry-after" in blocked.headers
    assert c.post("/v1/auth/login", json={"email": "hostel@demo", "password": pw}).status_code == 200


def test_unknown_email_and_wrong_password_look_the_same(client):
    a = client.post("/v1/auth/login", json={"email": "nobody@demo", "password": "x"})
    b = client.post("/v1/auth/login", json={"email": "admin@demo", "password": "x"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_docs_are_hidden_on_a_public_deployment(app_factory):
    local = app_factory()
    public = app_factory(ops_public_url="https://ops.example.test")
    assert TestClient(local).get("/docs").status_code == 200
    assert TestClient(public).get("/docs").status_code == 404
    assert TestClient(public).get("/openapi.json").status_code == 404
