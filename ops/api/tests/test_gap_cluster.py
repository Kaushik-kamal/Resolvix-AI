"""Gap clustering: normalisation, stopwords, key/label rules and the strategy registry (pure unit tests)."""
import unicodedata

import pytest

from resolvix_ops.gaps import ClusterStrategy, KeywordClusterStrategy, get_strategy, register_strategy
from resolvix_ops.gaps.cluster import keywords, normalise, redact_phone_numbers
from resolvix_ops.gaps.service import MAX_EXAMPLES, merge_examples

S = KeywordClusterStrategy()


def assign(question, dept="accounts"):
    return S.assign(question, dept)


# ------------------------------------------------------------------ normalisation
def test_normalise_lowercases_strips_punctuation_and_collapses_space():
    assert normalise("  Hostel,   FEE?!  (2024)  ") == "hostel fee 2024"


def test_normalise_applies_nfc():
    ka_nukta = "क़"  # ka + nukta
    decomposed = unicodedata.normalize("NFD", "क़")  # precomposed qa decomposes to ka + nukta
    assert decomposed == ka_nukta
    assert normalise(decomposed) == normalise("क़") == unicodedata.normalize("NFC", ka_nukta)


def test_normalise_keeps_devanagari_words_whole():
    # matras and virama sit inside U+0900-U+097F and must not split the word
    assert normalise("छात्रावास शुल्क, कब?") == "छात्रावास शुल्क कब"
    assert normalise("परीक्षा।") == "परीक्षा"  # the danda is punctuation


def test_normalise_empty_and_symbols_only():
    assert normalise("") == ""
    assert normalise("?!... --") == ""


# ------------------------------------------------------------------ English
def test_english_keywords_and_label():
    key, label = assign("What is the hostel fee?")
    assert key == "accounts|fee|hostel"
    assert label == "Fee Hostel"


def test_english_stopwords_removed():
    assert keywords("how can I get the bus route for the college") == ["bus", "route"]
    assert "the" not in keywords("the the the exam")
    assert keywords("what is the exam date") == ["date", "exam"]


# ------------------------------------------------------------------ Devanagari
def test_devanagari_question_keeps_keywords_and_label_unchanged():
    key, label = assign("छात्रावास की फीस कब तक जमा करनी है?")
    # stopwords की/कब/तक/करनी/है removed; remaining छात्रावास, फीस, जमा -> first two by occurrence, sorted
    assert key == "accounts|छात्रावास|फीस"
    assert label == "छात्रावास फीस"


def test_devanagari_stopwords_are_removed():
    assert keywords("क्या है यह का की के में") == []


def test_devanagari_and_latin_mix():
    key, label = assign("hostel की fee कब जमा होगी")
    assert key == "accounts|fee|hostel"
    assert label == "Fee Hostel"


# ------------------------------------------------------------------ romanised Hindi
def test_romanised_hindi_stopwords_removed():
    key, label = assign("Hostel fee kab tak jama karni hai?")
    assert key == "accounts|fee|hostel"
    assert label == "Fee Hostel"


@pytest.mark.parametrize("stop", ["kya", "hai", "ka", "ki", "ke", "mein", "kaise", "kab", "kahan", "mujhe", "aap", "hum", "tak"])
def test_romanised_stopword_list_contains_the_spec_words(stop):
    assert keywords(stop) == []


def test_kab_tak_phrase_is_dropped_as_two_stopwords():
    assert keywords("kab tak") == []
    assert keywords("exam kab tak") == ["exam"]


# ------------------------------------------------------------------ order, frequency, ties
def test_word_order_does_not_change_key_or_label():
    a = assign("hostel fee kab")
    b = assign("kab fee hostel")
    c = assign("fee, hostel!")
    assert a == b == c == ("accounts|fee|hostel", "Fee Hostel")


def test_frequency_beats_first_occurrence():
    # scholarship x3, form x2, deadline x1 -> top 2 are form and scholarship
    key, _ = assign("deadline scholarship form scholarship form scholarship")
    assert key == "accounts|form|scholarship"


