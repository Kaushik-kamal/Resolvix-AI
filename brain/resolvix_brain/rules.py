"""Deterministic urgency rule table (FR-B2 step 8).

The LLM only *extracts* ``UrgencyFacts``; this module decides priority, ticket type, department spec and action
from ``urgency_rules.yaml`` (first match wins). Supported conditions: ``key: value``, ``<key>_lte: n``,
``<key>_gte: n``, ``<key>_lt``/``_gt``, ``<key>_in: [..]``. A missing fact (None) never satisfies a numeric
comparison. Emotional tone is not an input anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    priority: str
    ticket_type: str | None
    department: str | None        # raw spec: a department key, from_event, from_topic, from_topic_or_default
    action: str
    reason: str


def _cond_ok(key: str, expected: Any, facts: dict[str, Any]) -> bool:
    for suffix, op in (("_lte", lambda a, b: a <= b), ("_gte", lambda a, b: a >= b),
                       ("_lt", lambda a, b: a < b), ("_gt", lambda a, b: a > b)):
        if key.endswith(suffix):
            val = facts.get(key[: -len(suffix)])
            return val is not None and op(val, expected)
    if key.endswith("_in"):
        return facts.get(key[:-3]) in expected
    return facts.get(key) == expected


class RuleTable:
    def __init__(self, rules: list[dict[str, Any]], version: int = 1):
        if not rules or rules[-1].get("when") != {}:
            raise ValueError("urgency_rules.yaml: the last rule must be the catch-all (when: {})")
        self.rules = rules
        self.version = version

    @classmethod
    def from_file(cls, path: str | Path) -> "RuleTable":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(data["rules"], data.get("version", 1))

    def evaluate(self, facts: dict[str, Any]) -> RuleResult:
        """First matching rule. ``facts`` = UrgencyFacts fields + ``intent`` + ``tier``."""
        for r in self.rules:
            when = r.get("when") or {}
            if all(_cond_ok(k, v, facts) for k, v in when.items()):
                return RuleResult(r["id"], r["priority"], r.get("ticket_type"), r.get("department"),
                                  r.get("action", "none"), r.get("reason", ""))
        raise RuntimeError("no rule matched; catch-all missing")  # unreachable: __init__ enforces catch-all

    def rule(self, rule_id: str) -> RuleResult:
        for r in self.rules:
            if r["id"] == rule_id:
                return RuleResult(r["id"], r["priority"], r.get("ticket_type"), r.get("department"),
                                  r.get("action", "none"), r.get("reason", ""))
        raise KeyError(rule_id)
