# Resolvix Voice Runtime & Integration (Member A)

This package contains the real-time voice orchestration layer for Resolvix. It hosts the Agora Conversational AI custom-LLM SSE streaming shim, manages call sessions and barge-in cancellation, drives the in-process `Brain`, executes typed actions (ticket-first, transfers, SMS, gaps), and serves the browser test interfaces.

---

## 1. Quickstart

### Prerequisites
- Python 3.11+
- Virtual environment with frozen contracts installed:
  ```bash
  pip install -e ../contracts/python
  pip install -e .
  ```

### Run Dev Ops Stub + Voice Runtime
In terminal 1 (starts local in-memory ops-api stub on port 8100):
```bash
python dev/ops_stub.py
```

In terminal 2 (starts voice runtime on port 8000):
```bash
uvicorn resolvix_runtime.app:app --port 8000 --reload
```

Open your browser to:
- **Typed Test Console (FR-A3):** [http://localhost:8000/test](http://localhost:8000/test)
- **Web Voice Call (Agora RTC):** [http://localhost:8000/call](http://localhost:8000/call)
- **Health Check:** [http://localhost:8000/healthz](http://localhost:8000/healthz)

---

## 2. Running Tests

Run unit and contract validation tests:
```bash
pytest tests -v
pytest ../contracts/tests -q
```
All 16 voice-runtime tests and 6 contract tests pass without requiring active network access or external vendor API keys.

---

## 3. Architecture Overview

- **Shim (`resolvix_runtime/shim.py`):** Accepts OpenAI-compatible chat completion requests from Agora (`POST /v1/chat/completions?call_id=...`). Translates `BrainEvent` streams into Agora SSE chunks:
  - `MetaEvent` → `chat.completion.custom_metadata` (interruptable control)
  - `SpeechEvent` → `chat.completion.chunk` (with `{{ticket_id}}` placeholder substitution)
  - `ActionEvent` → `executor.py` (blocking actions awaited before speech)
  - `DoneEvent` → asynchronous background push of `TurnSummary` to ops-api.
- **Action Executor (`resolvix_runtime/executor.py`):**
  - Enforces the **ticket-first** rule before transfers.
  - Generates `TMP-XXXX` tickets and uses `registered_no_id` speech if ops-api is temporarily unreachable, buffering writes in an in-memory retry queue.
  - Replaces `{{ticket_id}}` in speech with `speak_ticket_id(id, lang)` (spoken digit-by-digit) and in SMS variables with raw alphanumeric ID.
  - Simulates transfers on web/test channels and invokes telephony adapters on PSTN.
- **Barge-in Manager (`resolvix_runtime/sessions.py`):** Cancels the active stream task if a new user query arrives mid-stream for the same `call_id`.
- **Mock Brain (`resolvix_runtime/mock_brain.py`):** Replays the 9 fixture scenarios by keyword matching on user queries with dynamic `call_id` and `turn_index` rewriting. Switch to B's real brain via `BRAIN_IMPL=real`.

---

## 4. Environment Variables (`.env`)

See `.env.example` for all configurable variables:
| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | HTTP port for voice runtime |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Public HTTPS URL (Cloudflare Tunnel/ngrok) required by Agora |
| `SHIM_API_KEY` | `change-me` | Bearer token authenticated on `/v1/chat/completions` |
| `SERVICE_KEY` | `change-me` | Shared key for ops-api and `/admin/kb/reload` |
| `OPS_API_URL` | `http://localhost:8100` | Base URL for Member C ops-api |
| `BRAIN_IMPL` | `mock` | `mock` (fixtures replay) or `real` (`resolvix_brain`) |
| `TELEPHONY_MODE` | `mock` | `mock` (simulated telephony) or `agora` |
| `AGORA_APP_ID` | `""` | Agora App ID |
| `AGORA_APP_CERTIFICATE`| `""` | Agora App Certificate for dynamic token generation |
| `ASR_VENDOR` | `deepgram` | Speech-to-text vendor on Agora Conversational AI agent |
| `TTS_VENDOR` | `elevenlabs` | Text-to-speech vendor |

---

## 5. Spikes & Decisions Documentation

- [SPIKES.md](docs/SPIKES.md): Detailed results for Spike S1 (telephony/SIP & web call guarantee), Spike S3 (ASR & TTS evaluations), and Spike S4 (silence prompts & engine settings).
- [DECISIONS.md](docs/DECISIONS.md): Architectural decisions and rationale.
