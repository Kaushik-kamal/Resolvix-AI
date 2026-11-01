"""Small shared helpers so every component speaks IDs and numbers the same way."""
from __future__ import annotations

_EN_DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_HI_DIGITS = ["shoonya", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat", "aath", "nau"]


def speak_ticket_id(ticket_id: str, lang: str = "en") -> str:
    """'EX-1042' -> 'E X, one zero four two' (en) / 'E X, ek shoonya chaar do' (hi, hinglish)."""
    digits = _HI_DIGITS if lang in ("hi", "hinglish") else _EN_DIGITS
    prefix, _, num = ticket_id.partition("-")
    letters = " ".join(prefix)
    spoken_num = " ".join(digits[int(c)] if c.isdigit() else c for c in num)
    return f"{letters}, {spoken_num}"


def sms_idempotency_key(call_id: str | None, template_id: str, to_number: str) -> str:
    return f"{call_id or 'nocall'}:{template_id}:{to_number}"


def ticket_idempotency_key(call_id: str | None, turn_index: int, ticket_type: str) -> str:
    return f"{call_id or 'nocall'}:{turn_index}:{ticket_type}"
