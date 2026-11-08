from app.services.text.lexicon import LexiconEntry, apply_lexicon, find_foreign_terms, transliterate_foreign
from app.services.text.normalizer import normalize_for_tts
from app.services.text.pauses import (
    CHAPTER_END_MS,
    ELLIPSIS_MS,
    PARAGRAPH_MS,
    block_pause_after,
    detect_intonation,
    render_inline_pauses_ssml,
)
from app.services.text.uzbek import (
    count_syllables,
    count_syllables_uz,
    cyrillic_to_latin,
    normalize_apostrophes,
    number_to_words,
    ordinal_to_words,
    spell_abbreviation,
)


def test_numbers():
    assert number_to_words(0) == "nol"
    assert number_to_words(1991) == "bir ming toʻqqiz yuz toʻqson bir"
    assert number_to_words(2_000_015) == "ikki million oʻn besh"
    assert ordinal_to_words(1) == "birinchi"
    assert ordinal_to_words(2) == "ikkinchi"
    assert ordinal_to_words(20) == "yigirmanchi"


def test_apostrophes_and_cyrillic():
    assert normalize_apostrophes("o'g'il ma'no") == "oʻgʻil maʼno"
    assert cyrillic_to_latin("Ўзбекистон") == "Oʻzbekiston"
    assert cyrillic_to_latin("ШАҲАР") == "SHAHAR"
    assert cyrillic_to_latin("ер, келди") == "yer, keldi"


def test_syllables():
    assert count_syllables_uz("Oʻzbekiston") == 4
    assert count_syllables_uz("Salom dunyo") == 4
    assert count_syllables("Hello world, this is a test", "en") == 7
    assert count_syllables("Привет мир", "ru") == 3


def test_abbreviations():
    assert spell_abbreviation("AQSh") == "a-qu-sha"
    assert spell_abbreviation("BMT") == "be-em-te"


def test_normalize_for_tts():
    out = normalize_for_tts("1991-yil 5-bobda AQSh, soat 14:30da, 50% va $25.")
    assert out == ("bir ming toʻqqiz yuz toʻqson birinchi yil beshinchi bobda a-qu-sha, "
                   "soat oʻn toʻrt oʻttizda, ellik foiz va yigirma besh dollar.")
    assert normalize_for_tts("XII bob") == "oʻn ikkinchi bob"
    assert normalize_for_tts("- Salom, - dedi u...") == "— Salom, — dedi u…"


def test_lexicon_suffix_and_case():
    entries = [LexiconEntry("Shakespeare", "Shekspir", 2), LexiconEntry("Google", "gugl", 2),
               LexiconEntry("New York", "Nyu-York", 2)]
    text = "Shakespeare'ning asarlari Google'da. google qidiruvi. New York."
    assert apply_lexicon(text, entries) == "Shekspirning asarlari Guglda. gugl qidiruvi. Nyu-York."


def test_lexicon_priority():
    entries = [LexiconEntry("Harry", "Garri", 2), LexiconEntry("harry", "Xarri", 3)]
    assert apply_lexicon("Harry keldi", entries) == "Xarri keldi"


def test_foreign_detection_ignores_uzbek():
    terms = find_foreign_terms("Quyosh xos kun. Washington va Thompson bilan oʻqidik. Cambridge.")
    assert terms == ["Washington", "Thompson", "Cambridge"]
    assert transliterate_foreign("Thompson") == "Tompson"
    assert transliterate_foreign("Washington") == "Vashington"


def test_pauses_and_intonation():
    assert block_pause_after("Salom.", is_paragraph_end=True) == PARAGRAPH_MS
    assert block_pause_after("Shunday…", is_paragraph_end=False) == ELLIPSIS_MS
    assert block_pause_after("Tamom.", is_paragraph_end=True, is_chapter_end=True) == CHAPTER_END_MS
    assert detect_intonation("Kelasizmi?").contour == "rising"
    assert detect_intonation("Qoching!").emotion == "excited"
    assert detect_intonation("Bilmadim…").contour == "trailing"
    assert '<break time="0.7s" />' in render_inline_pauses_ssml("Bilmadim… balki")
