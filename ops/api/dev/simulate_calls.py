"""Call simulator: replays contracts/fixtures/brain_streams/*.jsonl against a running Ops API, acting as Member A.

Run with: python -X utf8 dev/simulate_calls.py [--speed 1.0] [--base-url http://localhost:8100] [--only <name>]

  --speed N          1.0 = natural pacing, 10 = ten times faster, 0 = no pauses at all
  --only NAME        one scenario (or a comma-separated list); matches the fixture file name, e.g. urgent_exam_transfer
  --fail-transfers   report every transfer as failed (transfer_failed) instead of connected
  --run-id ID        suffix for call ids and idempotency keys (default: random, so reruns never collide)

The X-Service-Key comes from the SERVICE_KEY environment variable or ops/api/.env and is never printed.
Exit code 0 when every scenario completed (a missing gap endpoint is skipped, not a failure), 1 when a scenario
failed, 2 for usage errors or an unreachable server.
"""
import argparse
import os
import sys
from pathlib import Path

DEV_DIR = Path(__file__).resolve().parent
OPS_API_DIR = DEV_DIR.parent
for _path in (str(DEV_DIR), str(OPS_API_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import httpx  # noqa: E402

from sim_lib import load_scenarios, run_simulation  # noqa: E402


def read_service_key(env_file: Path) -> str | None:
    key = os.environ.get("SERVICE_KEY")
    if key:
        return key
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SERVICE_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--base-url", default="http://localhost:8100")
    parser.add_argument("--only", default=None)
    parser.add_argument("--fail-transfers", action="store_true")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    scenarios = load_scenarios(args.only)
    if not scenarios:
        names = ", ".join(s.name for s in load_scenarios())
        print(f"No scenario matches --only {args.only!r}. Available: {names}")
        return 2
    key = read_service_key(OPS_API_DIR / ".env")
    if not key:
        print("SERVICE_KEY not found (set the SERVICE_KEY env var or ops/api/.env)")
        return 2

    with httpx.Client(base_url=args.base_url, headers={"X-Service-Key": key}, timeout=15.0) as client:
        try:
            results = run_simulation(client, speed=args.speed, run_id=args.run_id,
                                     fail_transfers=args.fail_transfers, scenarios=scenarios)
        except httpx.TransportError as exc:
            print(f"Cannot reach {args.base_url}: {type(exc).__name__}")
            return 2
    failed = [r for r in results if not r.ok]
    skipped = sum(r.skipped_gaps for r in results)
    print(f"{len(results) - len(failed)}/{len(results)} scenarios completed"
          + (f", {skipped} gap call(s) skipped (endpoint missing)" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
