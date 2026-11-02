# Engineering Decisions: Member A (Voice Runtime & Integration)

This document records architectural, protocol, and engineering decisions made during the implementation of Member A's responsibilities.

---

## 1. Barge-In Task Registry (`sessions.py`)
- **Context:** When a caller speaks while the assistant is streaming audio, Agora immediately posts a new chat completion request for the same `call_id`.
- **Decision:** A thread-safe `SessionRegistry` tracks the currently executing SSE streaming pump task for each `call_id`. When a new request arrives, any active task for that `call_id` is immediately cancelled via `asyncio.Task.cancel()`.
- **Rationale:** Cancelling the task causes `handle_turn` to exit immediately, freeing memory and network resources without blocking the incoming turn. The brain in-process iterator catches `asyncio.CancelledError` and releases internal state.

## 2. Temporary Ticket ID on Ops API Unavailability
- **Context:** When ops-api is unreachable or experiencing timeouts during a blocking `create_ticket` action, the caller must not experience a dropped call or silence.
- **Decision:** If the ops-api call fails after 2 retries (with 2-second timeouts), the runtime generates a temporary ID (`TMP-XXXX`), queues the request in an in-memory retry queue flushed every 5 seconds, and speaks the polite line from `runtime_lines.yaml → registered_no_id` without exposing raw digits.
- **Rationale:** High availability for voice interactions requires graceful degradation. The caller is assured their request is registered, while the system transparently buffers the write until ops-api recovers.

## 3. Placeholder Substitution Timing
- **Context:** Brain yields speech containing `{{ticket_id}}` (or `TICKET_ID_PLACEHOLDER`) before or alongside ticket actions.
- **Decision:** The ActionExecutor processes blocking actions *before* any speech chunk is emitted. If a ticket was created, `{{ticket_id}}` in speech is replaced with `speak_ticket_id(ticket_id, lang)`. In SMS variables, it is replaced with the raw alphanumeric ticket ID (e.g. `EX-1042`).
- **Rationale:** Guarantees digit-by-digit spoken pronunciation (in Hindi or English as appropriate) for the caller's ear while preserving strict raw identifiers for SMS records.

## 4. Pure Python Agora RTC Token Builder
- **Context:** Generating Agora RTC tokens typically requires compiling native C++ bindings for the Agora dynamic token generator, which can be brittle across environments (macOS arm64, linux x86_64).
- **Decision:** Implemented an HMAC-SHA256 Agora token generator in pure Python (`agora_control.py`). When credentials are empty (testing mode), returns a mock token allowing open-channel development.
- **Rationale:** Ensures zero external binary dependencies and allows seamless local testing and Docker builds.

## 5. Non-Blocking Writes via Ops Client
- **Context:** `DoneEvent` turn summaries, `log_gap`, and non-blocking SMS notifications should not add latency to the voice stream or block the finish chunk.
- **Decision:** The runtime fires `post_turn`, `post_gap`, and `post_sms` via `asyncio.create_task()`. Failures are caught and appended to `OpsClient.retry_queue`.
- **Rationale:** Reduces time-to-finish-token and ensures network hiccups to the ops database do not stutter agent speech.
