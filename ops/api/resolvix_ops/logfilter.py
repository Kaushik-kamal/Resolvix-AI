"""Keep phone numbers out of the access log (the repeat-caller query is GET /v1/tickets?caller_number=+91...)."""
import logging
import re

from .privacy import mask_number

_NUMBER = re.compile(r"(?:%2B|\+)?\d{8,15}", re.IGNORECASE)


def mask_numbers_in_text(text: str) -> str:
    def repl(m: re.Match) -> str:
        token = m.group(0)
        prefix = "%2B" if token.upper().startswith("%2B") else "+" if token.startswith("+") else ""
        digits = token[len(prefix):]
        return (mask_number(prefix.replace("%2B", "+") + digits) or "").replace("+", prefix or "", 1) if prefix else mask_number(digits)
    return _NUMBER.sub(repl, text)


class PhoneMaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(mask_numbers_in_text(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = mask_numbers_in_text(record.msg)
        return True


def install_access_log_masking() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, PhoneMaskFilter) for f in logger.filters):
        logger.addFilter(PhoneMaskFilter())
