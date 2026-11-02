from __future__ import annotations

import json
from pathlib import Path
import pytest
import respx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
AGORA_DIR = ROOT / "contracts" / "fixtures" / "agora"


@respx.mock
def test_sse_writer_matches_expected_fixture_04(client: TestClient):
    # Mock ops-api endpoints
    respx.post("http://localhost:8100/v1/calls").respond(201, json={"status": "created"})
    respx.post("http://localhost:8100/v1/calls/call-urgent-exam/turns").respond(201, json={"status": "stored"})
    respx.post("http://localhost:8100/v1/tickets").respond(
        201, json={"ticket_id": "EX-1042", "created": True}
    )
    respx.post("http://localhost:8100/v1/tickets/EX-1042/events").respond(201, json={"status": "stored"})
    respx.post("http://localhost:8100/v1/calls/call-urgent-exam/end").respond(200, json={"status": "ended"})

    # Load request and expected response
    req_body = json.loads((AGORA_DIR / "chat_request.json").read_text(encoding="utf-8"))
    expected_text = (AGORA_DIR / "expected_sse_for_04.txt").read_text(encoding="utf-8")

    headers = {"Authorization": "Bearer test-shim-key"}
    resp = client.post(
        "/v1/chat/completions?call_id=call-urgent-exam",
        headers=headers,
        json=req_body,
    )

    assert resp.status_code == 200
    actual_text = resp.text

    # Parse expected chunks
    expected_chunks = [c.strip() for c in expected_text.split("\n\n") if c.strip()]
    actual_chunks = [c.strip() for c in actual_text.split("\n\n") if c.strip()]

    assert len(actual_chunks) == len(expected_chunks), (
        f"Mismatch in chunk count. Expected {len(expected_chunks)}, got {len(actual_chunks)}.\n"
        f"Actual chunks:\n{actual_text}"
    )

    for i, (exp_chunk, act_chunk) in enumerate(zip(expected_chunks, actual_chunks)):
        if exp_chunk == "data: [DONE]":
            assert act_chunk == "data: [DONE]"
            continue

        assert exp_chunk.startswith("data: ")
        assert act_chunk.startswith("data: ")

        exp_json = json.loads(exp_chunk[6:])
        act_json = json.loads(act_chunk[6:])

        # Compare ignoring id and created timestamp per test requirements
        exp_json.pop("id", None)
        exp_json.pop("created", None)
        act_json.pop("id", None)
        act_json.pop("created", None)

        assert act_json == exp_json, f"Chunk {i} JSON mismatch:\nActual: {act_json}\nExpected: {exp_json}"
