"""JSONL import: parse, validate per line, collect errors without aborting."""
import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from resolvix_contracts import KBEntry


class ImportRejected(Exception):
    """The whole upload is rejected (422): bad encoding, too big, too many lines."""


@dataclass
class ParsedImport:
    entries: list[tuple[int, KBEntry]] = field(default_factory=list)  # (line number, entry)
    errors: list[dict] = field(default_factory=list)  # [{line, message}]


def _short(err: ValidationError) -> str:
    parts = []
    for e in err.errors()[:5]:
        loc = ".".join(str(p) for p in e["loc"]) or "entry"
        parts.append(f"{loc}: {e['msg']}")
    more = len(err.errors()) - 5
    return "; ".join(parts) + (f" (+{more} more)" if more > 0 else "")


def parse_jsonl(raw: bytes, max_bytes: int, max_lines: int) -> ParsedImport:
    if len(raw) > max_bytes:
        raise ImportRejected(f"File exceeds {max_bytes} bytes")
    try:
        text = raw.decode("utf-8-sig")  # tolerates a UTF-8 BOM
    except UnicodeDecodeError as exc:
        raise ImportRejected(f"File is not valid UTF-8 ({exc.reason} at byte {exc.start})") from exc

    lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if len(lines) > max_lines:
        raise ImportRejected(f"File has {len(lines)} non-blank lines; the limit is {max_lines}")

    out = ParsedImport()
    for n, line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            out.errors.append({"line": n, "message": f"Invalid JSON: {exc.msg} (column {exc.colno})"})
            continue
        if not isinstance(data, dict):
            out.errors.append({"line": n, "message": "Each line must be a JSON object"})
            continue
        try:
            out.entries.append((n, KBEntry.model_validate(data)))
        except ValidationError as exc:
            out.errors.append({"line": n, "message": _short(exc)})
    return out
