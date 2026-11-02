"""CR-7: the Brain requests the same SMS (recipient + template) only once per call, never claims one was sent, and
never suppresses an SMS the runtime has not received. Scope: one call (``Session.sms_requested``); no contract change."""
from __future__ import annotations

from types import SimpleNamespace

from resolvix_contracts import sms_idempotency_key
from resolvix_contracts.models import TurnRequest

from conftest import T_CLOSED, Caller, actions, done, speech
from resolvix_brain.flows import sms_action
from resolvix_brain.session import Session

HUMAN = "mujhe kisi insaan se baat karni hai"          # after hours: ticket + callback + ticket_created SMS
A, B = "+919000000001", "+919000000002"


def sess(call_id="c1") -> Session:
    return Session(call_id=call_id, kb_version="v")


def act(s: Session, template="ticket_created", to=A, plan=None):
    return sms_action(s, None, template, to, {"ticket_id": "{{ticket_id}}", "dept": "Helpdesk"}, "transactional", plan)


# ---------------------------------------------------------------- 1-4 the key: recipient + template, scoped to the session
def test_same_recipient_and_purpose_twice_in_a_call_gives_one_action():
    s = sess()
    first, second = act(s), act(s)
    assert first is not None and first.idempotency_key == sms_idempotency_key("c1", "ticket_created", A)
    assert second is None


def test_duplicate_is_flagged_on_the_plan_but_the_first_is_not():
    s, plan = sess(), SimpleNamespace(flags=[])
    act(s, plan=plan)
    assert plan.flags == []
    act(s, plan=plan)
    act(s, plan=plan)
    assert plan.flags == ["sms_duplicate_suppressed"]


def test_different_recipient_is_still_allowed():
    s = sess()
    assert act(s, to=A) is not None and act(s, to=B) is not None
    assert act(s, to=B) is None


def test_different_purpose_is_still_allowed():
    s = sess()
    assert act(s, "ticket_created") is not None and act(s, "staff_alert") is not None
    assert act(s, "staff_alert") is None


def test_another_call_is_independent_even_for_the_same_number():
    s1, s2 = sess("c1"), sess("c2")
    a1, a2 = act(s1), act(s2)
    assert a1 is not None and a2 is not None and a1.idempotency_key != a2.idempotency_key


def test_invalid_number_never_records_a_key():
    s = sess()
    assert act(s, to="12345") is None and act(s, to=None) is None and not s.sms_requested


def test_the_session_clone_keeps_its_own_copy_of_the_keys():
    s = sess()
    act(s)
    work = s.clone()
    assert act(work, to=B) is not None and B not in " ".join(s.sms_requested)    # a discarded turn leaves the call untouched


# ---------------------------------------------------------------- 5 end to end through the Brain
async def test_second_ticket_sms_is_not_requested_and_not_claimed(brain):
    c = Caller(brain, "c-dup", A, now=T_CLOSED)
    first = await c.say(HUMAN)
    assert len(actions(first, "send_sms")) == 1
    assert "requested an sms" in speech(first).lower() or "request" in speech(first).lower()
    assert "sent" not in speech(first).lower().replace("requested", "") and "bhej diya" not in speech(first)
    second = await c.say(HUMAN)
    assert actions(second, "create_ticket") and not actions(second, "send_sms")
    assert "sms" not in speech(second).lower() and "{{ticket_id}}" in speech(second)      # ticket id is still spoken
    assert "sms_duplicate_suppressed" in done(second).validator_flags


async def test_spoken_sms_line_never_says_sent_in_any_language(brain):
    for text, needle in [("mujhe kisi insaan se baat karni hai", "request"),
                         ("I want to talk to a person", "requested"), ("मुझे किसी से बात करनी है", "रिक्वेस्ट")]:
        c = Caller(brain, f"c-w-{needle}", A, now=T_CLOSED)
        ev = await c.say(text)
        assert actions(ev, "send_sms"), text
        low = speech(ev).lower()
        assert needle in low and "bhej diya" not in low and "sent you" not in low and "भेज दिया" not in low, speech(ev)


# ---------------------------------------------------------------- 6 retries and repeated turns
async def test_retrying_the_same_turn_index_does_not_bypass_dedup(brain):
    c = Caller(brain, "c-retry", A, now=T_CLOSED)
    assert len(actions(await c.say(HUMAN, turn_index=1), "send_sms")) == 1
    for _ in range(3):                                                      # the runtime resends turn 1
        again = await c.say(HUMAN, turn_index=1)
        assert not actions(again, "send_sms")


async def test_new_call_after_end_call_allows_the_sms_again(brain):
    c = Caller(brain, "c-life", A, now=T_CLOSED)
    assert len(actions(await c.say(HUMAN), "send_sms")) == 1
    await brain.end_call("c-life")
    c2 = Caller(brain, "c-life", A, now=T_CLOSED)                           # same id reused after the call ended
    assert len(actions(await c2.say(HUMAN), "send_sms")) == 1
    c3 = Caller(brain, "c-other", A, now=T_CLOSED)                          # different call, same number
    assert len(actions(await c3.say(HUMAN), "send_sms")) == 1


async def test_an_sms_the_runtime_never_received_is_delivered_later_not_suppressed(brain):
    c = Caller(brain, "c-defer", A, now=T_CLOSED)
    await c.start()
    req = TurnRequest(call_id="c-defer", turn_index=1, user_text=HUMAN, history=[], received_at=T_CLOSED)
    gen = brain.handle_turn(req)
    async for ev in gen:
        if ev.type == "action" and ev.action.kind == "create_ticket":
            break                                                            # barge-in right after the ticket
    await gen.aclose()
    nxt = await c.say("ok")                                                  # the deferred SMS is re-emitted once
    assert len(actions(nxt, "send_sms")) == 1
    later = await c.say(HUMAN)                                               # and now it counts as requested
    assert not actions(later, "send_sms")
