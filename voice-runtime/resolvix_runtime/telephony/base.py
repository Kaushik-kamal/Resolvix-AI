from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TelephonyAdapter(Protocol):
    async def transfer(self, call_id: str, to_number: str) -> bool:
        """Attempt to transfer the active call to to_number. Return True if connected, False if failed/no answer."""
        ...

    async def outbound_call(self, to_number: str, call_id: str) -> str:
        """Initiate an outbound call to to_number, associated with call_id. Return an outbound call identifier."""
        ...
