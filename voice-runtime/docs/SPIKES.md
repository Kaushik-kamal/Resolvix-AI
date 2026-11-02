# Spike Results: Member A (Voice Runtime & Integrations)

This document details the findings for Spikes S1, S3, and S4 as prescribed in `RESOLVIX_FINAL_PRD.md` and the Member A prompt.

---

## Spike S1: PSTN Inbound/Outbound, Telephony Transfer, and Web Call Guarantee

### Objectives
1. Determine whether an inbound phone call can reach the custom-LLM shim with an identifiable `call_id`.
2. Evaluate Agora inbound via SIP trunk (Twilio Elastic SIP Trunk) + number import.
3. Evaluate Agora outbound-call API (`POST /api/conversational-ai-agent/v2/projects/{appid}/call`).
4. Determine whether a live transfer to an arbitrary Indian phone number can be triggered.

### Findings
- **Inbound SIP to Agora:** Agora Conversational AI supports SIP trunking via Twilio Elastic SIP Trunk. However, provisioning Indian DID numbers with KYC/DLT verification takes several days. Trial Twilio accounts are restricted to verified caller IDs.
- **Agora Outbound API:** The Agora Conversational AI v2 outbound call API works reliably for calling verified numbers using an existing project ID and App certificate. It can pass `call_id` in the LLM query parameter (`llm.url = {PUBLIC_BASE_URL}/v1/chat/completions?call_id={id}`).
- **Telephony Transfer:** Live SIP Refer transfer over Twilio SIP trunk to arbitrary external mobile numbers requires carrier-level call forwarding permissions that are not enabled by default on standard trial accounts.
- **Simulated Transfer Strategy:** When running on `channel in (web, test)` or when external telephony transfer is unavailable:
  - Post `transfer_attempted` with `payload.mode="simulated"` to ops-api.
  - Post `transfer_failed` with `reason="simulated"` to ops-api.
  - Speak `runtime_lines.yaml → transfer_simulated` (in test channel) or the failed fallback line mentioning the ticket ID (`transfer_failed`). The ticket remains open on the dashboard so staff can follow up.

### Conclusion & Operational Decision
- **The Web Call Path (`static/call.html` with Agora Web SDK) is the primary guaranteed demo path.** It supports real-time two-way audio, voice activity detection, and instant barge-in.
- Outbound dialing via Agora REST is supported as a secondary feature when credentials are provided.
- Transfers are honestly labelled and simulated when PSTN carrier routing is unavailable.

---

## Spike S3: Agora-Supported ASR & TTS Evaluation for Hindi / English / Hinglish

### Objectives
Test the ASR and TTS options supported by Agora on Hindi/English/Hinglish samples with college names, dates, amounts, and roll numbers.

### Evaluation Summary
1. **ASR (Speech-to-Text):**
   - **Deepgram Nova-3 (`multilingual`):** Excellent transcription of code-switched Hindi-English (Hinglish). High accuracy on numerical sequences (roll numbers and fee amounts).
   - **Sarvam ASR (`saaras:v2`):** Native Hindi transcription is very accurate; handles pure Devanagari inputs well, but slightly higher latency on mixed sentences compared to Deepgram.
   - **Recommendation:** Default `ASR_VENDOR=deepgram` for optimal time-to-first-token and Hinglish support.

2. **TTS (Text-to-Speech):**
   - **ElevenLabs (Multilingual v2):** Exceptional naturalness and expressiveness for bilingual conversational speech. Correctly pronounces digit-by-digit spoken ticket IDs (e.g., "E X, one zero four two" / "E X, ek shoonya chaar do").
   - **Microsoft Azure Speech (hi-IN voices `Swara` / `Madhur`):** Highly intelligible for pure Hindi, very low latency, but less natural cadence for Hinglish mixed sentences.
   - **Recommendation:** Default `TTS_VENDOR=elevenlabs` with configured voice ID; fallback to Azure `hi-IN` voices via environment configuration.

---

## Spike S4: Engine Silence, Idle Settings, and Interruptable Metadata

### Objectives
Evaluate whether Agora Conversational AI Engine exposes idle/silence settings or events, and how `interruptable` metadata influences barge-in behavior.

### Findings
1. **Interruptable Metadata:**
   - Emitting `{"object": "chat.completion.custom_metadata", "metadata": {"interruptable": false}}` as the first SSE chunk informs Agora's turn-taking manager to disable user interruption during critical emergency scripts (Scenario 05).
   - In standard dialogue turns (`interruptable: true`), speaking into the microphone immediately triggers a new completion call from Agora, which our runtime handles via barge-in task cancellation.
2. **Silence Prompts:**
   - The engine provides configurable VAD silence timeout thresholds. When prolonged silence occurs (~5s), silence prompt 1 can be triggered ("Kya aap sun paa rahe hain?"). After ~10–12s, silence prompt 2 is triggered, followed by call termination.
   - Runtime lines for `silence_1` and `silence_2` are provided in `runtime_lines.yaml`.
