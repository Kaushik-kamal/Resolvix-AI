"""Prompt-injection scan for KB text.

This is a hint for the admin who approves an entry, not a security boundary: a match flags the entry (it stays a
draft and cannot be approved until it is edited and re-saved clean). The text is normalised before matching so the
usual evasions do not work: NFKC (fullwidth letters), zero-width / format characters and soft hyphens removed, common
Cyrillic/Greek look-alike letters mapped to Latin, every run of punctuation or whitespace collapsed to one space,
case folded.

Patterns (on the normalised text, word-bounded so "contact assistance" does not match "act as"):
  * ignore / forget / disregard / override / bypass / skip / discard ... (up to 3 words) ... instructions / rules / prompt
  * system prompt, developer message, jailbreak, new instructions, you are now / you re now, from now on,
    pretend to be, act as a/an/if/though/the, disregard
  * Hinglish and Devanagari variants of "ignore the previous instructions"
"""
import re
import unicodedata
from typing import Any, Iterator

_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "һ": "h",
    "ԁ": "d", "ɡ": "g", "ӏ": "l", "ո": "n", "ս": "u", "ν": "v", "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ı": "i", "ⅼ": "l", "ǀ": "l",
})

_PATTERNS = [
    r"\b(?:ignore|forget|disregard|override|bypass|skip|discard)\b (?:\w+ ){0,3}?(?:instructions?|rules?|prompts?|guidelines?|directions?)\b",
    r"\bsystem prompt\b",
    r"\bdeveloper (?:message|prompt)\b",
    r"\bjailbreak\b",
    r"\bnew instructions\b|\bnew instruction (?:for you|to you|is|are)\b",
    r"\bforget (?:everything|all|what) (?:\w+ ){0,2}?(?:above|before|earlier|previous|said)\b",
    r"\byou (?:are|re) now\b",
    r"\bfrom now on\b",
    r"\bpretend (?:to be|you)\b",
    r"\bact as (?:a|an|if|though|the)\b",
    r"\bdisregard",
    # Hinglish / Devanagari
    r"\b(?:pichle|purane|saare|sabhi)\b (?:\w+ )?(?:nirdesh|instructions?|niyam)\b",
    r"\b(?:nirdesh|niyam)\w* (?:ko )?(?:ignore|bhool|andekha|nazarandaz)",
    r"(?:पिछले|पुराने|सभी|सारे) (?:\w+ )?(?:निर्देश|नियम)",
    r"(?:निर्देश|नियम)\w* (?:को )?(?:अनदेखा|भूल|नजरअंदाज|इग्नोर)",
]
INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")  # zero width, soft hyphen, bidi marks
    text = text.casefold().translate(_HOMOGLYPHS)
    # keep letters, digits and combining marks (Devanagari vowel signs); everything else becomes a space
    text = "".join(ch if unicodedata.category(ch)[0] in "LNM" else " " for ch in text)
    return " ".join(text.split())


def iter_strings(value: Any) -> Iterator[str]:
    """Every string in a JSON-like structure (dict keys included, list items and nested values included)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                yield k
            yield from iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from iter_strings(v)


def is_suspicious(entry: dict) -> bool:
    """True when any string of the entry (list items and keys included) matches after normalisation."""
    return any(INJECTION_RE.search(normalize(s)) for s in iter_strings(entry))
