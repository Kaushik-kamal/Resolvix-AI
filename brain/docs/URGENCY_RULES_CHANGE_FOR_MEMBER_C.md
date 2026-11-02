# Change to `contracts/config/urgency_rules.yaml` (Member B, for Member C)

The only shared file Member B changes. The file's content belongs to Member B; Member C only displays it
(`GET /v1/urgency-rules`, dashboard Rules page). The structure is unchanged: the same top-level keys, plus one new key, and one
new rule that uses the existing rule fields. Nothing else under `contracts/` is touched (verified: every other file is byte-identical
to the frozen v1.0.0 package, ignoring CRLF).

## What changed (`git diff`: +29 / -6)

| Change | Why |
|---|---|
| **New rule `R-FALLBACK`** (`when: {intent: system_failure}`, P3, `SYSTEM_FAILURE`, `ticket_and_callback`) | The Brain's safe fallback (LLM or internal failure) must create a ticket and a callback; the original file had no rule for it. Raised only by the Brain, never matched from caller text. |
| `safety_lexicon` extended (medical, harassment, self_harm, violence) | Recall-biased: Devanagari and romanised variants, common misspellings, "can't breathe", "fire", "chaku"... A false alarm costs a staff call; a miss can cost a life. **Needs staff review.** |
| `human_request_lexicon` extended | Hindi/Devanagari/English phrasings of "I want a person". |
| **New top-level key `human_request_exclusions`** | Phrases that contain a lexicon word but are not a request for a person ("human resources", "humanities"). Checked before the human-request lexicon. |
| Comment lines | Explain matching and the recall bias. |

## Why it must go in with the Brain

With the original file the Brain's tests fail (5: three human-request lexicon cases, the rule-file shape test, and the deterministic
CLI eval) and the SYSTEM_FAILURE fallback has no rule. With the new file all Brain tests pass.

## Checked against Member C's implementation (Member C's files were not edited)

- Member C's full API test suite passes with the new file (549 passed, 2 skipped, on a copy of this branch).
- `GET /v1/urgency-rules` serves the file as JSON; the dashboard rules model treats `when` generically and lists any rule, so `R-FALLBACK`
  appears as one more row. The dashboard tests were not re-run with this file.
- **Heads-up:** `ops/api/dev/guard_forbidden.py` keeps a SHA-256 manifest of "forbidden" paths including `contracts/config/urgency_rules.yaml`
  and `brain`. It is already failing on a fresh clone (the manifest lists `egg-info` files that are not in the repo). After this merge
  it will additionally report this file and the new `brain/` tree. That is expected; regenerate the manifest only by agreement.

## Asks of Member C
1. Review the diff of this one file; no code change is needed.
2. Decide when to refresh `ops/api/docs/forbidden_manifest.json` (after the merge).
3. Nothing else in `brain/` touches `ops/`.

## Follow-up after the PR #1 review (same file, still Member B's content)

| Change | Why |
|---|---|
| `R-FALLBACK` moved above `R-UNANSWERED` | First match wins and a fallback turn has `tier: escalate`, so it would have become a `KNOWLEDGE_GAP` ticket. Rule ids, fields and the last catch-all rule are unchanged. |
| New top-level key `safety_exclusions` | Ordinary phrases ("fire exit", "sexual harassment committee", "cyber attack"; never anything exam-related for self-harm) no longer start the P1 emergency path. It only cancels the lexicon word inside the phrase; a clear emergency elsewhere in the sentence still fires. **Needs staff review.** |
| `self_harm` lexicon extended | "jaan lena", "apni jaan", ... : "Main sach mein apni jaan lena chahta hoon" was not detected before. "fail hua toh mar jaunga" stays P1. |
| `human_request_exclusions` extended | "human anatomy", "human body", "human physiology" and similar are not a request for a person. |

Structure: still the same top-level keys plus `human_request_exclusions` and `safety_exclusions` (both lists of strings, ignored by `GET /v1/urgency-rules` consumers that do not know them).
`ops/` was not touched; the forbidden-manifest hash for this file will change again.
