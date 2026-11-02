from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient


@respx.mock
def test_healthz_endpoint(client: TestClient):
    respx.get("http://localhost:8100/healthz").respond(200, json={"status": "ok"})

    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "brain" in data
    assert "ops_api" in data
    assert data["contract_version"] == "1.0.0"


def test_kb_reload_auth_failure(client: TestClient):
    resp = client.post(
        "/admin/kb/reload",
        headers={"X-Service-Key": "wrong-key"},
        json={"kind": "file", "location": "contracts/kb/sample_kb.jsonl"},
    )
    assert resp.status_code == 401
    err = resp.json()["error"]
    assert err["code"] == "unauthorized"


def test_kb_reload_success(client: TestClient):
    headers = {"X-Service-Key": "test-service-key"}
    resp = client.post(
        "/admin/kb/reload",
        headers=headers,
        json={"kind": "url", "location": "http://localhost:8100/v1/kb/export"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "kb_version" in data
    assert data["entry_count"] > 0


def test_kb_reload_compile_error_returns_422(client: TestClient):
    headers = {"X-Service-Key": "test-service-key"}
    resp = client.post(
        "/admin/kb/reload",
        headers=headers,
        json={"kind": "file", "location": "nonexistent_file_path_123.jsonl"},
    )
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert "details" in err
