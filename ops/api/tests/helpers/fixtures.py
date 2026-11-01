"""Shared fixtures for the gaps / KB / seed / simulator tests (orchestrator-owned: import, never edit).

    ops_app          running app (lifespan active) on a temp DB with the 4 seed users
    service_client   TestClient sending X-Service-Key (what the voice runtime uses)
    admin_client     TestClient logged in as admin@demo
    staff_client     TestClient logged in as exam@demo (staff, department exam_cell)
    anon_client      TestClient with no credentials
    freeze_clock     call freeze_clock(datetime(...utc...)) to freeze app.state.clock; IST date follows
    app_factory      make(**settings_overrides) -> app (not started; disposed at teardown)
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from resolvix_ops.app import create_app
from resolvix_ops.clock import FrozenClock

SERVICE_KEY = "test-service-key-12345"
ADMIN = "admin@demo"
STAFF = "exam@demo"


@pytest.fixture
def app_factory(test_settings):
    apps = []

    def make(**overrides):
        settings = test_settings.model_copy(update=overrides) if overrides else test_settings
        app = create_app(settings)
        apps.append(app)
        return app

    yield make
    for app in apps:
        app.state.engine.dispose()


@pytest.fixture
def ops_app(test_settings):
    app = create_app(test_settings.model_copy(update={"seed_users_on_startup": True}))
    with TestClient(app):  # runs the lifespan (SSE loop, SMS executor) for the whole test
        yield app
    app.state.engine.dispose()


@pytest.fixture
def service_client(ops_app):
    return TestClient(ops_app, headers={"X-Service-Key": SERVICE_KEY})


def _login(app, email: str) -> TestClient:
    client = TestClient(app)
    r = client.post("/v1/auth/login", json={"email": email, "password": app.state.settings.seed_password})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def admin_client(ops_app):
    return _login(ops_app, ADMIN)


@pytest.fixture
def staff_client(ops_app):
    return _login(ops_app, STAFF)


@pytest.fixture
def anon_client(ops_app):
    return TestClient(ops_app)


@pytest.fixture
def freeze_clock(ops_app):
    def freeze(now: datetime):
        ops_app.state.clock = FrozenClock(now, ops_app.state.settings.timezone)
        return ops_app.state.clock

    return freeze
