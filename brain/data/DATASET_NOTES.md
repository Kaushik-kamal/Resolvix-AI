# AKGEC dataset: what was converted, what was not (draft KB, Member B)

Source: `structured_rag_data_v8.json` from the shared Drive folder `AKGEC_chatbot` (a previous RAG project): 843 chunks of text
scraped from `akgec.ac.in`, lowercased, English, 2011-2026 content mixed. The file itself is **not** in this repo.

Output: `kb.jsonl` = 21 entries, **all `status=draft`** (the Brain ignores drafts, so nothing here is live until staff approve it in the
ops dashboard). Built with `scripts/ingest_raw.py` from the hand-curated rows in `raw/akgec_curated_rows.json`. Every answer sentence
was taken from the chunk(s) named in `source_ref` ("dataset chunk N" = index in the JSON list); nothing was added from outside knowledge.

## Checks that were run (real `multilingual-e5-small`, mock LLM)
- Compiles: 21 entries, 6 in the FAQ cache, **4,418 tokens** (budget 90,000), same version hash on a re-run, no warnings.
- 18 unanswerable or off-topic questions ("hostel fee kitni hai", "library timings", "director ka phone number", "bus kab chalti hai"...):
  **0** answered from the FAQ cache, all went to the escalation path.
- 6 of 10 paraphrase probes were answered from the cache. The 4 misses only went to the (mock) LLM, which cannot answer; they say nothing
  about live answer quality. **Live Groq has still not been run**, so answer quality on this KB is unmeasured.
- `brain/eval/*.jsonl` still describe the 12-entry sample KB and were **not** rewritten.

## Needs a human before any entry is approved
1. **Every entry**: confirm it is still true. The fee pages mix 2025-26 and 2026-27 content; `valid_until` is empty everywhere.
2. **Hindi answers** are drafts written for this file (romanised) and have had no native review.
3. **Fee entries** (FEE-001..007): payment mode, medical-charge cover, caution money Rs 5000 and "exam fee goes to the university" are
   consistent across the scraped tables. Check them against the live fee page.
4. **ADM-001** (UPTAC counselling) rests on a page title plus the fee note; **GEN-011** (director) merges an older bio with newer event
   pages (Director and Director General). Confirm both.

## Deliberately NOT converted (and why)
| Content | Reason |
|---|---|
| Fee amounts (tuition, hostel rent, exam fee, book bank...) | The scraped tables lost their headings: columns, programmes and sessions cannot be told apart reliably (2025-26 and 2026-27 mixed). A wrong amount would be spoken as fact. Staff should enter them from the fee notice. |
| Library timings, issue/return hours | The timings are missing in the dataset (the sentence is cut off after the labels). |
| Transport, bus routes, exam dates/results, helpline and staff phone numbers, admission cut-offs | Not present in the dataset. These are the PRD's main helpdesk topics; they must come from the college. |
| Chunks 276, 277 (`ve-cell`) | **Personal data**: student names with 13-digit roll numbers. Never put these in a KB. |
| Sports/awards lists, event reports, faculty FDP and publication lists, society pages, lab inventories | Names of individuals or not helpdesk questions; mostly 2011-2017 and outdated. |
| About 20 chunks with 10-digit numbers | Not reviewed one by one; some may be staff or individual phone numbers. Treat as personal until checked. |

## Getting to a usable KB
Staff or the college supply a fee notice, hostel notice, library timings, exam calendar, transport routes and the helpdesk phone list;
add them as rows (`raw/*.json` or the dashboard CSV import), run `python scripts/ingest_raw.py ...`, have staff approve, then rewrite the
eval sets for the real entries and re-measure.
