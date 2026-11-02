from __future__ import annotations

import json
from pathlib import Path
import pytest
import respx
from pydantic import TypeAdapter

from resolvix_contracts import TICKET_ID_PLACEHOLDER
from resolvix_contracts.models import BrainEvent, CallChannel
from resolvix_runtime.config import RuntimeSettings
from resolvix_runtime.executor import ActionExecutor
from resolvix_runtime.ops_client import OpsClient
from resolvix_runtime.sessions import SessionState
from resolvix_runtime.telephony.mock import MockTelephony

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "contracts" / "fixtures" / "brain_streams"
BRAIN_EVENT_ADAPTER = TypeAdapter(BrainEvent)


@pytest.mark.asyncio
async def test_all_nine_fixtures_executor_ordering():
    fixture_files = sorted(FIXTURES_DIR.glob("*.jsonl"))
    assert len(fixture_files) >= 9

    settings = RuntimeSettings(
        port=8000,
        ops_api_url="http://localhost:8100",
        service_key="test-key",
    )

    for fixture_file in fixture_files:
        lines = fixture_file.read_text(encoding="utf-8").strip().splitlines()
        req_info = json.loads(lines[0])["_request"]
        call_id = req_info["call_id"]
        turn_index = req_info["turn_index"]

        events = [BRAIN_EVENT_ADAPTER.validate_python(json.loads(line)) for line in lines[1:]]

        call_order: list[str] = []

        async with respx.mock(base_url="http://localhost:8100", assert_all_called=False) as router:
            def record_ticket(request):
                call_order.append("ticket")
                return respx.MockResponse(201, json={"ticket_id": "EX-1042", "created": True})

            def record_event(request):
                call_order.append(f"event:{request.url.path}")
                return respx.MockResponse(201, json={"status": "stored"})

            def record_sms(request):
                call_order.append("sms")
                body = json.loads(request.content)
                # Assert SMS vars carry the raw ticket_id, NOT spoken digits
                if "ticket_id" in body.get("vars", {}):
                    assert body["vars"]["ticket_id"] == "EX-1042"
                return respx.MockResponse(202, json={"message_id": "msg-123", "status": "sent", "mode": "mock"})

            def record_gap(request):
                call_order.append("gap")
                return respx.MockResponse(201, json={"status": "stored"})

            router.post("/v1/tickets").mock(side_effect=record_ticket)
            router.post(url__regex=r"/v1/tickets/.+/events").mock(side_effect=record_event)
            router.post("/v1/notifications/sms").mock(side_effect=record_sms)
            router.post("/v1/gaps").mock(side_effect=record_gap)

            ops_client = OpsClient(settings)
            telephony = MockTelephony(transfer_success=True)
            # Test in PSTN channel to assert on transfer execution order
            session = SessionState(call_id=call_id, channel=CallChannel.pstn, turn_count=turn_index)
            executor = ActionExecutor(ops_client, telephony, settings, session)

            seen_ticket = False
            for ev in events:
                if ev.type == "meta":
                    lang = ev.lang.value if hasattr(ev.lang, "value") else str(ev.lang)
                elif ev.type == "action":
                    if ev.action.kind == "create_ticket":
                        seen_ticket = True
                    if ev.action.kind == "transfer" and ev.action.requires_ticket:
                        assert seen_ticket, f"Transfer attempted before ticket created in {fixture_file.name}"
                        assert "ticket" in call_order, f"Ticket not called before transfer in {fixture_file.name}"

                    await executor.execute(ev.action, lang=lang)

                elif ev.type == "speech":
                    processed = executor.process_speech_text(ev.text, lang=lang)
                    if TICKET_ID_PLACEHOLDER in ev.text or "{{ticket_id}}" in ev.text:
                        assert TICKET_ID_PLACEHOLDER not in processed
                        assert "{{ticket_id}}" not in processed
                        assert "EX" in processed or "one zero" in processed or "ek shoonya" in processed
