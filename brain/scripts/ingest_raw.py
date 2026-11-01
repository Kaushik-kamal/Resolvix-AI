"""Convert the college's raw Q&A / notice text into ``brain/data/kb.jsonl`` (KBEntry), for human review.

    python scripts/ingest_raw.py data/raw/dataset.csv            # writes data/kb.jsonl + data/kb_review.md
    python scripts/ingest_raw.py data/raw/faq.md --out data/kb.jsonl

Accepted inputs (auto-detected by extension):
  .csv             columns (case-insensitive, any subset): question(s), answer, answer_hi, department, source, source_ref,
                   valid_from, valid_until, tags, faq
  .json / .jsonl   a list (or lines) of objects with the same keys
  .md / .txt       blocks of "Q: ...", "A: ...", optional "Dept: ...", "Source: ...", separated by blank lines

Rules (PRD 5.5): every generated entry is ``status=draft`` (a human approves in the ops dashboard), ids are a department
prefix plus a number, uncertain items are listed in the review file, and ``source_title``/``source_ref`` are kept. Nothing
here invents an answer: rows without a question or an answer are skipped and reported.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from resolvix_contracts.models import KBEntry

BRAIN_DIR = Path(__file__).resolve().parents[1]
PREFIX = {"accounts": "FEE", "exam_cell": "EXM", "hostel": "HST", "helpdesk": "GEN", "transport": "TRN",
          "admissions": "ADM", "library": "LIB", "emergency": "EMG"}


def _rows_from_text(text: str) -> list[dict]:
    rows = []
    for block in re.split(r"\n\s*\n", text.strip()):
        row: dict = {}
        for line in block.splitlines():
            m = re.match(r"\s*(Q|A|A_HI|Dept|Department|Source|Ref|Valid_until|Valid_from)\s*[:\-]\s*(.*)", line, re.I)
            if m:
                k = {"q": "question", "a": "answer", "a_hi": "answer_hi", "dept": "department", "ref": "source_ref"}.get(m.group(1).lower(), m.group(1).lower())
                row[k] = (row.get(k, "") + " " + m.group(2)).strip()
            elif row:
                last = list(row)[-1]
                row[last] += " " + line.strip()
        if row:
            rows.append(row)
    return rows


def read_rows(path: Path) -> list[dict]:
    ext = path.suffix.lower()
    if ext == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    if ext in (".json", ".jsonl"):
        raw = path.read_text(encoding="utf-8-sig")
        data = [json.loads(l) for l in raw.splitlines() if l.strip()] if ext == ".jsonl" else json.loads(raw)
        if isinstance(data, dict):
            data = data.get("entries") or data.get("data") or [data]
        return [{str(k).lower(): v for k, v in r.items()} for r in data]
    return _rows_from_text(path.read_text(encoding="utf-8-sig"))


def convert(rows: list[dict], directory) -> tuple[list[dict], list[str]]:
    counters: dict[str, int] = {}
    out, review = [], []
    for n, r in enumerate(rows, 1):
        q = r.get("question") or r.get("questions") or r.get("q")
        a = r.get("answer") or r.get("a") or r.get("answer_en")
        if not q or not a:
            review.append(f"row {n}: skipped (needs both a question and an answer)")
            continue
        variants = [v.strip() for v in re.split(r"\s*\|\s*|\n", q if isinstance(q, str) else "|".join(q)) if v.strip()]
        dept = (r.get("department") or "").strip().lower().replace(" ", "_") or None
        if dept not in directory.by_key:
            guess = directory.match_topics(" ".join(variants) + " " + str(a))
            review.append(f"row {n}: department {dept!r} unknown; guessed {guess or directory.default!r}")
            dept = guess or directory.default
        pre = PREFIX.get(dept, "GEN")
        counters[pre] = counters.get(pre, 0) + 1
        title = r.get("source") or r.get("source_title") or ""
        if not title:
            title = "UNKNOWN SOURCE (fill in)"
            review.append(f"row {n}: no source document named; set source_title before approving")
        tags = r.get("tags") or []
        entry = {"id": f"{pre}-{counters[pre]:03d}", "department": dept, "question_variants": variants, "answer_en": str(a).strip(),
                 "answer_hi": (r.get("answer_hi") or None), "source_title": title, "source_ref": r.get("source_ref") or None,
                 "valid_from": r.get("valid_from") or None, "valid_until": r.get("valid_until") or None,
                 "tags": tags.split(",") if isinstance(tags, str) and tags else (tags or []),
                 "is_faq": str(r.get("faq", "")).lower() in ("1", "true", "yes"), "status": "draft"}
        if not entry["answer_hi"]:
            review.append(f"{entry['id']}: no Hindi answer (spoken Hindi will fall back to English); add and review answer_hi")
        if not entry["valid_until"] and re.search(r"\b(20\d\d|last date|deadline|till|until)\b", entry["answer_en"], re.I):
            review.append(f"{entry['id']}: answer mentions a date/deadline but has no valid_until; confirm validity")
        KBEntry.model_validate(entry)  # fail loudly on schema problems
        out.append(entry)
    return out, review


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default=str(BRAIN_DIR / "data" / "kb.jsonl"))
    ap.add_argument("--departments", default=str(BRAIN_DIR.parent / "contracts" / "config" / "departments.yaml"))
    a = ap.parse_args(argv)
    from resolvix_brain.routing import Directory

    entries, review = convert(read_rows(Path(a.input)), Directory.from_file(a.departments))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
    rev = out.with_name(out.stem + "_review.md")
    rev.write_text("# Review list (all entries are status=draft)\n\n" + "\n".join(f"- {r}" for r in review) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} draft entries to {out} and {len(review)} review items to {rev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
