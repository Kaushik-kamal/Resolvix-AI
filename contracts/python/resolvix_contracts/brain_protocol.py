"""
Brain protocol — the in-process interface between A (voice-runtime) and B (brain).

B implements `Brain`. A depends ONLY on this protocol (never on brain internals).
A ships with `MockBrain` (fixtures/brain_streams/*.jsonl) so it can run without B.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from .models import BrainEvent, CallContext, CallStartPlan, KBSource, KBVersionInfo, TurnRequest


@runtime_checkable
class Brain(Protocol):
    async def start_call(self, ctx: CallContext) -> CallStartPlan:
        """Create brain-side session state for ctx.call_id; pin the active KB version; return greeting."""
        ...

    def handle_turn(self, req: TurnRequest) -> AsyncIterator[BrainEvent]:
        """
        Yield events for one caller turn, in this order:
          1. exactly one MetaEvent (first)
          2. any mix of SpeechEvent / ActionEvent
          3. exactly one DoneEvent (last)
        Must never raise to the caller: on internal failure yield a fallback MetaEvent(path='fallback'),
        a fallback SpeechEvent, a CreateTicketAction(type=SYSTEM_FAILURE) and a DoneEvent.
        Cancellation (barge-in): A may cancel the iterator at any time; B must release resources and
        record only the speech already yielded as the assistant turn.
        """
        ...

    async def end_call(self, call_id: str) -> None:
        """Drop session state for call_id."""
        ...

    async def reload_kb(self, source: KBSource) -> KBVersionInfo:
        """Compile + validate + activate a new KB version. New calls use it; live calls keep their pinned version."""
        ...

    def health(self) -> dict:
        """{'status': 'ok'|'degraded', 'kb_version': str, 'llm': 'ok'|'down', 'contract_version': str}"""
        ...
