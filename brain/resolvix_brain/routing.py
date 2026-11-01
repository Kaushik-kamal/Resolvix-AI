"""Department resolution, office hours and transfer numbers, from ``departments.yaml`` (read-only)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from resolvix_contracts.models import DepartmentsConfig, Department

from .settings import get_tz
from .text import normalize

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_EVENT_DEPT = {"fee_deadline": "accounts", "admit_card": "exam_cell", "exam": "exam_cell"}


class Directory:
    def __init__(self, cfg: DepartmentsConfig):
        self.cfg = cfg
        self.by_key = {d.key: d for d in cfg.departments}
        self.tz = get_tz(cfg.timezone)
        self._topics = {d.key: [tuple(normalize(t).split()) for t in d.topics] for d in cfg.departments}

    @classmethod
    def from_file(cls, path: str | Path) -> "Directory":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(DepartmentsConfig.model_validate(raw))

    @property
    def default(self) -> str:
        return self.cfg.default_department

    def get(self, key: str) -> Department:
        return self.by_key.get(key) or self.by_key[self.cfg.default_department]

    def name(self, key: str) -> str:
        return self.get(key).name

    # ------------------------------------------------------------ hours
    def local(self, when: datetime) -> datetime:
        return when.astimezone(self.tz) if when.tzinfo else when.replace(tzinfo=self.tz)

    def is_open(self, key: str, when: datetime) -> bool:
        t = self.local(when)
        hhmm = t.strftime("%H:%M")
        day = _DAYS[t.weekday()]
        return any(day in h.days and h.open <= hhmm <= h.close for h in self.get(key).hours)

    def open_departments(self, when: datetime) -> list[str]:
        return [d.key for d in self.cfg.departments if self.is_open(d.key, when)]

    def hours_text(self, key: str) -> str:
        return "; ".join(f"{'/'.join(h.days)} {h.open}-{h.close}" for h in self.get(key).hours)

    # ------------------------------------------------------------ numbers
    def transfer_number(self, key: str) -> str:
        nums = self.get(key).transfer_numbers
        return nums[0] if nums else ""

    def emergency_transfer(self) -> str:
        em = self.cfg.emergency.get("transfer_numbers") or self.get("emergency").transfer_numbers
        return em[0] if em else ""

    def emergency_alert_numbers(self) -> list[str]:
        return list(self.cfg.emergency.get("sms_alert_numbers") or self.get("emergency").sms_alert_numbers)

    def public_numbers(self) -> list[str]:
        return list(self.cfg.emergency.get("public_numbers") or ["112"])

    # ------------------------------------------------------------ resolution
    def match_topics(self, text: str, boost: list[str] | None = None) -> str | None:
        """Department whose ``topics`` match the text best (ties broken by cited-entry departments, then order)."""
        toks = normalize(text).split()
        joined = " " + " ".join(toks) + " "
        best, best_score = None, 0
        for d in self.cfg.departments:
            score = 0
            for topic in self._topics[d.key]:
                if topic and (" " + " ".join(topic) + " ") in joined:
                    score += 1
            if score and boost and d.key in boost:
                score += 0.5
            if score > best_score:
                best, best_score = d.key, score
        return best

    def resolve(self, spec: str | None, *, text: str = "", event_type: str = "none",
                cited_depts: list[str] | None = None) -> str:
        """Turn a rule's ``department`` spec into a concrete department key."""
        if spec in self.by_key:
            return spec  # type: ignore[return-value]
        if spec == "from_event" and event_type in _EVENT_DEPT:
            return _EVENT_DEPT[event_type]
        topic = self.match_topics(text, cited_depts)
        if topic:
            return topic
        if cited_depts:
            for d in cited_depts:
                if d in self.by_key:
                    return d
        return self.cfg.default_department
