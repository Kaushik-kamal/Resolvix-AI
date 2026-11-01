"""Shared test fixtures. Unit tests use the deterministic mock LLM and (unless marked ``realembed``) the offline
lexical embedder; ``realembed`` tests load multilingual-e5-small (cached under brain/.cache after first use)."""
from __future__ import annotations

import dataclasses
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from resolvix_contracts.models import CallChannel, CallContext, TurnRequest

from resolvix_brain import BrainSettings
from resolvix_brain.brain import ResolvixBrain
from resolvix_brain.embeddings import LexicalEmbedder, create_embedder

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures" / "brain_streams"
IST = timezone(timedelta(hours=5, minutes=30))
T_OPEN = datetime(2026, 10, 23, 10, 15, tzinfo=IST)      # a Friday, all MVP offices open (fixture time)
T_CLOSED = datetime(2026, 10, 24, 22, 30, tzinfo=IST)    # Saturday night, exam cell/accounts/helpdesk closed


def make_settings(**over) -> BrainSettings:
    s = BrainSettings.from_env({"LLM_MODE": "mock", "EMBED_MODE": "lexical", "WARMUP_ON_RELOAD": "false"})
    return dataclasses.replace(s, today_override=date(2026, 10, 23), **over)


@pytest.fixture(scope="session")
def real_embedder():
    s = dataclasses.replace(make_settings(), embed_mode="fastembed")
    emb = create_embedder(s)
    assert not emb.degraded, "multilingual-e5-small could not be loaded (needs a one-time ~470 MB download)"
    return emb


@pytest.fixture
def lexical_embedder():
    return LexicalEmbedder()


@pytest_asyncio.fixture
async def brain(lexical_embedder):
    b = ResolvixBrain(make_settings(), embedder=lexical_embedder)
    await b.ready()
    yield b
    await b.aclose()


@pytest_asyncio.fixture
async def rbrain(real_embedder):
    b = ResolvixBrain(make_settings(), embedder=real_embedder)
    await b.ready()
    yield b
    await b.aclose()


class Caller:
    """Drives a call turn by turn and collects the events of each turn."""

    def __init__(self, brain: ResolvixBrain, call_id: str = "call-t", number: str | None = "+919000000001",
                 now: datetime = T_OPEN):
        self.brain, self.call_id, self.number, self.now = brain, call_id, number, now
        self.idx = 0
        self.started = False

    async def start(self):
        self.started = True
        return await self.brain.start_call(CallContext(
            call_id=self.call_id, channel=CallChannel.pstn if self.number else CallChannel.web,
            caller_number=self.number, started_at=self.now))

    async def say(self, text: str, *, turn_index: int | None = None, dtmf: str | None = None, history=None):
        if not self.started:
            await self.start()
        self.idx = turn_index if turn_index is not None else self.idx + 1
        req = TurnRequest(call_id=self.call_id, turn_index=self.idx, user_text=text, history=history or [],
                          dtmf=dtmf, received_at=self.now)
        return [e async for e in self.brain.handle_turn(req)]


def kinds(events):
    return [(e.action.kind if e.type == "action" else e.type) for e in events]


def speech(events) -> str:
    return " ".join(e.text for e in events if e.type == "speech")


def actions(events, kind: str | None = None):
    return [e.action for e in events if e.type == "action" and (kind is None or e.action.kind == kind)]


def done(events):
    return events[-1].summary


def load_fixture(name: str):
    lines = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[0])["_request"], [json.loads(l) for l in lines[1:]]
