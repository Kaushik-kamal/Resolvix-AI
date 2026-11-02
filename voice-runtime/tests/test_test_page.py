from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient

UTTERANCES = [
    "B.Tech ki fees kitni hai aur payment kaise karni hai?",
    "What time does the hostel gate close?",
    "Sector 62 se college aane ke liye bus route kya hai?",
    "Exam 15 minute mein hai, room nahi mil raha! Roll number 2400271549999, paper Data Structures.",
    "Hostel room 302 mein student behosh ho gaya hai, ambulance bhejo",
    "Hostel mein WiFi nahi chal raha hai, haan sahi hai complaint karni hai",
    "Mujhe kisi insaan se baat karni hai",
    "Admission ke liye kaunse documents chahiye? trigger fail",
    "Re-evaluation ki fees kitni hai aur form kahan milega?",
]


@respx.mock
def test_static_pages_served(client: TestClient):
    resp_test = client.get("/test")
    assert resp_test.status_code == 200
    assert "Resolvix Helpline" in resp_test.text
    assert "Typed Test Interface" in resp_test.text

    resp_call = client.get("/call")
    assert resp_call.status_code == 200
    assert "College Voice Helpline" in resp_call.text
    assert "AgoraRTC" in resp_call.text


@respx.mock
def test_test_turn_all_scenarios(client: TestClient):
    respx.post("http://localhost:8100/v1/calls").respond(201, json={"status": "registered"})
    respx.post(url__regex=r"http://localhost:8100/v1/calls/.+/turns").respond(201, json={"status": "stored"})
    respx.post("http://localhost:8100/v1/tickets").respond(
        201, json={"ticket_id": "EX-1001", "created": True}
    )
    respx.post(url__regex=r"http://localhost:8100/v1/tickets/.+/events").respond(201, json={"status": "stored"})
    respx.post("http://localhost:8100/v1/notifications/sms").respond(
        202, json={"message_id": "msg-123", "status": "sent", "mode": "mock"}
    )
    respx.post("http://localhost:8100/v1/gaps").respond(201, json={"status": "stored"})

    for utterance in UTTERANCES:
        resp = client.post("/api/test/turn", json={"text": utterance})
        assert resp.status_code == 200
        data = resp.json()
        assert "call_id" in data
        assert "events" in data
        assert len(data["events"]) >= 2  # at least meta and done
        assert "spoken_text" in data
        assert "{{ticket_id}}" not in data["spoken_text"]