def test_tie_break_is_first_occurrence():
    # all frequency 1: first two seen win, then the key is sorted alphabetically
    key, label = assign("zebra apple mango")
    assert key == "accounts|apple|zebra"
    assert label == "Apple Zebra"


def test_only_two_keywords_are_used():
    assert assign("alpha beta gamma delta")[0] == "accounts|alpha|beta"


# ------------------------------------------------------------------ fewer than 2 / none
def test_one_keyword():
    key, label = assign("kya exam hai")
    assert (key, label) == ("accounts|exam", "Exam")


def test_no_keywords_gives_general():
    key, label = assign("kya hai yeh?")
    assert key == "accounts|general"
    assert label == "General"


def test_empty_question_gives_general():
    assert assign("")[0] == "accounts|general"
    assert assign("?!?")[0] == "accounts|general"


def test_single_character_tokens_are_not_keywords():
    assert keywords("a b c exam") == ["exam"]


# ------------------------------------------------------------------ department
def test_department_none_is_unknown():
    assert S.assign("hostel fee", None)[0] == "unknown|fee|hostel"
    assert S.assign("kya hai", None)[0] == "unknown|general"


def test_blank_department_is_unknown():
    assert S.assign("hostel fee", "   ")[0] == "unknown|fee|hostel"
    assert S.assign("hostel fee", "")[0] == "unknown|fee|hostel"


def test_department_set_separates_clusters_with_same_keywords():
    assert S.assign("hostel fee", "accounts")[0] == "accounts|fee|hostel"
    assert S.assign("hostel fee", "hostel")[0] == "hostel|fee|hostel"
    assert S.assign("hostel fee", "accounts")[0] != S.assign("hostel fee", None)[0]


def test_department_is_case_and_space_insensitive():
    assert S.assign("hostel fee", " Accounts ") == S.assign("hostel fee", "accounts")


def test_deterministic():
    assert [assign("Noida sector 62 bus route") for _ in range(3)] == [assign("Noida sector 62 bus route")] * 3


# ------------------------------------------------------------------ registry
def test_default_strategy_is_keywords():
    assert isinstance(get_strategy("keywords"), KeywordClusterStrategy)
    assert isinstance(get_strategy("KEYWORDS "), KeywordClusterStrategy)


def test_unknown_strategy_falls_back_to_keywords(caplog):
    assert isinstance(get_strategy("embeddings-not-installed"), KeywordClusterStrategy)
    assert "falling back" in caplog.text
    assert isinstance(get_strategy(None), KeywordClusterStrategy)


def test_custom_strategy_can_be_registered():
    class Constant(ClusterStrategy):
        name = "constant-test"

        def assign(self, question, department_guess):
            return "k", "L"

    register_strategy("constant-test", Constant)
    assert get_strategy("constant-test").assign("anything", None) == ("k", "L")


# ------------------------------------------------------------------ examples helper
def test_merge_examples_caps_at_five_newest_last():
    examples = []
    for i in range(8):
        examples = merge_examples(examples, f"q{i}")
    assert MAX_EXAMPLES == 5
    assert examples == ["q3", "q4", "q5", "q6", "q7"]


def test_merge_examples_dedupes_identical_text_moving_it_to_the_end():
    assert merge_examples(["a", "b", "c"], "a") == ["b", "c", "a"]
    assert merge_examples(["a"], "a") == ["a"]


# ------------------------------------------------------------------ phone number redaction
@pytest.mark.parametrize("text", [
    "call +919000000001 please", "call 9000000001 please", "call +91 90000 00001 please",
    "call 90000-00001 please", "call (+91) 9000 000 001 please"])
def test_phone_numbers_are_redacted(text):
    out = redact_phone_numbers(text)
    assert "9000" not in out and "•••" in out
    assert "9000" not in "".join(assign(out))


def test_short_digit_runs_are_not_phone_numbers():
    assert redact_phone_numbers("fee 2023 2024 2025") == "fee 2023 2024 2025"
    assert redact_phone_numbers("sector 62 bus") == "sector 62 bus"
    assert redact_phone_numbers("") == ""
