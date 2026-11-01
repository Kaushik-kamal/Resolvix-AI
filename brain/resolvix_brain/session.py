"""In-memory call sessions (TTL 2 h), with clone/adopt so a turn can be planned on a copy and committed once.

Committing at the moment content leaves the brain (see ``brain.py``) keeps the session consistent when the runtime
cancels ``handle_turn`` for a barge-in: either the whole decision for the turn is applied or none of it.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from resolvix_contracts.models import ActionEvent, CallChannel, Lang, TicketRef

MAX_TURNS = 8


@dataclass
class Flow:
    """A pending multi-turn dialogue: complaint | unknown | urgent | clarify | human_offer."""
    name: str
    step: str
    data: dict[str, Any] = field(default_factory=dict)
    asked: int = 0            # follow-up questions asked so far in this flow
    reprompts: int = 0        # yes/no re-prompts used in the current step


@dataclass
class Session:
    call_id: str
    kb_version: str
    channel: str = CallChannel.test.value
    caller_number: str | None = None
    lang: Lang = Lang.hinglish
    script: str = "roman"
    open_tickets: list[TicketRef] = field(default_factory=list)
    turns: list[tuple[str, str]] = field(default_factory=list)       # (role, text), last MAX_TURNS
    pending: Flow | None = None
    slots: dict[str, str] = field(default_factory=dict)
    clarify_count: int = 0
    unknown_count: int = 0
    unclear_count: int = 0
    awaiting: str | None = None                                       # "anything_else"
    deferred: list[ActionEvent] = field(default_factory=list)        # critical actions lost to a barge-in
    created: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)

    def clone(self) -> "Session":
        return copy.deepcopy(self)

    def adopt(self, other: "Session") -> None:
        """Replace this session's state with ``other``'s (same call)."""
        for k, v in other.__dict__.items():
            setattr(self, k, v)

    def add_turn(self, role: str, text: str) -> None:
        if text.strip():
            self.turns.append((role, text))
            del self.turns[:-MAX_TURNS]


class SessionStore:
    def __init__(self, ttl_s: int = 7200):
        self.ttl = ttl_s
        self._s: dict[str, Session] = {}

    def get(self, call_id: str) -> Session | None:
        self._expire()
        s = self._s.get(call_id)
        if s:
            s.last_seen = time.monotonic()
        return s

    def put(self, s: Session) -> None:
        self._s[s.call_id] = s

    def drop(self, call_id: str) -> None:
        self._s.pop(call_id, None)

    def pinned_versions(self) -> set[str]:
        return {s.kb_version for s in self._s.values()}

    def __len__(self) -> int:
        return len(self._s)

    def _expire(self) -> None:
        now = time.monotonic()
        for cid in [c for c, s in self._s.items() if now - s.last_seen > self.ttl]:
            self._s.pop(cid, None)
