"""Numbers, dates, times: extraction for grounding checks, and spoken-form normalisation for TTS.

``extract_facts`` turns text into a set of canonical fact strings so that "95,000", "95 hazaar" and
"ninety five thousand" all become ``n:95000``, "10 pm" and "raat 10 baje" both become ``n:10`` plus the
meridiem fact ``tm:10|pm``, and month names (English, Hindi transliteration, Devanagari) become ``mo:<1-12>``.

Grounding rule (see ``validate.py``): every fact in the spoken text must appear in the cited KB entries.
Meridiem facts (``tm:``) are only compared when the source also states a meridiem for that clock time, so
a source of "10 pm" rejects "subah 10 baje" but "7:30" without am/pm cannot contradict "subah 7:30".
"""
from __future__ import annotations

import re
from datetime import date

from .text import normalize

MONTHS: dict[str, int] = {}
for _i, _names in enumerate(
    [
        "january jan janvari janwari जनवरी",
        "february feb farvari farwari फरवरी",
        "march mar maarch मार्च",
        "april apr aprail अप्रैल",
        "may mai मई",
        "june jun joon जून",
        "july jul julai जुलाई",
        "august aug agast अगस्त",
        "september sep sept sitambar सितंबर सितम्बर",
        "october oct aktubar अक्टूबर",
        "november nov navambar नवंबर नवम्बर",
        "december dec disambar दिसंबर दिसम्बर",
    ],
    start=1,
):
    for _n in _names.split():
        MONTHS[_n] = _i
# "mar" and "may" are ordinary words ("may I", "mai" = I in Hindi); only count them when written as a month
# next to a day number (handled in _tokens via _AMBIGUOUS_MONTHS).
_AMBIGUOUS_MONTHS = {"may", "mai", "mar", "jan", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "feb", "apr"}

_ONES = {
    "zero": 0, "shunya": 0, "shoonya": 0, "one": 1, "ek": 1, "two": 2, "do": 2, "three": 3, "teen": 3, "four": 4,
    "char": 4, "chaar": 4, "five": 5, "panch": 5, "paanch": 5, "six": 6, "chhe": 6, "chhah": 6,
    "seven": 7, "saat": 7, "eight": 8, "aath": 8, "nine": 9, "nau": 9, "ten": 10, "das": 10, "eleven": 11,
    "gyarah": 11, "giyarah": 11, "gyaarah": 11, "twelve": 12, "barah": 12, "baarah": 12, "thirteen": 13,
    "terah": 13, "fourteen": 14, "chaudah": 14, "fifteen": 15, "pandrah": 15, "sixteen": 16,
    "solah": 16, "seventeen": 17, "satrah": 17, "eighteen": 18, "atharah": 18, "nineteen": 19, "unnis": 19,
    "unees": 19, "twenty": 20, "bees": 20, "ikkis": 21, "baais": 22, "teis": 23, "chaubis": 24, "pachchis": 25,
    "pachis": 25, "chhabbis": 26, "sattais": 27, "atthais": 28, "untis": 29, "thirty": 30, "tees": 30,
    "ikatis": 31, "battis": 32, "taintis": 33, "chauntis": 34, "paintis": 35, "chhattis": 36, "saintis": 37,
    "adtis": 38, "untalis": 39, "forty": 40, "chalis": 40, "fifty": 50, "pachas": 50, "sixty": 60, "seventy": 70,
    "sattar": 70, "eighty": 80, "assi": 80, "ninety": 90, "nabbe": 90,
    # ordinals count as the number they denote ("second year" == "2nd year")
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10,
}
_MULT = {"sau": 100, "hundred": 100, "hazaar": 1000, "hazar": 1000, "thousand": 1000, "lakh": 100000, "lac": 100000,
         "lakhs": 100000, "crore": 10000000, "million": 1000000}
# "ek/do/one/two" are also articles/verbs in Hindi/English ("kar do", "one of"); count them only before a unit.
_CONTEXTUAL = {"ek", "do", "one", "two"}
_UNITS = frozenset(
    "din dinon ghante ghanta ghanta minute minutes mint hafte hafta mahine mahina saal rupaye rupees rupee rs "
    "working day days hour hours week weeks month months year years baje percent semester semesters form forms "
    "copy copies installment installments kisht seats seat times baar bar sau hazaar hazar lakh lac crore "
    "hundred thousand million".split()
)
_TOD_AM = frozenset("subah savere morning am a.m. सुबह".split())
_TOD_PM = frozenset("dopahar shaam sham raat evening afternoon night pm p.m. दोपहर शाम रात".split())
_NUM_TOKEN = re.compile(r"\d+(?::\d{2})?(?:\.\d+)?(?:st|nd|rd|th)?|[a-z\u0900-\u097F]+(?:\.[a-z](?:\.)?)?", re.I)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_COMMA_NUM = re.compile(r"(?<=\d),(?=\d{2,3}\b)")
_PLACEHOLDER = re.compile(r"\{\{.*?\}\}")
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_CURRENCY = re.compile(r"\u20b9|\brs\.?|\binr\b", re.I)


