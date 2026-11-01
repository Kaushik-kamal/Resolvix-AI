"""End-to-end journeys J5 and J6 against a real uvicorn on a throwaway database.

  J5  simulator call -> P1 ticket -> staff views it (masked), reveals a number, sets in_progress then resolved with a note
      -> status SMS records (mode mock) -> audit rows
  J6  caller gap -> cluster -> KB draft from the cluster -> admin approves -> mock publish -> export contains the entry

Run with: python -X utf8 dev/e2e_journeys.py        (env SMOKE_PORT picks the port; default 8100, a free one if busy)
Prints PASS/FAIL per step; exit code 0 only when every step passed.
"""
import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

OPS_API_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(Path(__file__).resolve().parent), str(OPS_API_DIR)]
from sim_lib import run_simulation  # noqa: E402

failures = 0


def check(ok: bool, message: str) -> bool:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}: {message}")
    if not ok:
        failures += 1
    return ok


def read_env() -> dict:
    values = {}
    for line in (OPS_API_DIR / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip()
    return values


def pick_port() -> int:
    wanted = int(os.environ.get("SMOKE_PORT", "8100"))
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", wanted)) != 0:
            return wanted
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def login(base_url: str, email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=base_url, timeout=15.0)
    r = c.post("/v1/auth/login", json={"email": email, "password": password})
    check(r.status_code == 200, f"login {email} -> {r.status_code}")
    return c


def journey_5(base_url, service, staff, db_path):
    print("\n--- J5: urgent call -> P1 ticket -> staff resolves it -> status SMS")
    results = run_simulation(service, speed=0, only="urgent_exam_transfer", out=lambda _l: None)
    check(len(results) == 1 and results[0].ok, f"simulator replayed the urgent exam call ({results[0].call_id if results else '-'})")
    ticket_ids = results[0].tickets
    check(len(ticket_ids) >= 1, f"simulator created ticket(s) {ticket_ids}")
    p1 = [t for t in service.get("/v1/tickets", params={"priority": "P1"}).json()["items"] if t["ticket_id"] in ticket_ids]
    check(len(p1) == 1, f"a P1 ticket exists for the call ({[t['ticket_id'] for t in p1]})")
    if not p1:
        return
    tid = p1[0]["ticket_id"]

    listed = staff.get("/v1/tickets").json()["items"]
    check(any(t["ticket_id"] == tid for t in listed), "staff session lists the P1 ticket")
    detail = staff.get(f"/v1/tickets/{tid}").json()
    masked = "•" in (detail["caller_number"] or "")
    check(masked, f"staff sees the caller number masked ({detail['caller_number']})")
    revealed = staff.get(f"/v1/tickets/{tid}?reveal=true").json()
    check(revealed["caller_number"] and "•" not in revealed["caller_number"], "reveal=true returns the full number (audited)")

    r1 = staff.patch(f"/v1/tickets/{tid}", json={"status": "in_progress", "assignee": "exam@demo"})
    r2 = staff.patch(f"/v1/tickets/{tid}", json={"status": "resolved", "note": "Room 3.12 confirmed by phone",
                                                  "resolution": "Student directed to room 3.12"})
    check(r1.status_code == 200 and r2.status_code == 200 and r2.json()["status"] == "resolved"
          and r2.json()["resolved_at"] is not None, f"status in_progress -> resolved ({r1.status_code}, {r2.status_code})")
    check(any("Room 3.12 confirmed by phone" in n for n in r2.json()["notes"]), "note appended with timestamp and actor")

    events = staff.get(f"/v1/tickets/{tid}/events").json()["items"]
    kinds = [e["kind"] for e in events]
    check(kinds.count("status_changed") == 2, f"two status_changed events ({kinds})")
    if detail.get("callback_number") and detail.get("call_id"):
        sms = [e for e in events if e["kind"] == "sms_sent"]
        check(len(sms) == 2 and all(e["payload"]["mode"] == "mock" for e in sms),
              f"two status SMS recorded, mode mock ({len(sms)})")
        check(all("•" in e["payload"]["to"] for e in sms), "SMS numbers masked in the events")
    else:
        # the P1 fixture ticket has no callback number: prove the SMS path on a fresh ticket that has one
        body = {"idempotency_key": f"e2e-{uuid.uuid4().hex[:8]}", "call_id": results[0].call_id, "type": "URGENT",
                "priority": "P1", "priority_reason": "R-EXAM-60: e2e", "department": "exam_cell",
                "summary": "E2E follow-up ticket with a callback number.", "callback_number": "+919000000002",
                "callback_requested": True, "caller_number": "+919000000002"}
        t2 = service.post("/v1/tickets", json=body).json()["ticket_id"]
        staff.patch(f"/v1/tickets/{t2}", json={"status": "in_progress"})
        staff.patch(f"/v1/tickets/{t2}", json={"status": "resolved"})
        staff.patch(f"/v1/tickets/{t2}", json={"status": "resolved"})  # same status: no third SMS
        ev2 = staff.get(f"/v1/tickets/{t2}/events").json()["items"]
        sms = [e for e in ev2 if e["kind"] == "sms_sent"]
        check(len(sms) == 2 and all(e["payload"]["mode"] == "mock" for e in sms),
              f"P1 fixture ticket has no callback number; follow-up ticket {t2} got exactly two mock status SMS ({len(sms)})")
        check(all("•" in e["payload"]["to"] for e in sms), "SMS numbers masked in the events")
        check("9000000002" not in str(ev2), "no full number anywhere in the events")

    con = sqlite3.connect(db_path)
    try:
        actions = [row[0] for row in con.execute("select action from audit_log")]
    finally:
        con.close()
    check(actions.count("ticket_updated") >= 2 and "number_revealed" in actions and "login_success" in actions,
          f"audit rows exist: ticket_updated x{actions.count('ticket_updated')}, number_revealed x{actions.count('number_revealed')}")


def journey_6(base_url, service, admin, staff):
    print("\n--- J6: knowledge gap -> cluster -> KB draft -> approve -> publish -> export")
    for q in ("bus route?", "What is the bus route", "bus route kya hai"):
        r = service.post("/v1/gaps", json={"question": q, "lang": "hinglish", "department_guess": "transport"})
        check(r.status_code == 201, f"gap posted ({q!r}) -> {r.status_code}")
    clusters = service.get("/v1/gaps/clusters").json()["items"]
    top = clusters[0] if clusters else None
    check(top is not None and top["count"] >= 3, f"gap cluster exists ({top['label'] if top else None}, count {top['count'] if top else 0})")
    if not top:
        return
    assert top["department"] == "transport"
    hidden = staff.patch(f"/v1/gaps/clusters/{top['cluster_id']}", json={"status": "needs_document"})
    check(hidden.status_code == 404, "exam_cell staff cannot touch a transport cluster (department scoping)")
    marked = admin.patch(f"/v1/gaps/clusters/{top['cluster_id']}", json={"status": "needs_document"})
    check(marked.status_code == 200 and marked.json()["status"] == "needs_document", "admin marks the cluster needs_document")

    entry = {"id": "BUS-777", "department": top["department"], "question_variants": top["examples"][:3],
             "answer_en": "The campus bus leaves the main gate every hour from 8 am to 6 pm.",
             "source_title": "Transport Notice", "is_faq": True}
    saved = staff.post("/v1/kb/entries", json=entry)
    check(saved.status_code == 201 and saved.json()["status"] == "draft" and not saved.json()["flagged"],
          f"KB draft created from the cluster ({saved.status_code}, status {saved.json().get('status')})")
    check(staff.post("/v1/kb/entries/BUS-777/status", json={"status": "approved"}).status_code == 403,
          "staff cannot approve")
    approved = admin.post("/v1/kb/entries/BUS-777/status", json={"status": "approved"})
    check(approved.status_code == 200 and approved.json()["status"] == "approved", "admin approves the entry")
    export = service.get("/v1/kb/export").json()
    check("BUS-777" in {e["id"] for e in export["entries"]}, f"export contains the entry ({len(export['entries'])} entries)")
    pub = admin.post("/v1/kb/publish")
    check(pub.status_code == 200 and pub.json()["entry_count"] == len(export["entries"]),
          f"mock publish -> {pub.status_code}, entry_count {pub.json().get('entry_count')}")
    check(any("mock" in w for w in pub.json().get("warnings", [])), "publish response is labelled mock")
    hist = admin.get("/v1/kb/publishes").json()["items"]
    check(len(hist) == 1 and hist[0]["mode"] == "mock", "publish history lists the mock publish")


def main() -> int:
    env_vars = read_env()
    service_key, password = env_vars.get("SERVICE_KEY"), env_vars.get("SEED_PASSWORD")
    if not service_key or not password:
        print("FAIL: SERVICE_KEY / SEED_PASSWORD missing from .env")
        return 1
    port = pick_port()
    run_id = uuid.uuid4().hex[:8]
    db_name = f"e2e_{run_id}.db"
    db_path = OPS_API_DIR / "data" / db_name
    env = dict(os.environ, DATABASE_URL=f"sqlite:///./data/{db_name}", PORT=str(port), NOTIFY_MODE="mock")
    python = [sys.executable, "-X", "utf8"]

    print(f"Seeding throwaway database data/{db_name}")
    seed = subprocess.run(python + ["dev/seed.py"], cwd=OPS_API_DIR, env=env, capture_output=True, text=True, encoding="utf-8")
    check(seed.returncode == 0, "dev/seed.py exited 0 on an empty database")
    proc = subprocess.Popen(python + ["-m", "uvicorn", "resolvix_ops.app:app", "--port", str(port), "--loop", "asyncio",
                                      "--workers", "1"], cwd=OPS_API_DIR, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    base_url = f"http://127.0.0.1:{port}"
    clients = []
    try:
        service = httpx.Client(base_url=base_url, timeout=15.0, headers={"X-Service-Key": service_key})
        clients.append(service)
        up = False
        for _ in range(60):
            try:
                if service.get("/healthz").status_code == 200:
                    up = True
                    break
            except httpx.TransportError:
                time.sleep(0.3)
        if not check(up, f"uvicorn up on port {port}"):
            return 1
        admin = login(base_url, "admin@demo", password)
        staff = login(base_url, "exam@demo", password)
        clients += [admin, staff]
        journey_5(base_url, service, staff, db_path)
        journey_6(base_url, service, admin, staff)
        print("\nAll journeys passed!" if failures == 0 else f"\n{failures} step(s) FAILED")
        return 0 if failures == 0 else 1
    finally:
        for c in clients:
            c.close()
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{db_path}{suffix}")
            for _ in range(20):
                try:
                    path.unlink()
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(0.25)


if __name__ == "__main__":
    sys.exit(main())
