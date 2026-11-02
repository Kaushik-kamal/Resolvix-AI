# Raw college dataset goes here

> **Update:** a website-scrape dataset arrived (`structured_rag_data_v8.json`, kept outside the repo). A curated subset was converted into
> 21 **draft** entries: see `../DATASET_NOTES.md`, `akgec_curated_rows.json` and `../kb.jsonl`. The paragraph below describes the original plan.

The team was meant to hand over the AKGEC dataset (website scrape, notices, Q&A) at H0. **It is not in the package**, so
`brain/data/kb.jsonl` has not been generated and the Brain runs on `contracts/kb/sample_kb.jsonl`, which is
placeholder data and must never be presented as real college information.

When the dataset arrives:

```powershell
python scripts/ingest_raw.py data/raw/<file> --out data/kb.jsonl     # writes data/kb_review.md next to it
# a human reviews/approves entries (ops dashboard or by editing status), then:
$env:KB_SOURCE = "file:data/kb.jsonl"; python -m resolvix_brain compile
python -m resolvix_brain eval            # rewrite brain/eval/*.jsonl for the real KB first
```
