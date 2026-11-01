"""Load knowledge-base entries from a JSONL file, a ``KBExport`` JSON file, or a URL returning ``KBExport``."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from pydantic import ValidationError
from resolvix_contracts.models import KBEntry, KBExport, KBSource

from .compiler import KBCompileError


def _parse_text(text: str, origin: str) -> list[KBEntry]:
    problems: list[str] = []
    entries: list[KBEntry] = []
    stripped = text.lstrip("﻿").strip()
    if not stripped:
        raise KBCompileError([f"{origin}: empty knowledge base"])
    try:
        doc = json.loads(stripped)
    except json.JSONDecodeError:
        doc = None  # not one JSON document: parse as JSONL below
    if isinstance(doc, dict) and "entries" in doc:  # KBExport
        try:
            return list(KBExport.model_validate(doc).entries)
        except ValidationError as exc:
            raise KBCompileError([f"{origin}: invalid KBExport: {_short(exc)}"]) from exc
    for n, line in enumerate(stripped.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entries.append(KBEntry.model_validate(json.loads(line)))
        except (ValidationError, json.JSONDecodeError) as exc:
            problems.append(f"{origin} line {n}: {_short(exc)}")
    if problems:
        raise KBCompileError(problems)
    return entries


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4])
    return str(exc)[:200]


def _headers(service_key: str | None) -> dict[str, str]:
    """``X-Service-Key`` only when a key is configured. Redirects are never followed (httpx default), so the key
    cannot be forwarded to another host; the key is never part of any message, log line or exception text."""
    return {"X-Service-Key": service_key} if service_key else {}


def _fetch_problem(exc: httpx.HTTPError, url: str, has_key: bool) -> KBCompileError:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 401:
            hint = ("the server rejected the configured KB_EXPORT_SERVICE_KEY (it must equal the ops-api SERVICE_KEY)"
                    if has_key else "the server requires a service key: set KB_EXPORT_SERVICE_KEY")
            return KBCompileError([f"cannot fetch {url}: HTTP 401 unauthorized: {hint}"])
        if code == 403:
            return KBCompileError([f"cannot fetch {url}: HTTP 403 forbidden: the credential was accepted but is not "
                                   "allowed to export the knowledge base"])
        return KBCompileError([f"cannot fetch {url}: HTTP {code}"])
    return KBCompileError([f"cannot fetch {url}: {exc.__class__.__name__}"])


def load_entries(source: KBSource, timeout: float = 10.0, service_key: str | None = None) -> list[KBEntry]:
    """Synchronous loader (CLI and tests). Raises ``KBCompileError`` with a problem list on any failure.
    ``service_key`` is sent as ``X-Service-Key`` for url sources only; file sources never use it."""
    if source.kind == "file":
        p = Path(source.location)
        if not p.is_file():
            raise KBCompileError([f"file not found: {p}"])
        return _parse_text(p.read_text(encoding="utf-8"), p.name)
    try:
        r = httpx.get(source.location, timeout=timeout, headers=_headers(service_key))
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise _fetch_problem(exc, source.location, bool(service_key)) from None
    return _parse_text(r.text, source.location)


async def load_entries_async(source: KBSource, timeout: float = 10.0, service_key: str | None = None) -> list[KBEntry]:
    if source.kind == "file":
        return load_entries(source)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(source.location, headers=_headers(service_key))
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise _fetch_problem(exc, source.location, bool(service_key)) from None
    return _parse_text(r.text, source.location)
