"""SMS policy: pure functions, no I/O except load_sms_config.

evaluate() runs the checks in a fixed order and returns the first failure as a short snake_case reason.
The contract's SmsResult.reason is a free string, so these are the documented values:

    unknown_template          template_id is not in sms_templates.yaml
    consent_not_allowed       consent value is not allowed for that template
    invalid_e164              to_number is not E.164
    staff_number_not_allowed  staff_alert to a number that is not a department/emergency sms_alert_number
    missing_vars              the template has placeholders that vars does not fill
    vars_too_long             a var (or the rendered text) is longer than the limits below
    pii_in_vars               vars carry personal data (rules below)
    url_not_allowed           the rendered text has a URL outside allowed_url_prefixes

Idempotency (lookup by idempotency_key) is not here: the service does it before calling evaluate().
"""
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

# ----- consent allowed per template
ALLOWED_CONSENT: dict[str, frozenset[str]] = {
    "ticket_created": frozenset({"transactional"}),
    "status_change": frozenset({"transactional"}),
    "answer_copy": frozenset({"caller_requested", "offer_accepted"}),
    "staff_alert": frozenset({"staff"}),
}

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
PLACEHOLDER = re.compile(r"\{(\w+)\}")

MAX_VAR_LEN = 200       # characters per var
MAX_TEXT_LEN = 480      # rendered message (3 GSM segments); keeps answer_copy summaries short

# ----- personal-data rules, applied to var VALUES only (never to the fixed template text)
# Values are normalised first (NFKC, Devanagari digits -> ASCII). Generic college information ("mess fee 3500 per
# month", "bus fare 20 rupees", "fee structure 2025") passes; data that is about a person does not:
#   marks_or_grade        marks, score, CGPA, grade, result ... with a number or grade letter, "scored/secured/got 82",
#                         "82/100", "result: pass|fail"
#   personal_dues         dues, owe(s), outstanding, overdue, arrears, balance, pending, fine, penalty next to a number
#                         (years such as 2025 do not count)
#   money_with_person     a money amount (Rs, INR, rupees, rupee sign, "5000/-") together with a person marker
#                         (your, you, his, her, their, student, ward, son, daughter, Mr/Mrs/Ms, roll, enrolment, name)
#   roll_number_with_name a roll-number-like token and a name-like token anywhere in the vars
_NUM = r"(?!(?:19|20)\d\d\b)\d[\d,. ]*"
_MARKS_AFTER = re.compile(
    r"(?i)\b(?:marks?|scores?|cgpa|sgpa|gpa|percentage|percentile|result)\b\s*(?:is|are|was|of|:|=|-)?\s*\d")
_MARKS_BEFORE = re.compile(r"(?i)\d\s*(?:marks?\b|cgpa\b|sgpa\b|gpa\b|out of\b|/\s*100\b)")
_MARKS_VERB = re.compile(r"(?i)\b(?:scored|secured|obtained|got)\s+\d")
_RESULT_WORD = re.compile(r"(?i)\bresult\b\s*(?:is|was|:|=|-)?\s*(?:pass|passed|fail|failed|detained|promoted)\b")
_GRADE = re.compile(r"\bgrade\s*[:=-]?\s*[A-F][+-]?(?![A-Za-z])", re.IGNORECASE)
_DUES_WORD = r"(?:dues?|owe[sd]?|outstanding|overdue|arrears|balance|pending|fine|penalty)"
_DUES = re.compile(rf"(?i)\b{_DUES_WORD}\b\D{{0,15}}{_NUM}|{_NUM}\D{{0,15}}\b{_DUES_WORD}\b")
_MONEY = re.compile(r"(?i)(?:₹|\brs\.?|\binr\s?|\brupees?\b|रुपये|रुपए|रुपया)\s*\d|\d[\d,]*(?:\.\d+)?\s*(?:₹|\brs\b|\binr\b|\brupees?\b|रुपये|रुपए|/-)")
_PERSON = re.compile(
    r"(?i)\b(?:your|yours|you|his|her|their|student|ward|son|daughter|mr|mrs|ms|miss|roll|enrol\w*)\b|\bname\b")