def _prep(text: str) -> str:
    t = _PLACEHOLDER.sub(" ", text or "")
    t = _URL.sub(" ", t)
    t = t.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    t = _COMMA_NUM.sub("", t)
    t = _CURRENCY.sub(" rupees ", t)
    return t.lower()


def _num_value(tok: str) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:st|nd|rd|th)?", tok)
    if m:
        v = float(m.group(1))
        return v
    return None


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def extract_facts(text: str) -> set[str]:
    """Canonical numeric/date/time facts in ``text``. See module docstring."""
    t = _prep(text)
    facts: set[str] = set()
    # numeric dates dd/mm/yyyy
    for d, m, y in _DATE_NUMERIC.findall(t):
        facts.update({f"n:{int(d)}", f"mo:{int(m)}", f"n:{int(y) if len(y) == 4 else 2000 + int(y)}"})
    t = _DATE_NUMERIC.sub(" ", t)

    toks = _NUM_TOKEN.findall(t)
    n = len(toks)
    # (index, value, mult_or_None) groups, built left to right
    groups: list[tuple[int, float, int | None, int]] = []  # (start_idx, value, mult, end_idx)
    i = 0
    while i < n:
        tok = toks[i]
        # month names
        if tok in MONTHS:
            nxt = toks[i + 1] if i + 1 < n else ""
            prv = toks[i - 1] if i > 0 else ""
            if tok not in _AMBIGUOUS_MONTHS or _num_value(nxt) is not None or _num_value(prv) is not None:
                facts.add(f"mo:{MONTHS[tok]}")
            i += 1
            continue
        # time H:MM
        if re.fullmatch(r"\d{1,2}:\d{2}", tok):
            h, mnt = tok.split(":")
            facts.add(f"t:{int(h)}:{mnt}")
            mer = _meridiem(toks, i)
            if mer:
                facts.add(f"tm:{int(h)}:{mnt}|{mer}")
            i += 1
            continue
        val = _num_value(tok)
        if val is None:
            val = _ONES.get(tok)
            if val is not None and tok in _CONTEXTUAL:
                nxt = toks[i + 1] if i + 1 < n else ""
                if nxt not in _UNITS:
                    val = None
            val = float(val) if val is not None else None
        mult = None
        j = i
        if val is None and tok in _MULT:  # bare "hazaar" == 1000
            groups.append((i, 1.0, _MULT[tok], i))
            i += 1
            continue
        if val is not None:
            # two-word tens+ones: "twenty five" / "pachas"
            if val in (20, 30, 40, 50, 60, 70, 80, 90) and tok in _ONES and i + 1 < n and toks[i + 1] in _ONES \
                    and 1 <= _ONES[toks[i + 1]] <= 9 and toks[i + 1] not in _CONTEXTUAL:
                val += _ONES[toks[i + 1]]
                j = i + 1
            if j + 1 < n and toks[j + 1] in _MULT:
                mult = _MULT[toks[j + 1]]
                j += 1
            groups.append((i, val, mult, j))
            i = j + 1
            continue
        i += 1

    # merge "2 lakh 50 hazaar" style: consecutive groups with strictly decreasing multipliers
    merged: list[tuple[int, float, int | None, int]] = []
    for g in groups:
        if merged and merged[-1][2] and g[2] and g[0] == merged[-1][3] + 1 and g[2] < merged[-1][2]:
            s, v, m, _ = merged[-1]
            merged[-1] = (s, v * m + g[1] * g[2], 1, g[3])
        elif merged and merged[-1][2] and merged[-1][2] > 100 and g[2] is None and g[0] == merged[-1][3] + 1 \
                and g[1] < merged[-1][2]:
            s, v, m, _ = merged[-1]
            merged[-1] = (s, v * m + g[1], 1, g[3])
        else:
            merged.append(g)

    for start, val, mult, end in merged:
        total = val * mult if mult else val
        facts.add(f"n:{_fmt(total)}")
        # a plain hour with a meridiem: "10 pm", "raat 10 baje"
        if mult is None and float(val).is_integer() and 1 <= val <= 12:
            mer = _meridiem(toks, start, end)
            if mer:
                facts.add(f"tm:{int(val)}|{mer}")
    return facts


