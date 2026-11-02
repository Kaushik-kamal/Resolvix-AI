from __future__ import annotations

import respx
import httpx
from fastapi.testclient import TestClient
from resolvix_runtime.shim import parse_call_id


def test_auth_missing_header(client: TestClient):
    resp = client.post("/v1/chat/completions", json={"stream": True, "messages": []})
    assert resp.status_code == 401


def test_auth_invalid_token(client: TestClient):
    headers = {"Authorization": "Bearer wrong-key"}
    resp = client.post("/v1/chat/completions", headers=headers, json={"stream": True, "messages": []})
    assert resp.status_code == 401


def test_stream_false_rejected(client: TestClient):
    headers = {"Authorization": "Bearer test-shim-key"}
    resp = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"stream": False, "messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 400
    assert "stream must be true" in resp.json()["detail"]


def test_call_id_resolution_order():
    # 1. Query param takes top precedence
    messages = [{"role": "system", "content": "RESOLVIX_CALL_ID=sys-id"}]
    resolved = parse_call_id("query-call-id", messages)
    assert resolved == "query-call-id"

    # 2. System message fallback
    resolved = parse_call_id(None, messages)
    assert resolved == "sys-id"

    # 3. Generated fallback
    resolved = parse_call_id(None, [{"role": "user", "content": "hi"}])
    assert resolved.startswith("call-gen-")
