"""Load the brain-stream fixtures (contracts/fixtures/brain_streams/*.jsonl) as replayable scenarios."""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

RESOLVIX_DIR = Path(__file__).resolve().parents[4]  # sim_lib -> dev -> api -> ops -> resolvix
STREAMS_DIR = RESOLVIX_DIR / "contracts" / "fixtures" / "brain_streams"


@dataclass
class Scenario:
    name: str                  # file stem, e.g. "04_urgent_exam_transfer"
    index: int                 # position in the sorted fixture list (0-based)
    request: dict              # the "_request" line (original call_id, turn_index, ...)
    events: list[dict] = field(default_factory=list)  # meta / speech / action / done, in stream order

    @property
    def short_name(self) -> str:
        return re.sub(r"^\d+_", "", self.name)

    @property
    def original_call_id(self) -> str:
        return self.request["call_id"]

    @property
    def turn_index(self) -> int:
        return int(self.request.get("turn_index", 0))

    def matches(self, wanted: str) -> bool:
        wanted = wanted.strip().lower()
        return bool(wanted) and (wanted in (self.name.lower(), self.short_name.lower())
                                 or wanted in self.name.lower())


def load_scenarios(only: str | None = None, directory: Path | None = None) -> list[Scenario]:
    """All fixture streams sorted by file name; `only` keeps those matching any comma-separated name."""
    directory = directory or STREAMS_DIR
    scenarios = []
    for index, path in enumerate(sorted(directory.glob("*.jsonl"))):
        request, events = {}, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if "_request" in data:
                request = data["_request"]
            else:
                events.append(data)
        scenarios.append(Scenario(name=path.stem, index=index, request=request, events=events))
    if only:
        wanted = [w for w in only.split(",") if w.strip()]
        scenarios = [s for s in scenarios if any(s.matches(w) for w in wanted)]
    return scenarios
