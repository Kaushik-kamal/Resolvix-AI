"""Test authentication."""
import pytest
from resolvix_ops.auth import hash_password
from resolvix_ops.orm import User


@pytest.fixture
def seeded_user(db_session, test_settings):
    """Create a test user."""
    user = User(
        email="test@demo",
        password_hash=hash_password(test_settings.seed_password),
        role="admin",
        department=None
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_no_credentials_returns_401(client):
    """Request without credentials should return 401 with ErrorEnvelope."""
    response = client.get("/v1/departments")
    assert response.status_code == 401
    
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "unauthorized"


def test_wrong_service_key_returns_401(client):
    """Wrong service key should return 401."""
    response = client.get(
        "/v1/departments",
        headers={"X-Service-Key": "wrong-key"}
    )
    assert response.status_code == 401


def test_correct_service_key_grants_access(client, test_settings):
    """Correct service key should grant access."""
    response = client.get(
        "/v1/departments",
        headers={"X-Service-Key": test_settings.service_key}
    )
    assert response.status_code == 200


def test_login_with_valid_credentials(client, seeded_user, test_settings):
    """Login with valid credentials should set cookie and return success."""
    response = client.post(
        "/v1/auth/login",
        json={
            "email": "test@demo",
            "password": test_settings.seed_password
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["email"] == "test@demo"
    
    # Check cookie is set
    assert "resolvix_session" in response.cookies


def test_login_with_wrong_password(client, seeded_user):
    """Login with wrong password should return 401."""
    response = client.post(
        "/v1/auth/login",
        json={
            "email": "test@demo",
            "password": "WrongPassword!"
        }
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "unauthorized"


def test_authenticated_request_with_cookie(client, seeded_user, test_settings):
    """Request with valid session cookie should work."""
    # Login first
    login_response = client.post(
        "/v1/auth/login",
        json={
            "email": "test@demo",
            "password": test_settings.seed_password
        }
    )
    assert login_response.status_code == 200
    
    # Use the cookie for next request
    response = client.get("/v1/departments")
    assert response.status_code == 200


def test_me_endpoint(client, seeded_user, test_settings):
    """GET /v1/auth/me should return user info."""
    # Login first
    client.post(
        "/v1/auth/login",
        json={
            "email": "test@demo",
            "password": test_settings.seed_password
        }
    )
    
    response = client.get("/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@demo"
    assert data["role"] == "admin"


def test_logout(client, seeded_user, test_settings):
    """POST /v1/auth/logout should clear cookie."""
    # Login first
    client.post(
        "/v1/auth/login",
        json={
            "email": "test@demo",
            "password": test_settings.seed_password
        }
    )
    
    response = client.post("/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["success"] is True
