from __future__ import annotations

import json
from pathlib import Path
import pytest
import respx

from resolvix_contracts import ticket_idempotency_key
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
async def test_ticket_idempotency_key_identical():
    settings = RuntimeSettings(ops_api_url="http://localhost:8100", service_key="test-key")
    call_id = "call-idempotency-test"
    turn_index = 2
    ticket_type = TicketType.URGENT

    # Verify idempotency key matches contract helper
    expected_key = ticket_idempotency_key(call_id, turn_index, ticket_type.value)

    captured_keys: list[str] = []

    async with respx.mock(base_url="http://localhost:8100") as router:
        def handle_ticket(request):
            body = json.loads(request.content)
            captured_keys.append(body["idempotency_key"])
            return respx.MockResponse(201, json={"ticket_id": "EX-1042", "created": True})

        router.post("/v1/tickets").mock(side_effect=handle_ticket)

        ops_client = OpsClient(settings)
        telephony = MockTelephony()
        session = SessionState(call_id=call_id, channel=CallChannel.pstn, turn_count=turn_index)

        # First execution
        executor1 = ActionExecutor(ops_client, telephony, settings, session)
        action1 = CreateTicketAction(
            ticket=TicketCreate(
                idempotency_key=expected_key,
                call_id=call_id,
                type=ticket_type,
                priority=Priority.P1,
                priority_reason="Test reason",
                department="exam_cell",
                summary="Test ticket",
            )
        )
        await executor1.execute(action1)

        # Second replay execution
        executor2 = ActionExecutor(ops_client, telephony, settings, session)
        action2 = CreateTicketAction(
            ticket=TicketCreate(
                idempotency_key=expected_key,
                call_id=call_id,
                type=ticket_type,
                priority=Priority.P1,
                priority_reason="Test reason",
                department="exam_cell",
                summary="Test ticket",
            )
        )
        await executor2.execute(action2)

    assert len(captured_keys) == 2
    assert captured_keys[0] == captured_keys[1] == expected_key
