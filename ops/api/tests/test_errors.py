"""Test error handling."""
from fastapi.testclient import TestClient
from resolvix_ops.app import create_app


def test_validation_error_returns_422_envelope(client, test_settings):
    """Invalid request body should return 422 with ErrorEnvelope."""
    response = client.post(
        "/v1/auth/login",
        json={"invalid": "data"}  # Missing required fields
    )
    assert response.status_code == 422
    
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"
    assert data["error"]["retryable"] is False


def test_not_found_returns_404_envelope(client):
    """Non-existent endpoint should return 404 with ErrorEnvelope."""
    response = client.get("/v1/nonexistent")
    assert response.status_code == 404
    
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "not_found"


def test_unhandled_exception_returns_500_envelope(test_settings):
    """Unhandled exception should return 500 with ErrorEnvelope and no traceback."""
    from fastapi import FastAPI, APIRouter
    from resolvix_ops.errors import general_exception_handler
    
    # Create a minimal app with a route that raises
    app = FastAPI()
    app.add_exception_handler(Exception, general_exception_handler)
    
    router = APIRouter()
    
    @router.get("/force-error")
    def force_error():
        raise ValueError("Test exception")
    
    app.include_router(router)
    
    # Use raise_server_exceptions=False to see the 500 response
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/force-error")
        
        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "internal"
        assert data["error"]["retryable"] is False
        
        # Ensure no traceback in response
        response_text = response.text
        assert "Traceback" not in response_text
        assert "ValueError" not in response_text



def test_method_not_allowed_returns_405_envelope(client):
    """Wrong HTTP method should return 405 with not_found envelope (closest match)."""
    # POST to a GET-only endpoint
    response = client.post("/healthz")
    assert response.status_code == 405
    
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "not_found"  # 405 maps to not_found
