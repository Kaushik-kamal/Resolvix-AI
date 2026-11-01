"""Gap clustering strategies.

A strategy maps one unanswered question (plus the runtime's department guess) to a stable
cluster key and a human label. The default `keywords` strategy is deterministic and needs no
network: normalise, drop English/Hindi stopwords, take the 2 most frequent keywords.

Other strategies (embedding based, P1) plug in behind the same interface and are selected by
the `gap_cluster_strategy` setting through `get_strategy`.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from abc import ABC, abstractmethod
from collections import Counter

log = logging.getLogger(__name__)

UNKNOWN_DEPARTMENT = "unknown"
GENERAL_KEYWORD = "general"
GENERAL_LABEL = "General"
TOP_KEYWORDS = 2

# Everything that is not a latin letter, a digit or a Devanagari code point becomes a space.
# Devanagari is listed explicitly (U+0900-U+097F) so vowel signs and viramas stay inside words;
# the danda (U+0964) and double danda (U+0965) are punctuation and are removed first.
_DANDAS = re.compile("[।॥]")
_NOT_WORD = re.compile("[^a-z0-9ऀ-ॿ]+")
_DEVANAGARI = re.compile("[ऀ-ॿ]")

ENGLISH_STOPWORDS = frozenset("""
a an the and or but if so than then that this these those there here it its is are was were be been being am
do does did done doing have has had having will would shall should can could may might must
i me my mine we us our ours you your yours he him his she her hers they them their theirs
what which who whom whose when where why how whether
to of in on at by for with without from into onto about as up down out over under again also too very just
not no nor yes any some all each every both few more most other such only own same
please pls plz kindly tell told know want wanted need needed get got give help hello hi hey sir madam mam
ok okay thanks thank regards
""".split())

ROMANISED_HINDI_STOPWORDS = frozenset("""
kya hai hain ho hoga hogi honge hota hoti hote tha thi the hua hui hue
ka ki ke ko mein me main se par pe per tak liye lie
aur ya bhi to toh hi ji na nahi nahin
kaise kaisa kaisi kab kahan kaha kahaan kaun kon kyun kyu kyon kitna kitni kitne kidhar
mujhe mujhko mera meri mere hum humein hume humko hamara hamari hamare aap aapka aapki aapke tum tumhara tumhari
ye yeh wo woh is us isse usse isko usko yahan wahan
bata batao batana bataiye bataye batayiye chahiye chahta chahti chahte
kar karna karni karne karo kare kijiye kijie karein karen
do dena dijiye de diya
sakta sakti sakte raha rahi rahe rha rhi
jo jab abhi kuch koi sab wala wali wale
""".split())

DEVANAGARI_STOPWORDS = frozenset("""
का की के को में मैं से पर और या भी तो क्या है हैं हो होगा होगी होंगे होता होती होते था थी थे हुआ हुई हुए
कैसे कैसा कैसी कब कहाँ कहां कौन क्यों क्यूँ कितना कितनी कितने किधर
मुझे मुझको मेरा मेरी मेरे हम हमें हमको हमारा हमारी हमारे आप आपका आपकी आपके तुम तुम्हारा तुम्हारी
ये यह वो वह इस उस इसे उसे इसको उसको यहाँ यहां वहाँ वहां
लिए तक बता बताओ बताइए बताएं बताना चाहिए चाहता चाहती चाहते
कर करना करनी करने करो करें करे कीजिए
दो देना दीजिए दे दिया
सकता सकती सकते रहा रही रहे
जो जब अभी कुछ कोई सब वाला वाली वाले
नहीं नही न जी
""".split())

STOPWORDS = ENGLISH_STOPWORDS | ROMANISED_HINDI_STOPWORDS | DEVANAGARI_STOPWORDS


_PHONE_LIKE = re.compile(r"\+?\d[\d \-()]{8,}\d")
_YEAR = re.compile(r"(?:19|20)\d\d")
PHONE_PLACEHOLDER = "•••"


def redact_phone_numbers(text: str) -> str:
    """Replace phone-number-like digit runs (10 or more digits, spaces/hyphens/brackets allowed) with bullets.

    Callers sometimes say their number inside the question. It must never become a cluster label,
    an example shown on the dashboard or part of an SSE payload.
    """
    def repl(match: re.Match) -> str:
        run = match.group(0)
        if sum(ch.isdigit() for ch in run) < 10:
            return run
        groups = re.findall(r"\d+", run)
        if all(_YEAR.fullmatch(g) for g in groups):  # "fee 2023 2024 2025" is a list of years
            return run
        return PHONE_PLACEHOLDER

    return _PHONE_LIKE.sub(repl, text or "")


def normalise(text: str) -> str:
    """NFC, lowercase, punctuation removed, whitespace collapsed. Devanagari is kept."""
    text = unicodedata.normalize("NFC", text or "").lower()
    text = _DANDAS.sub(" ", text)
    text = _NOT_WORD.sub(" ", text)
    return " ".join(text.split())


def keywords(text: str, limit: int = TOP_KEYWORDS) -> list[str]:
    """Top `limit` non-stopword tokens by frequency (ties: first occurrence), sorted alphabetically.

    Single-character tokens carry no topic and are dropped together with the stopwords.
    """
    tokens = [t for t in normalise(text).split() if len(t) > 1 and t not in STOPWORDS]
    counts = Counter(tokens)
    first_seen: dict[str, int] = {}
    for position, token in enumerate(tokens):
        first_seen.setdefault(token, position)
    ranked = sorted(counts, key=lambda t: (-counts[t], first_seen[t]))
    return sorted(ranked[:limit])


def title_case(keyword: str) -> str:
    """Capitalise latin keywords; Devanagari (and anything with a Devanagari letter) is unchanged."""
    if _DEVANAGARI.search(keyword):
        return keyword
    return keyword.capitalize()


def department_part(department_guess: str | None) -> str:
    cleaned = (department_guess or "").strip().lower()
    return cleaned or UNKNOWN_DEPARTMENT


class ClusterStrategy(ABC):
    """assign(question, department_guess) -> (cluster key, label). Must be deterministic and cheap."""

    name = "base"

    @abstractmethod
    def assign(self, question: str, department_guess: str | None) -> tuple[str, str]:
        ...


class KeywordClusterStrategy(ClusterStrategy):
    """key = '<department|unknown>|<kw1>|<kw2>' (keywords sorted), label = keywords title-cased."""

    name = "keywords"

    def assign(self, question: str, department_guess: str | None) -> tuple[str, str]:
        dept = department_part(department_guess)
        words = keywords(question)
        if not words:
            return f"{dept}|{GENERAL_KEYWORD}", GENERAL_LABEL
        return f"{dept}|{'|'.join(words)}", " ".join(title_case(w) for w in words)


_STRATEGIES: dict[str, type[ClusterStrategy]] = {KeywordClusterStrategy.name: KeywordClusterStrategy}


def register_strategy(name: str, strategy_cls: type[ClusterStrategy]) -> None:
    """Make a strategy selectable through the gap_cluster_strategy setting."""
    _STRATEGIES[name] = strategy_cls


_INSTANCES: dict[tuple, ClusterStrategy] = {}  # strategies that keep state (embedding centroids) live per configuration


def get_strategy(name: str | None, settings=None) -> ClusterStrategy:
    """Instantiate the named strategy; an unknown name falls back to keywords (with a warning).

    "embedding" needs settings.embedding_api_key; without it the keyword strategy is used (BLOCKERS.md).
    """
    wanted = (name or "").strip().lower()
    if wanted == "embedding":
        from .embedding import EmbeddingClusterStrategy
        cache_key = (wanted, getattr(settings, "embedding_api_url", None), getattr(settings, "embedding_model", None),
                     bool(getattr(settings, "embedding_api_key", "")))
        if cache_key not in _INSTANCES:
            strategy = EmbeddingClusterStrategy.from_settings(settings) if settings is not None else None
            if strategy is None:
                log.warning("gap_cluster_strategy=embedding but EMBEDDING_API_KEY is not set; using 'keywords'")
                strategy = KeywordClusterStrategy()
            _INSTANCES[cache_key] = strategy
        return _INSTANCES[cache_key]
    cls = _STRATEGIES.get(wanted)
    if cls is None:
        log.warning("Unknown gap_cluster_strategy %r, falling back to 'keywords'", name)
        cls = KeywordClusterStrategy
    return cls()
