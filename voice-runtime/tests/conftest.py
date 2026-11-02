from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from resolvix_runtime.app import create_app
from resolvix_runtime.brain_loader import reset_brain
from resolvix_runtime.config import RuntimeSettings
from resolvix_runtime.sessions import get_session_registry


@pytest.fixture(autouse=True)
def reset_state():
    """Ensure clean singleton and session state between tests."""
    reset_brain()
    registry = get_session_registry()
    registry._sessions.clear()
    yield
    reset_brain()
    registry._sessions.clear()


@pytest.fixture
def test_settings() -> RuntimeSettings:
    return RuntimeSettings(
        port=8000,
        public_base_url="http://localhost:8000",
        shim_api_key="test-shim-key",
        service_key="test-service-key",
        ops_api_url="http://localhost:8100",
        brain_impl="mock",
        telephony_mode="mock",
        telephony_transfer_success=True,
    )


@pytest.fixture
def app(test_settings: RuntimeSettings):
    return create_app(test_settings)


@pytest.fixture
def client(app):
    return TestClient(app)