def _meridiem(toks: list[str], i: int, end: int | None = None) -> str | None:
    """am/pm for the number at toks[i..end]: a following am/pm, a preceding time-of-day word ("raat 10"),
    or a time-of-day word after "baje" ("9 baje subah"). A word that belongs to the *next* time is ignored."""
    end = i if end is None else end
    nxt = toks[end + 1] if end + 1 < len(toks) else ""
    nn = toks[end + 2] if end + 2 < len(toks) else ""
    prv = toks[i - 1] if i > 0 else ""
    if nxt in ("am", "a.m."):
        return "am"
    if nxt in ("pm", "p.m."):
        return "pm"
    if prv in _TOD_AM and prv not in ("am", "a.m."):
        return "am"
    if prv in _TOD_PM and prv not in ("pm", "p.m."):
        return "pm"
    if nxt in ("baje", "oclock", "o'clock"):
        if nn in _TOD_AM:
            return "am"
        if nn in _TOD_PM:
            return "pm"
    return None


def ungrounded(spoken: set[str], source: set[str]) -> set[str]:
    """Facts in ``spoken`` that the source does not support. ``tm:`` facts only conflict with a source ``tm:``
    for the same clock time."""
    bad: set[str] = set()
    src_tm = {f.split("|")[0] for f in source if f.startswith("tm:")}
    for f in spoken:
        if f in source:
            continue
        if f.startswith("tm:"):
            if f.split("|")[0] in src_tm:  # source states a different meridiem for this time
                bad.add(f)
            continue  # source silent about this meridiem: base n:/t: fact decides
        bad.add(f)
    return bad


# --------------------------------------------------------------------------- spoken-form normalisation
_HI_DIGITS = ["shoonya", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat", "aath", "nau"]
_EN_DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_AMOUNT_TOKEN = re.compile(
    r"((?:\u20b9|\brs\.?|\binr)\s*)?(?<![\d.])(\d{1,3}(?:,\d{2,3})+|\d{4,9})(?!\d)(\s*(?:rupees?|rupaye|rs\.?|/-))?", re.I
)
_YEAR_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b")
_TIME_AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", re.I)
_MARKDOWN = re.compile(r"[*`#>]+|(?<!\w)_{1,2}|_{1,2}(?!\w)|^\s*[-•]\s+", re.M)


def amount_words(n: int, lang: str) -> str:
    """95000 -> '95 hazaar' / '95 thousand'; 150000 -> '1 lakh 50 hazaar' / '1 lakh 50 thousand'."""
    th = "hazaar" if lang != "en" else "thousand"
    parts: list[str] = []
    if n >= 10_000_000:
        parts.append(f"{n // 10_000_000} crore")
        n %= 10_000_000
    if n >= 100_000:
        parts.append(f"{n // 100_000} lakh")
        n %= 100_000
    if n >= 1000:
        parts.append(f"{n // 1000} {th}")
        n %= 1000
    if n:
        parts.append(str(n))
    return " ".join(parts) or "0"


def read_digits(s: str, lang: str = "hi") -> str:
    table = _EN_DIGITS if lang == "en" else _HI_DIGITS
    return " ".join(table[int(c)] if c.isdigit() else c for c in s)


def to_spoken(text: str, lang: str, today: date | None = None, reading_year_drops: bool = True) -> str:
    """Make text TTS-friendly: strip markdown/URLs/placeholders-free numerics, speak amounts, drop the
    current year from dates, express am/pm times naturally. ``{{ticket_id}}`` is left intact for the runtime."""
    holders: list[str] = []

    def hold(m: re.Match) -> str:  # keep {{ticket_id}} etc. untouched by every rewrite below
        holders.append(m.group(0))
        return f"\x00{len(holders) - 1}\x00"

    t = _PLACEHOLDER.sub(hold, text or "")
    t = _URL.sub("", t)
    t = _MARKDOWN.sub("", t)
    cur_year = (today or date.today()).year

    def amount(m: re.Match) -> str:
        raw = m.group(2).replace(",", "")
        has_cur = bool(m.group(1) or m.group(3))
        if "," not in m.group(2) and not has_cur:
            return m.group(0)  # plain digits without a currency marker: years, pin codes, ids
        w = amount_words(int(raw), lang)
        return w + (" rupaye" if lang != "en" else " rupees") if has_cur else w

    t = _AMOUNT_TOKEN.sub(amount, t)
    if reading_year_drops:
        t = _YEAR_RE.sub(lambda m: m.group(0) if int(m.group(3)) != cur_year else f"{m.group(1)} {m.group(2)}", t)

    if lang != "en":
        def tm(m: re.Match) -> str:
            h = m.group(1) + (f":{m.group(2)}" if m.group(2) else "")
            pm = m.group(3).lower().startswith("p")
            hour = int(m.group(1))
            word = "subah" if not pm else ("dopahar" if hour in (12, 1, 2) else "shaam" if hour in (3, 4, 5) else "raat")
            return f"{word} {h} baje"

        t = _TIME_AMPM.sub(tm, t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: holders[int(m.group(1))], t)
    return re.sub(r"\s{2,}", " ", t).strip()
