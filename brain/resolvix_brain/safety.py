"""Pre-LLM safety and human-request lexicon (FR-B2 step 1 and 3).

Pure string matching over normalised tokens: no network, no LLM, microseconds per call. Terms come from
``urgency_rules.yaml -> safety_lexicon`` / ``human_request_lexicon`` so staff can extend them without code.
Matching is token-sequence based, so "behosh" matches "behosh ho gaya" but not "behoshiyaan-less"; Devanagari
and romanised Hindi are matched the same way because both sides are normalised identically.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .text import normalize

# lexicon category -> UrgencyFacts.event_type
CATEGORY_EVENT = {"medical": "medical", "harassment": "harassment", "self_harm": "safety", "violence": "safety"}
_FIRST_PERSON = frozenset("mujhe mera meri mere main mai me my i myself मुझे मेरा मेरी मेरे मैं".split())


@dataclass(frozen=True)
class SafetyHit:
    category: str          # medical | harassment | self_harm | violence
    term: str              # the lexicon entry that matched
    event_type: str        # UrgencyFacts.event_type
    affected: str          # self | other


class _Index:
    """First-token -> list of (term tokens, term text, category) for O(tokens) matching."""

    def __init__(self, terms: list[tuple[str, str]]) -> None:
        self.by_first: dict[str, list[tuple[tuple[str, ...], str, str]]] = {}
        for category, term in terms:
            toks = tuple(normalize(str(term)).split())
            if toks:
                self.by_first.setdefault(toks[0], []).append((toks, str(term), category))

    def find(self, toks: list[str]) -> tuple[str, str] | None:
        for i, tok in enumerate(toks):
            for term_toks, term, category in self.by_first.get(tok, ()):
                if tuple(toks[i : i + len(term_toks)]) == term_toks:
                    return category, term
        return None


class Lexicon:
    def __init__(self, safety: dict[str, list[str]], human: list[str], human_exclusions: list[str] | None = None):
        self._safety = _Index([(cat, t) for cat, terms in safety.items() for t in terms])
        self._human = _Index([("human", t) for t in human])
        self._excl = [tuple(normalize(e).split()) for e in (human_exclusions or [])]
        self.term_count = sum(len(v) for v in safety.values())

    @classmethod
    def from_rules_file(cls, path: str | Path) -> "Lexicon":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(data.get("safety_lexicon", {}), data.get("human_request_lexicon", []),
                   data.get("human_request_exclusions", []))

    def safety_hit(self, text: str) -> SafetyHit | None:
        toks = normalize(text).split()
        found = self._safety.find(toks)
        if not found:
            return None
        category, term = found
        affected = "self" if (_FIRST_PERSON & set(toks)) else "other"
        return SafetyHit(category, term, CATEGORY_EVENT.get(category, "safety"), affected)

    def human_request(self, text: str, dtmf: str | None = None) -> bool:
        if (dtmf or "").strip() == "0":
            return True
        toks = normalize(text).split()
        hit = self._human.find(toks)
        if not hit:
            return False
        # "human resources" etc. contain a lexicon word but are not a request for a person
        joined = " ".join(toks)
        return not any(" ".join(e) in joined for e in self._excl if e)
