"""TTS uchun matnni normallashtirish (oʻzbek, lotin)."""
from __future__ import annotations

import re
import unicodedata

from app.services.text.uzbek import (
    cyrillic_ratio,
    cyrillic_to_latin,
    decimal_to_words,
    normalize_apostrophes,
    number_to_words,
    ordinal_to_words,
    spell_abbreviation,
)

# Talaffuz qilinmaydigan, lekin keng tarqalgan qisqartmalar
_EXPANSIONS = {
    r"\bva h\.k\.": "va hokazo",
    r"\bva b\.": "va boshqalar",
    r"\bm\.": "metr",
    r"\bkm\b": "kilometr",
    r"\bkg\b": "kilogramm",
    r"\bsm\b": "santimetr",
    r"\bmm\b": "millimetr",
    r"\bt\.y\.": "tugʻilgan yili",
    r"\bmil\. avv\.": "miloddan avvalgi",
    r"\bprof\.": "professor",
    r"\bdots\.": "dotsent",
    r"\bsh\.": "shahri",
    r"\bkoʻch\.": "koʻchasi",
}

# Soʻz qisqartmasi emas, balki toʻgʻridan-toʻgʻri soʻz sifatida oʻqiladiganlar
_READ_AS_WORD = {"NATO", "UNESCO", "UNICEF", "OPEK", "NASA", "FIFA", "UEFA"}

_UZ_UPPER = "A-ZOʻGʻ"


def normalize_punctuation(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("​", "")
    text = re.sub(r"\.{3,}", "…", text)
    # Tirelar: dialog va oraliq tire — em dash
    text = re.sub(r"(^|\n)[ \t]*[-–―][ \t]+", r"\1— ", text)
    text = re.sub(r"[ \t]+[-–―][ \t]+", " — ", text)
    # Tirnoqlar → « »
    text = re.sub(r"[“„\"](?=\S)", "«", text)
    text = re.sub(r"(?<=\S)[”\"]", "»", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def expand_numbers(text: str) -> str:
    # Foiz
    text = re.sub(r"(\d+)[,.](\d+)\s?%", lambda m: decimal_to_words(m[1], m[2]) + " foiz", text)
    text = re.sub(r"(\d+)\s?%", lambda m: number_to_words(int(m[1])) + " foiz", text)
    # Tartib son: "1991-yil", "5-bob", "3-sinf"
    text = re.sub(r"\b(\d+)-(?=[a-zA-ZʻʼoʻgʻOʻGʻ])", lambda m: ordinal_to_words(int(m[1])) + " ", text)
    # Vaqt 14:30
    text = re.sub(
        r"(?:\b[Ss]oat\s+)?\b(\d{1,2}):(\d{2})(?!\d)",
        lambda m: f"soat {number_to_words(int(m[1]))}" + (f" {number_to_words(int(m[2]))}" if int(m[2]) else ""),
        text,
    )
    # Oʻnli kasr
    text = re.sub(r"\b(\d+),(\d+)(?!\d)", lambda m: decimal_to_words(m[1], m[2]), text)
    # Minglik ajratgichlar: 1 000 000 yoki 1.000.000
    text = re.sub(r"\b\d{1,3}(?:[ .]\d{3})+\b", lambda m: re.sub(r"[ .]", "", m[0]), text)
    # Valyuta
    text = re.sub(r"\$\s?(\d+)", lambda m: number_to_words(int(m[1])) + " dollar", text)
    text = re.sub(r"(\d+)\s?\$", lambda m: number_to_words(int(m[1])) + " dollar", text)
    text = re.sub(r"€\s?(\d+)", lambda m: number_to_words(int(m[1])) + " yevro", text)
    # Qolgan butun sonlar
    text = re.sub(r"(?<![\w])\d{1,15}(?!\d)", lambda m: number_to_words(int(m[0])), text)
    return text


def _roman_to_int(s: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total, prev = 0, 0
    for ch in reversed(s):
        v = values.get(ch, 0)
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def expand_roman_numerals(text: str) -> str:
    """ "XII bob" → "oʻn ikkinchi bob" (faqat bob/qism/fasl/asr/jild oldidan)."""
    return re.sub(
        r"\b([IVXLC]{1,6})(?=\s+(?:bob|qism|fasl|asr|jild|kitob)\b)",
        lambda m: ordinal_to_words(_roman_to_int(m[1])) if _roman_to_int(m[1]) else m[1],
        text,
    )


def expand_abbreviations(text: str) -> str:
    for pattern, repl in _EXPANSIONS.items():
        text = re.sub(pattern, repl, text)

    def _abbr(m: re.Match) -> str:
        word = m[0]
        if sum(1 for c in word if c.isupper()) < 2:
            return word
        if word in _READ_AS_WORD:
            return word.capitalize()
        return spell_abbreviation(word)

    # 2–6 harfli bosh harfli qisqartmalar (AQSh, BMT, OAV, IIV)
    return re.sub(rf"\b[{_UZ_UPPER}](?:[{_UZ_UPPER}]|[{_UZ_UPPER}]?h){{1,5}}\b", _abbr, text)


def normalize_for_tts(text: str) -> str:
    """Toʻliq normallashtirish: kirill→lotin, apostroflar, tinish belgilari, raqam va qisqartmalar."""
    if cyrillic_ratio(text) > 0.5:
        text = cyrillic_to_latin(text)
    text = normalize_apostrophes(text)
    text = normalize_punctuation(text)
    text = expand_roman_numerals(text)
    text = expand_abbreviations(text)
    text = expand_numbers(text)
    return text
