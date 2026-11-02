"""Thin wrapper so the PRD layout works: ``python eval/run_eval.py [--mock]`` == ``python -m resolvix_brain eval``."""
import sys

from resolvix_brain.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(["eval", *sys.argv[1:]]))
