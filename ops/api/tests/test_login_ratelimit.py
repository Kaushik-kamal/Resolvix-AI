"""Login is limited to 10 attempts per minute per client IP (error code rate_limited)."""
from resolvix_ops.ratelimit import SlidingWindowLimiter


def test_limiter_window_and_keys():
    now = [0.0]
    lim = SlidingWindowLimiter(3, 60, clock=lambda: now[0])
    assert [lim.allow("a") for _ in range(4)] == [True, True, True, False]
    assert lim.allow("b") is True  # per key
    assert 1 <= lim.retry_after("a") <= 61
    now[0] = 61.0
    assert lim.allow("a") is True  # window slid


def test_limiter_zero_disables():
    lim = SlidingWindowLimiter(0)
    assert all(lim.allow("a") for _ in range(100))


def test_eleventh_login_attempt_in_a_minute_is_429(client):
    bad = {"email": "nobody@demo", "password": "x"}
    codes = [client.post("/v1/auth/login", json=bad).status_code for _ in range(10)]
    assert codes == [401] * 10
    r = client.post("/v1/auth/login", json=bad)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited" and r.json()["error"]["retryable"] is True
    assert int(r.headers["retry-after"]) >= 1


def test_limit_is_configurable_and_does_not_touch_other_routes(app_factory):
    from fastapi.testclient import TestClient
    app = app_factory(login_rate_limit_per_min=2)
    with TestClient(app) as c:
        for _ in range(2):
            c.post("/v1/auth/login", json={"email": "a", "password": "b"})
        assert c.post("/v1/auth/login", json={"email": "a", "password": "b"}).status_code == 429
        assert c.get("/healthz").status_code == 200
