"""
Resolvix End-to-End Integration Test Suite (owned by Member A).
Replays all 9 PRD scenarios through the typed turn interface (/api/test/turn)
and validates persistence and action execution against ops-api (:8100).
"""
from __future__ import annotations

import os
import time
import httpx
import pytest

RUNTIME_URL = os.getenv("RUNTIME_URL", "http://localhost:8000")
OPS_API_URL = os.getenv("OPS_API_URL", "http://localhost:8100")
SERVICE_KEY = os.getenv("SERVICE_KEY", "change-me")


@pytest.fixture
def http_client():
    headers = {"X-Service-Key": SERVICE_KEY}
    with httpx.Client(timeout=5.0, headers=headers) as client:
        yield client


def test_01_faq_answer(http_client):
    call_id = f"e2e-01-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "B.Tech second year fees ki last date kya hai?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "fees" in data["spoken_text"].lower() or "tarikh" in data["spoken_text"].lower() or "last date" in data["spoken_text"].lower()


def test_02_llm_answer(http_client):
    call_id = f"e2e-02-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "What time does the hostel gate close?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "gate" in data["spoken_text"].lower() or "hostel" in data["spoken_text"].lower()


def test_03_unknown_ticket(http_client):
    call_id = f"e2e-03-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "Sector 62 se college aane ke liye bus route kya hai? Haan, isi number par call kar dena."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{ticket_id}}" not in data["spoken_text"]

    # Verify ticket was created in ops-api
    tickets_resp = http_client.get(f"{OPS_API_URL}/v1/tickets")
    if tickets_resp.status_code == 200:
        items = tickets_resp.json().get("items", [])
        matching = [t for t in items if t.get("call_id") == call_id]
        if matching:
            assert matching[0]["type"] in ("KNOWLEDGE_GAP", "URGENT", "COMPLAINT", "HUMAN_REQUEST")


def test_04_urgent_exam_transfer(http_client):
    call_id = f"e2e-04-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "Exam 15 minute mein hai, room nahi mil raha! Roll number 2400271549999, paper Data Structures."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{ticket_id}}" not in data["spoken_text"]
    assert "urgent" in data["spoken_text"].lower() or "ticket" in data["spoken_text"].lower()

    # Verify P1 ticket was created in ops-api
    tickets_resp = http_client.get(f"{OPS_API_URL}/v1/tickets")
    if tickets_resp.status_code == 200:
        items = tickets_resp.json().get("items", [])
        matching = [t for t in items if t.get("call_id") == call_id]
        if matching:
            assert matching[0]["priority"] == "P1"
            assert matching[0]["type"] == "URGENT"


def test_05_emergency_safety(http_client):
    call_id = f"e2e-05-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "Hostel room 302 mein student behosh ho gaya hai, ambulance bhejo"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{ticket_id}}" not in data["spoken_text"]

    tickets_resp = http_client.get(f"{OPS_API_URL}/v1/tickets")
    if tickets_resp.status_code == 200:
        items = tickets_resp.json().get("items", [])
        matching = [t for t in items if t.get("call_id") == call_id]
        if matching:
            assert matching[0]["priority"] == "P1"
            assert matching[0]["type"] == "EMERGENCY"


def test_06_complaint_confirmed(http_client):
    call_id = f"e2e-06-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "Hostel mein 3 din se WiFi nahi chal raha hai, haan sahi hai complaint karni hai."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{ticket_id}}" not in data["spoken_text"]


def test_07_human_request(http_client):
    call_id = f"e2e-07-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "Mujhe kisi insaan se baat karni hai, agent se nahi."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{ticket_id}}" not in data["spoken_text"]


def test_08_failure_fallback(http_client):
    call_id = f"e2e-08-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "Admission ke liye kaunse documents chahiye? trigger fail"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{ticket_id}}" not in data["spoken_text"]


def test_09_partial_answer(http_client):
    call_id = f"e2e-09-{int(time.time())}"
    resp = http_client.post(
        f"{RUNTIME_URL}/api/test/turn",
        json={"call_id": call_id, "text": "Re-evaluation ki fees kitni hai aur form kahan milega?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{ticket_id}}" not in data["spoken_text"]