_ROLL = [
    re.compile(r"(?<![\d+])\d{9,14}(?!\d)"),                       # bare 9-14 digit run (phone numbers start with +)
    re.compile(r"\b\d{2}[A-Za-z]{2,4}\d{3,6}\b"),                  # 21CS1234 style
    re.compile(r"(?i)\b(?:roll|enrol\w*)\s*(?:no\.?|number|#)?\s*[:#-]?\s*[A-Za-z0-9]*\d"),
]
_NAME = [
    re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b"),      # two or more Capitalised words
    re.compile(r"(?i)\b(?:mr|mrs|ms|miss|dr|shri|smt)\.?\s+[A-Za-z]{2,}"),
    re.compile(r"(?i)\bname\b\s*[:=-]?\s*[A-Za-z]"),
]
_DEVANAGARI_DIGITS = {ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")}

# URLs: with a scheme, www., or a bare domain on a common TLD. Trailing punctuation is not part of the URL.
_URL = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]*://[^\s]*|\bwww\.[^\s]+|\b\d{1,3}(?:\.\d{1,3}){3}\b[^\s]*"
    r"|\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b[^\s]*)")


@dataclass(frozen=True)
class SmsConfig:
    templates: dict[str, str]
    allowed_url_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str | None = None
    text: str | None = None   # rendered message when ok


def load_sms_config(path: Path) -> SmsConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SmsConfig(
        templates=dict(raw.get("templates", {})),
        allowed_url_prefixes=tuple(raw.get("allowed_url_prefixes", [])),
    )


def staff_alert_numbers(departments_config) -> frozenset[str]:
    """Every sms_alert_number of every department plus the emergency ones."""
    numbers: set[str] = set()
    for dept in departments_config.departments:
        numbers.update(dept.sms_alert_numbers)
    numbers.update(departments_config.emergency.get("sms_alert_numbers", []))
    return frozenset(numbers)


def placeholders(template: str) -> list[str]:
    return PLACEHOLDER.findall(template)


def render(template: str, variables: dict[str, str]) -> str:
    """Fill {name} placeholders; plain substitution, so values can never inject format syntax."""
    return PLACEHOLDER.sub(lambda m: variables[m.group(1)], template)


def pii_in_vars(variables: dict[str, str]) -> str | None:
    """Return the name of the first PII rule the vars violate, else None."""
    values = [unicodedata.normalize("NFKC", v).translate(_DEVANAGARI_DIGITS) for v in variables.values()
              if isinstance(v, str)]
    for v in values:
        if _MARKS_AFTER.search(v) or _MARKS_BEFORE.search(v) or _MARKS_VERB.search(v) or _RESULT_WORD.search(v) \
                or _GRADE.search(v):
            return "marks_or_grade"
        if _DUES.search(v):
            return "personal_dues"
    joined = " | ".join(values)
    if any(p.search(joined) for p in _ROLL) and any(p.search(joined) for p in _NAME):
        return "roll_number_with_name"
    if _MONEY.search(joined) and _PERSON.search(joined):
        return "money_with_person"
    return None


def disallowed_url(text: str, allowed_prefixes: tuple[str, ...]) -> str | None:
    """First URL-like token in text that is not under an allowed prefix, else None.

    Any dotted host name counts as a URL candidate (no TLD list), as does a dotted quad or anything with "://".
    An allowed URL must be plain ASCII and contain no ".." path segment.
    """
    text = unicodedata.normalize("NFKC", text)
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(".,;:!?)\"\'")
        if not any(url.startswith(prefix) for prefix in allowed_prefixes):
            return url
        if not url.isascii() or ".." in url or "%2e" in url.lower():
            return url
    return None


def evaluate(
    config: SmsConfig,
    staff_numbers: frozenset[str],
    *,
    template_id: str,
    consent: str,
    to_number: str,
    variables: dict[str, str],
) -> Decision:
    """Run checks 1, 2, 4, 5, 6, 7 in order; the first failure wins."""
    template = config.templates.get(template_id)
    if template is None:
        return Decision(False, "unknown_template")

    if consent not in ALLOWED_CONSENT.get(template_id, frozenset()):
        return Decision(False, "consent_not_allowed")

    if not E164.match(to_number):
        return Decision(False, "invalid_e164")
    if template_id == "staff_alert" and to_number not in staff_numbers:
        return Decision(False, "staff_number_not_allowed")

    needed = placeholders(template)
    if any(name not in variables for name in needed):  # extra vars are ignored
        return Decision(False, "missing_vars")
    used = {name: variables[name] for name in needed}
    if any(len(v) > MAX_VAR_LEN for v in used.values()):
        return Decision(False, "vars_too_long")

    if pii_in_vars(variables):  # scan every supplied var, even extras that would be ignored
        return Decision(False, "pii_in_vars")

    text = render(template, used)
    if len(text) > MAX_TEXT_LEN:
        return Decision(False, "vars_too_long")
    if disallowed_url(text, config.allowed_url_prefixes):
        return Decision(False, "url_not_allowed")
    return Decision(True, None, text)
