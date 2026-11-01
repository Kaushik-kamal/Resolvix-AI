"""The shared fixtures for the parallel agents behave as documented."""
from datetime import datetime, timezone


def test_clients_and_roles(service_client, admin_client, staff_client, anon_client):
    assert service_client.get("/v1/tickets").status_code == 200
    assert anon_client.get("/v1/tickets").status_code == 401
    assert admin_client.get("/v1/auth/me").json()["role"] == "admin"
    me = staff_client.get("/v1/auth/me").json()
    assert (me["role"], me["department"]) == ("staff", "exam_cell")


def test_clock_freezes_ist_date_across_utc_midnight(ops_app, freeze_clock):
    freeze_clock(datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc))  # 01:30 IST on the 31st
    assert ops_app.state.clock.today_ist().isoformat() == "2026-10-31"
    freeze_clock(datetime(2026, 10, 31, 18, 29, tzinfo=timezone.utc))  # 23:59 IST still the 31st
    assert ops_app.state.clock.today_ist().isoformat() == "2026-10-31"


def test_default_clock_is_real(ops_app):
    assert ops_app.state.clock.today_ist().year >= 2026


def test_app_factory_overrides(app_factory):
    app = app_factory(notify_async=True)
    assert app.state.settings.sms_async is True
