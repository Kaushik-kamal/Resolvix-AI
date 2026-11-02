"""A turn whose planning raises is rolled back: the fallback is spoken, but nothing the failed planning changed in the
working session (flow state, SMS keys recorded by ``sms_action``) is committed. See ``ResolvixBrain.handle_turn``."""
from __future__ import annotations

import pytest
from resolvix_contracts.models import TurnRequest

import resolvix_brain.flows as flows
from conftest import T_CLOSED, Caller, actions, done, kinds, speech

HUMAN = "mujhe kisi insaan se baat karni hai"          # after hours: ticket + callback + ticket_created SMS
NUM = "+919000000001"


def fail_after_sms(monkeypatch):
    """Make planning raise right after ``sms_action`` recorded its key (the spoken-line lookup that follows fails)."""
    real = flows.L

    def boom(sess, key, **kw):
        if key == "human_callback":
            raise RuntimeError("simulated failure after sms_action")
        return real(sess, key, **kw)
    monkeypatch.setattr(flows, "L", boom)
    return lambda: monkeypatch.setattr(flows, "L", real)


async def test_failed_turn_leaves_no_phantom_sms_key_and_the_next_request_still_sends(brain, monkeypatch):
    c = Caller(brain, "c-rb", NUM, now=T_CLOSED)
    heal = fail_after_sms(monkeypatch)
    ev = await c.say(HUMAN)
    assert done(ev).path == "fallback" and done(ev).rule_id == "R-FALLBACK"
    assert not actions(ev, "send_sms")                                        # the failed plan's SMS is not emitted
    assert brain.sessions.get("c-rb").sms_requested == set()                  # ... and its key was not committed
    heal()
    ev2 = await c.say(HUMAN)                                                  # a legitimate request is not suppressed
    assert len(actions(ev2, "send_sms")) == 1 and "sms_duplicate_suppressed" not in done(ev2).validator_flags


async def test_failed_turn_after_a_successful_sms_keeps_the_committed_key(brain, monkeypatch):
    c = Caller(brain, "c-rb2", NUM, now=T_CLOSED)
    assert len(actions(await c.say(HUMAN), "send_sms")) == 1
    keys = set(brain.sessions.get("c-rb2").sms_requested)
    assert keys
    fail_after_sms(monkeypatch)
    await c.say(HUMAN)                                                        # fails: rollback must not forget earlier keys
    assert brain.sessions.get("c-rb2").sms_requested == keys


async def test_fallback_response_and_ticket_are_unchanged_by_the_rollback(brain, monkeypatch):
    c = Caller(brain, "c-rb3", NUM, now=T_CLOSED)
    fail_after_sms(monkeypatch)
    ev = await c.say(HUMAN)
    assert kinds(ev)[0] == "meta" and "create_ticket" in kinds(ev) and kinds(ev)[-1] == "done"
    t = actions(ev, "create_ticket")[0].ticket
    assert (t.type, t.priority) == ("SYSTEM_FAILURE", "P3") and t.callback_requested and t.call_id == "c-rb3"
    assert "{{ticket_id}}" in speech(ev) and "sms" not in speech(ev).lower()
    assert "internal_error" in done(ev).validator_flags and "RuntimeError" in done(ev).validator_flags


async def test_fallback_is_spoken_in_the_language_of_the_failed_turn(brain, monkeypatch):
    c = Caller(brain, "c-rb4", NUM, now=T_CLOSED)
    fail_after_sms(monkeypatch)
    ev = await c.say("I want to talk to a person")                            # English; the session started as hinglish
    assert ev[0].lang == "en" and done(ev).lang == "en"
    assert "ticket" in speech(ev).lower() and "sorry" in speech(ev).lower()


async def test_failed_turn_does_not_change_a_pending_flow(brain, monkeypatch):
    c = Caller(brain, "c-rb5", NUM)
    await c.say("Hostel ka wifi do din se nahi chal raha")                   # complaint flow, location still unknown
    before = brain.sessions.get("c-rb5").pending
    assert before.name == "complaint" and not before.data["location"]
    monkeypatch.setattr(flows, "infer_category", lambda t: (_ for _ in ()).throw(RuntimeError("boom")))  # after location is set
    ev = await c.say("Block B room 214")
    assert done(ev).path == "fallback"
    after = brain.sessions.get("c-rb5").pending
    assert after is not None and after.name == "complaint" and not after.data["location"]   # half-applied update rolled back
    monkeypatch.undo()
    await c.say("Block B room 214")                                           # the same answer now works
    assert brain.sessions.get("c-rb5").pending.data["location"] == "Block B room 214"


async def test_deferred_actions_survive_a_failed_turn_and_are_emitted_once(brain, monkeypatch):
    c = Caller(brain, "c-rb6", NUM, now=T_CLOSED)
    await c.start()
    gen = brain.handle_turn(TurnRequest(call_id="c-rb6", turn_index=1, user_text=HUMAN, history=[], received_at=T_CLOSED))
    async for ev in gen:
        if ev.type == "action" and ev.action.kind == "create_ticket":
            break
    await gen.aclose()                                                        # barge-in: the SMS is deferred
    assert [e.action.kind for e in brain.sessions.get("c-rb6").deferred] == ["send_sms"]
    async def broken(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(brain, "_pipeline", broken)
    ev = await c.say("ok")                                                    # the next turn fails during planning
    assert len(actions(ev, "send_sms")) == 1 and actions(ev, "create_ticket")        # deferred SMS + fallback ticket
    assert brain.sessions.get("c-rb6").deferred == []
    ev = await c.say("ok")                                                    # still broken, nothing is replayed again
    assert not actions(ev, "send_sms")


async def test_failure_before_a_session_exists_still_gives_the_fallback(brain, monkeypatch):
    async def broken(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(brain, "_pipeline", broken)
    c = Caller(brain, "c-rb7", None)
    ev = await c.say("hello")
    assert done(ev).path == "fallback" and actions(ev, "create_ticket")
