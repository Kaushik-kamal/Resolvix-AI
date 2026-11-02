"""Response validators (FR-B2 step 7). Code, not the LLM, decides the final tier.

Checks, in order: citations exist in the *pinned* KB version; markdown/URLs removed; at most 2 sentences;
numeric grounding sentence by sentence (a sentence with a figure not found in the cited entries is dropped, and
if that removes the essential content the answer is escalated); language consistency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from resolvix_contracts.models import Tier

from .kb.compiler import CompiledKB
from .llm import LLMMeta
from .speech import extract_facts, ungrounded
from .text import detect_lang, split_sentences, tokens, _HI_ROMAN

_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_MD = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+|[*_`#>]+|\[([^\]]*)\]\([^)]*\)")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_TAGS = re.compile(r"</?\s*(?:meta|system|assistant|user)\s*>", re.I)
_CLARIFY_OK_NUMBERS = {f"n:{i}" for i in range(1, 9)}  # "1st year or 2nd year?" style options


@dataclass
class Validated:
    tier: Tier
    text: str
    kb_ids: list[str]
    flags: list[str] = field(default_factory=list)


def clean_text(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    t = text or ""
    if _URL.search(t):
        flags.append("url_removed")
        t = _URL.sub("", t)
    t = _TAGS.sub(" ", t)
    t = _MD.sub(lambda m: m.group(1) or " ", t)
    t = _EMOJI.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t, flags


def lang_ok(text: str, session_lang: str) -> bool:
    """False only for a clear mismatch: English caller + Hindi-dominant reply, or Hindi caller + English-only reply."""
    toks = tokens(text)
    if len(toks) < 5:
        return True
    hi = sum(t in _HI_ROMAN for t in toks) + sum(1 for t in toks if any("ऀ" <= c <= "ॿ" for c in t))
    detected = detect_lang(text)
    if session_lang == "en":
        return not (hi >= 3 and hi >= len(toks) * 0.3)
    if session_lang == "hi":
        return not (hi == 0 and str(getattr(detected, "value", detected)) == "en")
    return True


def source_facts(kb: CompiledKB, ids: list[str]) -> set[str]:
    out: set[str] = set()
    for i in ids:
        e = kb.entries[i]
        # citing the source ("Exam Notice 14", "p.2") is legitimate grounding, so title/ref numbers count
        for blob in (e.answer_en, e.answer_hi or "", e.source_title, e.source_ref or ""):
            out |= extract_facts(blob)
    return out


def validate(meta: LLMMeta, spoken: str, kb: CompiledKB, session_lang: str, today: date | None = None) -> Validated:
    """``today`` (IST date) makes citations of entries whose ``valid_until`` passed after compile time invalid."""
    flags: list[str] = []
    tier = Tier(meta.tier)
    ids = list(dict.fromkeys(meta.kb_ids))

    if tier in (Tier.confident, Tier.partial):
        if not ids or any(i not in kb.entries or (today and kb.is_expired(i, today)) for i in ids):
            flags.append("citation_invalid")
            return Validated(Tier.escalate, "", [], flags)

    if tier == Tier.escalate:
        return Validated(Tier.escalate, "", ids if all(i in kb.entries for i in ids) else [], flags)

    text, cflags = clean_text(spoken)
    flags += cflags
    sents = split_sentences(text)[:2]
    if len(split_sentences(text)) > 2:
        flags.append("trimmed_sentences")
    if not sents:
        flags.append("empty_text")
        return Validated(Tier.escalate, "", [], flags)

    cited = [i for i in ids if i in kb.entries] if tier in (Tier.confident, Tier.partial) else []
    src = source_facts(kb, cited) if cited else set()
    kept: list[str] = []
    dropped = 0
    for s in sents:
        facts = extract_facts(s)
        bad = ungrounded(facts, src)
        if tier == Tier.clarify:
            bad = {f for f in bad if f not in _CLARIFY_OK_NUMBERS}
        if bad:
            dropped += 1
            continue
        kept.append(s)
    if dropped:
        flags.append("number_not_in_source")
        if not kept:
            return Validated(Tier.escalate, "", [], flags)
        if tier == Tier.confident:
            kept_has_fact = any(extract_facts(s) & src for s in kept)
            answers_have_numbers = any(extract_facts(kb.entries[i].answer_en) for i in cited)
            tier = Tier.partial if (kept_has_fact or not answers_have_numbers) else Tier.escalate
            if tier == Tier.escalate:
                return Validated(tier, "", [], flags)
    out = " ".join(kept)
    if not lang_ok(out, session_lang):
        flags.append("language_mismatch")
    return Validated(tier, out, cited if tier in (Tier.confident, Tier.partial) else [], flags)
