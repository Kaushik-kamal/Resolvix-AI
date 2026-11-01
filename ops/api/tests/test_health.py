"""Test health endpoint."""
from resolvix_contracts import CONTRACT_VERSION


def test_health_check_public_access(client):
    """Health endpoint should be publicly accessible."""
    response = client.get("/healthz")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "ok"
    assert data["contract_version"] == CONTRACT_VERSION
    assert "notify_mode" in data
    assert "runtime_mode" in data


def test_health_check_no_auth_required(client):
    """Health endpoint should work without authentication."""
    # No headers
    response = client.get("/healthz")
    assert response.status_code == 200
