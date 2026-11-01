"""Fixed spoken lines (``prompts/lines.yaml``): en / romanised Hindi / Devanagari Hindi."""
from __future__ import annotations

from functools import lru_cache

import yaml

from .settings import PROMPTS_DIR
from .speech import read_digits


@lru_cache(maxsize=1)
def _load() -> dict:
    return yaml.safe_load((PROMPTS_DIR / "lines.yaml").read_text(encoding="utf-8"))


def line(key: str, lang: str, script: str = "roman", **fmt: str) -> str:
    """``lang`` is 'en' or 'hi' (hi covers hinglish); ``script`` 'deva' selects Devanagari when available."""
    entry = _load()[key]
    if isinstance(entry, str):
        text = entry
    else:
        variant = "en" if lang == "en" else ("deva" if script == "deva" and "deva" in entry else "hi")
        text = entry[variant]
    for k, v in fmt.items():
        text = text.replace(f"<{k}>", str(v))
    return text


def spoken_digits(number: str, lang: str) -> str:
    return read_digits(number, "en" if lang == "en" else "hi")


def greeting(lang: str) -> str:
    return _load()["greeting_bilingual"] if lang != "en" else _load()["greeting"]["en"]
