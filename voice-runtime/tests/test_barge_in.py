from __future__ import annotations

import asyncio
import pytest
from resolvix_contracts.models import CallChannel
from resolvix_runtime.sessions import get_session_registry


@pytest.mark.asyncio
async def test_barge_in_cancels_previous_stream_task():
    registry = get_session_registry()
    call_id = "call-barge-in-test"

    session, _ = registry.get_or_create(call_id=call_id, channel=CallChannel.web)

    cancelled_event = asyncio.Event()

    async def long_stream():
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            cancelled_event.set()
            raise

    task1 = asyncio.create_task(long_stream())
    registry.register_task(call_id, task1)

    assert not task1.done()
    assert not task1.cancelled()

    # Second incoming turn triggers barge-in
    task2 = asyncio.create_task(asyncio.sleep(0.1))
    registry.register_task(call_id, task2)

    # Allow event loop to process cancellation
    await asyncio.sleep(0.01)

    assert task1.cancelled() or cancelled_event.is_set()
    assert session.active_stream_task == task2

    await task2
