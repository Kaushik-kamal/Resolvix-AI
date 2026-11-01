"""Text helpers shared by safety, rules, flows and validators: normalisation, redaction, language/script
detection, yes/no parsing, phone/roll-number extraction.

Everything here is pure and fast (the safety path calls ``normalize`` on every turn and must stay < 5 ms).
"""
from __future__ import annotations

import re
import unicodedata

from resolvix_contracts.models import Lang

_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
# keep word chars, whitespace, Devanagari block (letters AND matras/virama, which are not \w) and ascii digits
_NON_WORD = re.compile(r"[^\w\sऀ-ॣ०-ॿ]", re.UNICODE)
_WS = re.compile(r"\s+")
_DEVA = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")


def normalize(text: str) -> str:
    """NFC, lower-case, Devanagari digits -> ASCII, punctuation/danda removed, whitespace collapsed."""
    t = unicodedata.normalize("NFC", text or "")
    t = t.translate(_ZERO_WIDTH).translate(_DEVA_DIGITS).lower()
    t = _NON_WORD.sub(" ", t.replace("_", " "))
    return _WS.sub(" ", t).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


# ------------------------------------------------------------------ redaction
_LONG_DIGITS = re.compile(r"(?<![\d])\+?\d(?:[\s\-]?\d){9,}(?![\d])")


def redact(text: str) -> str:
    """Mask phone and roll numbers (any run of >= 10 digits, optionally spaced or hyphenated)."""
    return _LONG_DIGITS.sub("[REDACTED]", (text or "").translate(_DEVA_DIGITS))


# ------------------------------------------------------------------ phone / roll extraction
_DIGIT_WORDS = {
    "zero": "0", "shunya": "0", "shoonya": "0", "sifar": "0", "one": "1", "ek": "1", "two": "2", "do": "2",
    "three": "3", "teen": "3", "four": "4", "char": "4", "chaar": "4", "five": "5", "panch": "5", "paanch": "5",
    "six": "6", "chhe": "6", "chhah": "6", "che": "6", "seven": "7", "saat": "7", "eight": "8", "aath": "8",
    "nine": "9", "nau": "9", "oh": "0",
}


def digit_runs(text: str) -> list[str]:
    """Runs of *adjacent* digits in the text, in order. Plain digit tokens ("98765 43210") and digit words
    ("nine eight seven ...", only inside a run of >= 3 words so "do din"/"ek baar" never count) are joined;
    any other word ends a run, so "10 minute ... 2400271549999" stays two separate runs."""
    runs: list[str] = []
    cur: list[str] = []
    words: list[str] = []

    def flush_words() -> None:
        nonlocal words
        if len(words) >= 3:
            cur.extend(_DIGIT_WORDS[w] for w in words)
        words = []

    def flush_run() -> None:
        nonlocal cur
        flush_words()
        if cur:
            runs.append("".join(cur))
        cur = []

    for tok in normalize(text).split():
        if tok.isdigit():
            flush_words()
            cur.append(tok)
        elif tok in _DIGIT_WORDS:
            words.append(tok)
        else:
            flush_run()
    flush_run()
    return runs


def digits_from_speech(text: str) -> str:
    """All digit runs joined (kept for callers that want every digit); prefer ``digit_runs``."""
    return "".join(digit_runs(text))


def extract_roll_number(text: str) -> str | None:
    """Roll number = a run of 10-13 digits (PRD 5.2)."""
    for run in digit_runs(text):
        if 10 <= len(run) <= 13:
            return run
    return None


def extract_phone(text: str) -> str | None:
    """Indian mobile number: optional 0/91/+91 prefix then 10 digits starting 6-9. Returns E.164 (+91...)."""
    for run in digit_runs(text):
        m = re.fullmatch(r"(?:91|0)?([6-9]\d{9})", run)
        if m:
            return "+91" + m.group(1)
    return None


def last4_spoken(number: str | None) -> str:
    return (number or "")[-4:]


# ------------------------------------------------------------------ language / script
_HI_ROMAN = frozenset(
    "hai hain hoon ho hota hoti hote hoga hogi honge tha thi ka ki ke ko se mein par pe nahi nahin na kya "
    "kab kaise kaisi kitna kitni kitne kahan kaun kyun kyu kaha mujhe mera meri mere main mai aap aapka aapki "
    "aapke hum humara ye yeh wo woh vo bhi aur ya tak liye lie raha rahi rahe chahiye chahta chahti karna karni "
    "karne karein kare kar karo batao bataiye batayiye bataye batana haan han ji jee abhi kal aaj bahut bohot "
    "thoda zyada sirf phir fir bas toh lekin magar kuch koi sab kisi unka unki unke iska iski iske uska uski "
    "uske mil milega milegi milta milti diya dena dijiye dijiye jaana jana jayega jayegi gaya gayi gaye "
    "wala wali wale sakta sakti sakte lagta lagti padta padti hamara apna apni apne dono ek yahan wahan kaise "
    "kyunki isliye jab tab agar ab".split()
)
_EN_FUNC = frozenset(
    "the is are was were be been what when where how why which who do does did can could will would should may "
    "i my me you your we our it its this that these those for of to in on at by with and or but not no yes please "
    "thanks thank hello hi need want know tell about from there their have has had a an if so also any".split()
)


def script_of(text: str) -> str:
    """'deva' if the text is mostly Devanagari letters, else 'roman'."""
    d = len(_DEVA.findall(text or ""))
    l = len(_LATIN.findall(text or ""))
    return "deva" if d > l and d > 0 else "roman"


def detect_lang(text: str) -> Lang | None:
    """Heuristic language of one utterance. None when there is too little signal (keep the session language).

    Devanagari -> hi. Romanised Hindi markers with English function words -> hinglish; without -> hi.
    No Hindi markers -> en.
    """
    toks = [t for t in tokens(text) if not t.isdigit()]
    if not toks:
        return None
    if script_of(text) == "deva":
        return Lang.hi
    hi = sum(t in _HI_ROMAN for t in toks)
    en = sum(t in _EN_FUNC for t in toks)
    if hi == 0 and en < 2 and len(toks) < 6:
        return None  # too little evidence to switch language (names, rooms, "roll number ... paper ...")
    if hi == 0 and en == 0:
        return Lang.en
    if hi == 0:
        return Lang.en
    if en > 0:
        return Lang.hinglish
    return Lang.hi


def reply_lang(lang: Lang | str) -> str:
    """Language bucket for fixed lines: 'en' or 'hi' (hi covers hi and hinglish)."""
    return "en" if str(getattr(lang, "value", lang)) == "en" else "hi"


# ------------------------------------------------------------------ yes / no
_YES = frozenset(
    "haan han ha haa ji jee yes yeah yep yup sahi theek thik correct right ok okay bilkul sure hanji haanji isi karo kardo kijiye "
    "हाँ हां हा जी सही ठीक बिलकुल जरूर".split()
)
_NO = frozenset("nahi nahin nahi no nope galat na wrong नहीं नही ना गलत".split())


def yes_no(text: str) -> bool | None:
    """True/False for an affirmative/negative reply, None when neither (or only filler)."""
    toks = set(tokens(text))
    if toks & _NO:
        return False
    if toks & _YES:
        return True
    return None


# ------------------------------------------------------------------ misc
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+(?=[A-Zऀ-ॿ\"'(\d])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split((text or "").strip())]
    return [p for p in parts if p]


def word_count(text: str) -> int:
    return len(tokens(text))
