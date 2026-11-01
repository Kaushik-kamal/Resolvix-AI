"""Prompt-injection scan for knowledge-base text (FR-B1 step 3, PRD 3.10).

An entry whose question/answer/source text looks like an instruction to the model is *excluded* from the active
KB and listed in the compile warnings so a human can review it. The KB is also rendered as quoted data, so this
is defence in depth, not the only barrier.
"""
from __future__ import annotations

import re

from resolvix_contracts.models import KBEntry

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore-instructions", re.compile(r"\bignore\s+(?:all\s+|the\s+|any\s+|your\s+)?(?:previous|prior|above|earlier|preceding)\b", re.I)),
    ("disregard", re.compile(r"\bdisregard\b", re.I)),
    ("system-prompt", re.compile(r"\bsystem\s+prompt\b", re.I)),
    ("you-are-now", re.compile(r"\byou\s+are\s+now\b", re.I)),
    ("act-as", re.compile(r"\bact\s+as\s+(?:a|an|the|if)\b", re.I)),
    ("pretend", re.compile(r"\bpretend\s+(?:to\s+be|you)\b", re.I)),
    ("new-instructions", re.compile(r"\bnew\s+instructions?\b", re.I)),
    ("override", re.compile(r"\boverride\s+(?:the\s+|your\s+|all\s+)?(?:rules?|instructions?|safety)\b", re.I)),
    ("jailbreak", re.compile(r"\b(?:jailbreak|developer\s+mode|dan\s+mode)\b", re.I)),
    ("reveal-prompt", re.compile(r"\b(?:reveal|show|print|repeat)\s+(?:me\s+)?(?:your|the)\s+(?:prompt|instructions?|rules)\b", re.I)),
    ("protocol-tags", re.compile(r"<\s*/?\s*(?:meta|system|assistant|user|instructions?)\s*>", re.I)),
    ("fence-breaker", re.compile(r"={3,}\s*KB\s+DATA|`{3,}")),
    ("hi-ignore", re.compile(r"(?:pichhle|pichle|purane|sabhi)\s+(?:nirdesh|aadesh|instructions?)\s+(?:ko\s+)?(?:bhool|ignore|anadekha)", re.I)),
    ("hi-ignore-deva", re.compile(r"(?:पिछले|पुराने|सभी)\s+(?:निर्देश|आदेश)")),
]


def scan_text(text: str) -> list[str]:
    return [name for name, pat in _PATTERNS if pat.search(text or "")]


def scan_entry(e: KBEntry) -> list[str]:
    blob = "\n".join([*e.question_variants, e.answer_en, e.answer_hi or "", e.source_title, e.source_ref or "",
                      *e.tags])
    return sorted(set(scan_text(blob)))
