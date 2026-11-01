"""Test configuration and fixtures."""
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resolvix_ops.app import create_app
from resolvix_ops.config import Settings
from resolvix_ops.orm import Base


@pytest.fixture
def test_settings(tmp_path):
    """Create test settings with temp database."""
    # Use pytest's tmp_path for automatic cleanup
    db_file = tmp_path / "test.db"
    temp_db = f"sqlite:///{db_file}"
    
    # Create temp config files
    departments_file = tmp_path / "departments.yaml"
    urgency_rules_file = tmp_path / "urgency_rules.yaml"
    sms_templates_file = tmp_path / "sms_templates.yaml"
    
    # Copy from contracts
    import shutil
    contracts_base = Path(__file__).parent.parent.parent.parent / "contracts" / "config"
    shutil.copy(contracts_base / "departments.yaml", departments_file)
    shutil.copy(contracts_base / "urgency_rules.yaml", urgency_rules_file)
    shutil.copy(contracts_base / "sms_templates.yaml", sms_templates_file)
    
    settings = Settings(
        _env_file=None,  # never pick up the dev .env (Twilio credentials, NOTIFY_MODE)
        database_url=temp_db,
        service_key="test-service-key-12345",
        session_secret="test-session-secret-needs-32-chars-minimum-length-here",
        seed_password="TestPassword123!",
        departments_file=str(departments_file),
        urgency_rules_file=str(urgency_rules_file),
        sms_templates_file=str(sms_templates_file),
        seed_users_on_startup=False,  # Manual seeding in tests
        notify_mode="mock",
        sms_poll_enabled=False,  # tests never start status-poll timers
    )
    return settings


@pytest.fixture
def client(test_settings):
    """Create test client with temporary database."""
    app = create_app(test_settings)
    
    # Use TestClient which automatically cleans up
    with TestClient(app) as test_client:
        yield test_client
    
    # Explicitly dispose engine to release file locks on Windows
    app.state.engine.dispose()


from _m2 import auth, client_n, fail_next_commit, fixture_json, live_server, notifier, sms_client  # noqa: E402,F401  (M2/M3 fixtures)

from helpers.fixtures import (  # noqa: E402,F401  (shared fixtures for gaps/KB/seed/simulator agents)
    admin_client, anon_client, app_factory, freeze_clock, ops_app, service_client, staff_client)


@pytest.fixture
def db_session(test_settings):
    """Create database session for direct DB access in tests."""
    engine = create_engine(test_settings.database_url)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()
    engine.dispose()
