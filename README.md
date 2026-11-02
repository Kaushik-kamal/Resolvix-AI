# Resolvix — AI Voice Agent for College Helplines

Resolvix is a real-time, multilingual (Hindi, English, Hinglish) AI voice agent that answers a college helpline. It answers only from approved college knowledge. When it doesn't know, or the matter is urgent, it escalates by creating a ticket first, then transferring the call, sending SMS or promising a callback.

---

## 1. Team Responsibilities & Ownership
- **Member A (Voice Runtime & Integration):** owns `voice-runtime/`, `integration/`, root `Makefile`, `docker-compose.yml`, `.env.example`, `README.md`.
- **Member B (Brain):** owns `brain/`, `contracts/config/urgency_rules.yaml`.
- **Member C (Ops API & Dashboard):** owns `ops/`, `contracts/config/sms_templates.yaml`.
- **Contracts (`contracts/`):** v1.0.0 is frozen. Changes require agreement from all three members.

---

## 2. Quickstart: Voice Runtime (Member A)

### Install Dependencies
```bash
pip install -e contracts/python pytest pyyaml
pip install -e voice-runtime
```

### Validate Frozen Contracts
```bash
make contracts-test
# or: pytest contracts/tests -q
```

### Run Voice Runtime & Dev Ops Stub
Terminal 1 (Dev Ops Stub on :8100):
```bash
make run-ops
# Runs in-memory ops-api stub with tickets, calls, and event storage
```

Terminal 2 (Voice Runtime on :8000):
```bash
make run-runtime
# Runs voice runtime with SSE streaming and MockBrain
```

### Access Demo Interfaces
- **Typed Test Interface (Demo Backup):** [http://localhost:8000/test](http://localhost:8000/test)
- **Web Voice Call (Agora RTC):** [http://localhost:8000/call](http://localhost:8000/call)
- **Health Endpoint:** [http://localhost:8000/healthz](http://localhost:8000/healthz)

---

## 3. Running Tests

```bash
# Contract tests
make contracts-test

# Voice Runtime tests (16 tests verifying SSE format, executor ordering, barge-in, idempotency)
make test-runtime

# End-to-end integration replay
make e2e
```

---

## 4. Repository Layout
- `voice-runtime/` — Agora custom-LLM shim, ActionExecutor, session management, MockBrain, and static test pages.
- `integration/` — `e2e_test.py` and `INTEGRATION_LOG.md`.
- `contracts/` — Frozen shared contracts (`resolvix_contracts`), JSON Schemas, OpenAPI specifications, 9 scenario fixtures, and config.
- `prompts/` — Copy-ready prompts for coding agents.
