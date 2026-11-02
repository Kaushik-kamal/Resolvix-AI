# Latency and prompt-cache measurements

Every number below was produced by `python -m resolvix_brain bench --mock` (command at the bottom) on the development laptop
(Windows 11, CPU only, Python 3.12, real `multilingual-e5-small`, **mock LLM**). Nothing here involves the network.
Spike S2 (Groq caching) is **NOT RUN**: no `GROQ_API_KEY` was available.

## Measured (this machine, 12-entry sample KB, 2,876 prompt tokens)

| What | Result |
|---|---|
| Embedder + KB cold start (model already cached on disk) | 2.1 s (first ever run downloads ~470 MB: ~47 s) |
| Safety lexicon (`safety_hit`) | 8 us per call (budget: 5 ms) |
| Urgency rule evaluation | 5 us per call |
| Query embedding (e5-small, CPU) | p50 6.0 ms, p95 6.9 ms |
| Whole `handle_turn`, FAQ path (mock LLM) | p50 6 ms, p95 7 ms (n=5) |
| Whole `handle_turn`, other paths (mock LLM, includes embedding) | p50 7 ms, p95 8 ms (n=40) |
| 50 simultaneous one-turn calls | 120 ms wall, per call p50 62 ms / p95 106 ms |
| Unit tests: 50 interleaved multi-turn complaint calls | isolated, no cross-talk (test_fifty_concurrent_calls_are_isolated) |

These are brain-only costs. End-to-end time-to-first-audio also includes ASR endpointing, the LLM and TTS, none of which
were measured here.

## NOT measured (needs a Groq key)

| Question (PRD Spike S2) | Status |
|---|---|
| `cached_tokens > 0` on the second identical-prefix call, 60k and 90k token prefixes, `gpt-oss-120b` vs `-20b` | NOT RUN |
| Warm time-to-first-token (target <= ~700 ms) | NOT RUN |
| Whether `max_tokens: 300` leaves room for reasoning tokens on `gpt-oss` | NOT RUN |
| Default model / `KB_TOKEN_BUDGET` choice | **Kept at PRD defaults (120b / 90,000)**; not validated. The sample KB is 2.9k tokens, far below any budget |

How to run S2 (the code is written and unit-tested against a mocked SSE stream; the live call itself is untested):

```powershell
cd brain
$env:GROQ_API_KEY = "<your key>"      # never commit it
$env:LLM_MODE = "live"
python -m resolvix_brain bench        # prints cold/warm ttft, total, prompt_tokens, cached_tokens for both models
```

To test a 60k/90k-token prefix, compile a KB padded with *clearly synthetic* entries (not provided here) and point
`KB_SOURCE` at it; `KB_TOKEN_BUDGET` must be raised above the padded size. Record the results in this file and choose the
model/budget from them. Fallbacks if caching fails (PRD): smaller budget, `gpt-oss-20b`, more FAQ coverage.

## Where latency can still hurt (design notes, not measurements)

- One LLM call per non-FAQ turn, buffered and validated before speaking (PRD: ~100-200 ms cost accepted for the
  no-fabrication guarantee). Retry on the fallback model only happens if the first attempt failed within 1.5 s.
- Safety, human-request, urgent pre-check, chit-chat and FAQ-hit turns never call the LLM.
- The first request after a KB reload pays the cache-miss cost unless the warm-up call (`WARMUP_ON_RELOAD`) succeeded.

## AKGEC draft KB (21 entries, 4,418 prompt tokens): live Groq status (2026-11-02)
**NOT RUN, blocked: no `GROQ_API_KEY` exists on this machine** (not in the environment, not in a `.env`). No latency, cache-hit or answer-quality number
for this KB has been measured, and none is claimed. Only the offline results exist: compiles to 4,418 tokens (budget 90,000), and
`python -m resolvix_brain eval --mock --kb-set akgec-draft` gives retrieval-proxy results (see `data/DATASET_NOTES.md`).
To run it when a key is available (never commit the key):
```powershell
$env:GROQ_API_KEY = "<your key>"          # session only
$env:LLM_MODE = "live"
python -m resolvix_brain eval --kb-set akgec-draft      # end to end on the draft KB (temporary approved copy, evaluation only)
python -m resolvix_brain bench                          # Spike S2 numbers (note: bench uses KB_SOURCE, the sample KB by default)
```
