from __future__ import annotations

import json
import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from resolvix_contracts.models import (
    CallChannel,
    CreateTicketAction,
    Priority,
    TicketCreate,
    TicketType,
)
from resolvix_runtime.config import RuntimeSettings
from resolvix_runtime.executor import ActionExecutor
from resolvix_runtime.ops_client import OpsClient
from resolvix_runtime.sessions import SessionState
from resolvix_runtime.telephony.mock import MockTelephony


@pytest.mark.asyncio
async def test_ops_down_buffers_in_queue_and_speaks_registered_no_id():
    settings = RuntimeSettings(ops_api_url="http://localhost:8100", service_key="test-key")

    async with respx.mock(base_url="http://localhost:8100", assert_all_called=False) as router:
        # Mock ops-api failing with 500 error / connection failure
        router.post("/v1/tickets").respond(500)
        router.post("/v1/calls").respond(500)

        ops_client = OpsClient(settings)
        telephony = MockTelephony()
        session = SessionState(call_id="call-down-test", channel=CallChannel.web)
        executor = ActionExecutor(ops_client, telephony, settings, session)

        ticket_action = CreateTicketAction(
            ticket=TicketCreate(
                idempotency_key="call-down-test:1:URGENT",
                call_id="call-down-test",
                type=TicketType.URGENT,
                priority=Priority.P1,
                priority_reason="Test urgency",
                department="exam_cell",
                summary="Student blocked",
            )
        )

        # 1. Execute ticket action while ops is down
        await executor.execute(ticket_action, lang="hi")

        # 2. Check temporary ID assigned
        assert executor.ticket_id is not None
        assert executor.ticket_id.startswith("TMP-")
        assert executor.ops_unreachable is True

        # 3. Check request is buffered in retry queue
        assert len(ops_client.retry_queue) >= 1
        queued_item = ops_client.retry_queue[-1]
        assert queued_item["type"] == "ticket_create"
        assert queued_item["payload"].idempotency_key == "call-down-test:1:URGENT"

        # 4. Check speech substitution uses registered_no_id
        original_speech = "Maine aapka ticket {{ticket_id}} bana diya hai."
        processed_speech = executor.process_speech_text(original_speech, lang="hi")
        expected_line = settings.get_runtime_line("registered_no_id", "hi")
        assert processed_speech == expected_line
        assert "TMP-" not in processed_speech
        assert "{{ticket_id}}" not in processed_speech


@respx.mock
def test_full_shim_stream_survives_ops_api_down(client: TestClient):
    # ops-api completely down
    respx.post("http://localhost:8100/v1/calls").respond(503)
    respx.post("http://localhost:8100/v1/tickets").respond(503)
    respx.post("http://localhost:8100/v1/calls/call-urgent-exam/turns").respond(503)

    headers = {"Authorization": "Bearer test-shim-key"}
    req_body = {
        "model": "resolvix-brain",
        "stream": True,
        "messages": [
            {"role": "user", "content": "Exam 15 minute mein hai, room nahi mil raha! Roll number 2400271549999"}
        ]
    }

    resp = client.post("/v1/chat/completions?call_id=call-urgent-exam", headers=headers, json=req_body)
    assert resp.status_code == 200
    text = resp.text

    # Must contain custom_metadata chunk, speech chunk with registered_no_id, finish chunk, and [DONE]
    assert "chat.completion.custom_metadata" in text
    assert "chat.completion.chunk" in text
    assert "Aapka anurodh darj kar liya gaya hai" in text or "register" in text.lower()
    assert "data: [DONE]" in text
