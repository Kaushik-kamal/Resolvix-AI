"""The real notifier, end to end through PATCH /v1/tickets/{id} (mock provider, no network)."""
from _m2 import CountingProvider, make_ticket_body, sms_rows
from resolvix_ops.services.notify import SmsNotifier
from resolvix_ops.sms.providers import ProviderError


def new_ticket(client, auth, fixture_json, key="k", **kw):
    r = client.post("/v1/tickets", json=make_ticket_body(fixture_json, key, **kw), headers=auth)
    assert r.status_code == 201
    return r.json()["ticket_id"]


def patch(client, auth, tid, **body):
    r = client.patch(f"/v1/tickets/{tid}", json=body, headers=auth)
    assert r.status_code == 200, r.text
    return r


def kinds(client, auth, tid):
    return [e["kind"] for e in client.get(f"/v1/tickets/{tid}/events", headers=auth).json()["items"]]


def test_default_notifier_is_the_sms_notifier(client):
    assert isinstance(client.app.state.notifier, SmsNotifier)


def test_status_change_sends_exactly_one_sms_with_event(sms_client, auth, fixture_json):
    tid = new_ticket(sms_client, auth, fixture_json)
    patch(sms_client, auth, tid, status="in_progress")
    (row,) = sms_rows(sms_client)
    assert row.idempotency_key == f"{tid}:status:in_progress"
    assert (row.template_id, row.consent, row.ticket_id, row.call_id) == (
        "status_change", "transactional", tid, "call-llm-down")
    assert row.to_number == "+919000000006" and row.mode == "mock" and row.status == "sent"
    (to, text, _), = sms_client.app.state.sms.provider.sent
    assert to == "+919000000006" and text == f"College Helpline: request {tid} is now in progress."
    # visible in the very next GET, with mode mock and a masked number
    events = sms_client.get(f"/v1/tickets/{tid}/events", headers=auth).json()["items"]
    assert [e["kind"] for e in events] == ["status_changed", "sms_sent"]
    assert events[1]["payload"]["mode"] == "mock" and events[1]["payload"]["to"] == "+91•••••0006"
    assert "9000000006" not in str(events)


def test_same_status_again_sends_nothing(sms_client, auth, fixture_json):
    tid = new_ticket(sms_client, auth, fixture_json)
    patch(sms_client, auth, tid, status="open")                  # already open: not a change
    patch(sms_client, auth, tid, status="in_progress")
    patch(sms_client, auth, tid, status="in_progress")           # same again
    patch(sms_client, auth, tid, note="called the student")      # note only
    assert len(sms_rows(sms_client)) == 1 and len(sms_client.app.state.sms.provider.sent) == 1


def test_ticket_without_call_id_gets_no_sms_and_no_record(sms_client, auth, fixture_json):
    tid = new_ticket(sms_client, auth, fixture_json, call_id=None)
    patch(sms_client, auth, tid, status="in_progress")
    assert sms_rows(sms_client) == [] and "sms_sent" not in kinds(sms_client, auth, tid)
    assert "sms_suppressed" not in kinds(sms_client, auth, tid)


def test_ticket_without_callback_number_gets_no_sms_and_no_record(sms_client, auth, fixture_json):
    tid = new_ticket(sms_client, auth, fixture_json, callback_number=None, callback_requested=False)
    patch(sms_client, auth, tid, status="resolved")
    assert sms_rows(sms_client) == [] and kinds(sms_client, auth, tid) == ["status_changed"]


def test_two_distinct_status_changes_send_two_sms(sms_client, auth, fixture_json):
    tid = new_ticket(sms_client, auth, fixture_json)
    patch(sms_client, auth, tid, status="in_progress")
    patch(sms_client, auth, tid, status="resolved")
    assert [r.idempotency_key for r in sms_rows(sms_client)] == [f"{tid}:status:in_progress", f"{tid}:status:resolved"]
    assert [b for _, b, _ in sms_client.app.state.sms.provider.sent][1].endswith("is now resolved.")


def test_flipping_back_to_an_earlier_status_does_not_resend(sms_client, auth, fixture_json):
    """Documented consequence of the key "{ticket_id}:status:{new_status}"."""
    tid = new_ticket(sms_client, auth, fixture_json)
    patch(sms_client, auth, tid, status="in_progress")   # SMS "in progress"
    patch(sms_client, auth, tid, status="open")          # SMS "open" (first time for that status)
    patch(sms_client, auth, tid, status="in_progress")   # back to in_progress: key exists, no SMS
    assert len(sms_client.app.state.sms.provider.sent) == 2
    assert [r.idempotency_key.split(":")[-1] for r in sms_rows(sms_client)] == ["in_progress", "open"]
    assert kinds(sms_client, auth, tid).count("status_changed") == 3


def test_no_ticket_created_sms(sms_client, auth, fixture_json):
    new_ticket(sms_client, auth, fixture_json)
    assert sms_rows(sms_client) == []  # the PRD queues SMS on status change only


def test_invalid_callback_number_is_recorded_as_suppressed_not_failed_patch(sms_client, auth, fixture_json):
    tid = new_ticket(sms_client, auth, fixture_json, callback_number="12345")
    patch(sms_client, auth, tid, status="in_progress")
    (row,) = sms_rows(sms_client)
    assert row.status == "suppressed" and row.reason == "invalid_e164"
    assert kinds(sms_client, auth, tid) == ["status_changed", "sms_suppressed"]
    assert sms_client.app.state.sms.provider.sent == []


def test_provider_failure_does_not_fail_patch_and_is_flagged(sms_client, auth, fixture_json):
    sms_client.app.state.sms.provider = CountingProvider([ProviderError("provider_http_500")] * 2)
    tid = new_ticket(sms_client, auth, fixture_json)
    body = patch(sms_client, auth, tid, status="in_progress").json()
    assert body["status"] == "in_progress"
    (row,) = sms_rows(sms_client)
    assert row.status == "failed" and row.flagged is True and row.reason == "provider_http_500"
    assert kinds(sms_client, auth, tid) == ["status_changed", "sms_failed"]


def test_unexpected_notifier_error_does_not_fail_patch(sms_client, auth, fixture_json):
    class Exploding(CountingProvider):
        def send(self, *a, **k):
            raise RuntimeError("boom")

    sms_client.app.state.sms.provider = Exploding()
    tid = new_ticket(sms_client, auth, fixture_json)
    r = patch(sms_client, auth, tid, status="resolved")
    assert r.json()["status"] == "resolved"
    assert sms_client.get(f"/v1/tickets/{tid}", headers=auth).json()["status"] == "resolved"  # change persisted


def test_sse_ticket_updated_still_emitted(sms_client, auth, fixture_json):
    from _m2 import drain
    tid = new_ticket(sms_client, auth, fixture_json)
    _, q = sms_client.app.state.sse_hub.subscribe()
    patch(sms_client, auth, tid, status="in_progress")
    names = [n for n, _ in drain(q, 1)]
    assert names == ["ticket.updated"]  # no new event types for SMS
