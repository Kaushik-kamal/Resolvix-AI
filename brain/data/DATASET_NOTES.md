# AKGEC dataset: what was converted, what was not (draft KB, Member B)

**Source:** `structured_rag_data_v8.json` from the shared Drive folder `AKGEC_chatbot`, a previous RAG project. It contains 843 text chunks scraped from `akgec.ac.in`, mostly English, lowercased, with content from 2011–2026 mixed together. The source file itself is not included in this repository.

**Output:** `kb.jsonl` contains 21 entries, all with `status=draft`. The Brain ignores draft entries, so none of this information is live until staff verify and approve entries through the Ops dashboard.

The entries were built using `scripts/ingest_raw.py` from manually curated rows in `raw/akgec_curated_rows.json`. Every answer sentence was taken from the source chunk or chunks identified in `source_ref` (`dataset chunk N` refers to the index in the original JSON list). No information was added from outside knowledge.

## Checks performed (real `multilingual-e5-small`, mock LLM)

- Compilation produced 21 entries, with 6 entries in the FAQ cache and **4,418 tokens** against a 90,000-token budget. A repeated run produced the same version hash and no warnings.
- Tested 18 unanswerable or off-topic questions, including "hostel fee kitni hai", "library timings", "director ka phone number", and "bus kab chalti hai". **Zero** were answered from the FAQ cache; all followed the escalation path.
- 6 of 10 paraphrase probes were answered from the cache. The other 4 misses went only to the mock LLM, which cannot establish live answer quality.
- **Live Groq has not yet been run**, so answer quality on this KB remains unmeasured.
- `brain/eval/*.jsonl` still describes the 12-entry sample KB and has not yet been rewritten for these 21 entries.

## Human verification required before approval

1. **Every entry:** Confirm that the information is still accurate. The source fee pages mix 2025–26 and 2026–27 content, and `valid_until` is empty for every entry.
2. **Hindi answers:** These are romanised draft answers prepared for this dataset and have not received native Hindi review.
3. **Fee entries (FEE-001 to FEE-007):** Verify payment mode, medical-charge coverage, caution money of Rs 5,000, and the statement that the exam fee goes to the university against the current official fee information.
4. **FEE-005 and FEE-007:** These contain general policy amounts, including figures such as "up to Rs 50,000", "up to Rs 1,00,000", and "Rs 5,000". They remain drafts and require staff verification before approval or publication.
5. **ADM-001:** The UPTAC counselling information relies on a page title and a fee note; confirm it against current admission information.
6. **GEN-011:** The director information combines an older biography with newer event pages referring to Director and Director General; confirm the current designation and details.

## Deliberately not converted (and why)

| Content | Reason |
|---|---|
| Personal fee amounts and fee tables (tuition, hostel rent, exam fee, book bank, etc.) | Personal fee amounts and fee tables were excluded because the scraped tables lost their headings. Columns, programmes and academic sessions cannot be reliably distinguished, with 2025–26 and 2026–27 content mixed together. FEE-005 and FEE-007 retain general policy amounts as drafts, subject to staff verification. |
| Library timings and issue/return hours | Timings are missing from the dataset; the relevant sentence is cut off after the labels. |
| Transport, bus routes, exam dates/results, helpline and staff phone numbers, admission cut-offs | These are not present in the dataset. They are important helpdesk topics and must be supplied by the college. |
| Chunks 276 and 277 (`ve-cell`) | **Personal data:** student names with 13-digit roll numbers. These were excluded and must never be added to the KB. |
| Sports and awards lists, event reports, faculty FDP and publication lists, society pages, lab inventories | These mostly contain individual names or information unrelated to helpdesk questions. Much of the material dates from 2011–2017 and may be outdated. |
| Approximately 20 chunks containing 10-digit numbers | These were not individually reviewed. Some numbers may be staff or personal phone numbers, so they were treated as potentially personal and excluded pending review. |

## Getting to a usable KB

The college or authorised staff must supply current official documents covering:

- Fee notice
- Hostel notice
- Library timings
- Examination calendar
- Transport routes
- Official helpdesk phone list

Add verified information as rows under `raw/*.json` or through the dashboard CSV import. Run `python scripts/ingest_raw.py ...`, then have authorised staff review and approve each entry.

Before production use:

1. Verify all source information and time-sensitive details.
2. Add appropriate `valid_until` dates wherever information is time-bound.
3. Obtain native Hindi review for Hindi answers.
4. Rewrite `brain/eval/*.jsonl` for the actual 21-entry dataset.
5. Run live Groq evaluation and measure answer quality and latency.
6. Confirm that only staff-approved entries are published.

**Current status:** 21 draft entries. No entries are approved or published. This dataset is an initial curated draft, not a production-verified source of college information.