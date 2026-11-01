"""Test configuration routes."""
def test_departments_requires_auth(client):
    """GET /v1/departments requires authentication."""
    response = client.get("/v1/departments")
    assert response.status_code == 401


def test_departments_with_service_key(client, test_settings):
    """GET /v1/departments with service key returns config."""
    response = client.get(
        "/v1/departments",
        headers={"X-Service-Key": test_settings.service_key}
    )
    assert response.status_code == 200
    
    data = response.json()
    assert "timezone" in data
    assert "departments" in data
    assert data["timezone"] == "Asia/Kolkata"
    assert isinstance(data["departments"], list)
    assert len(data["departments"]) > 0


def test_urgency_rules_with_service_key(client, test_settings):
    """GET /v1/urgency-rules returns rules."""
    response = client.get(
        "/v1/urgency-rules",
        headers={"X-Service-Key": test_settings.service_key}
    )
    assert response.status_code == 200
    
    data = response.json()
    assert "rules" in data
    assert isinstance(data["rules"], list)
    # Should have at least the rules from urgency_rules.yaml
    assert len(data["rules"]) >= 7
