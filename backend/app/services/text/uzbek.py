"""Oʻzbek tili (lotin) uchun yordamchi funksiyalar.

- apostroflarni unifikatsiya (oʻ, gʻ — U+02BB; tutuq belgisi — U+02BC)
- kirill → lotin transliteratsiya
- boʻgʻin sanash (oʻzbek, ingliz, rus va boshqa tillar uchun taxminiy)
- raqamlarni soʻz bilan yozish (miqdor va tartib son)
- qisqartmalarni harflab oʻqish
"""
from __future__ import annotations

import re

OKINA = "ʻ"  # ʻ  (oʻ, gʻ)
TUTUQ = "ʼ"  # ʼ  (tutuq belgisi: maʼno)

_APOSTROPHES = "'`‘’ʻʼ´"

# --------------------------------------------------------------------------- apostroflar


def normalize_apostrophes(text: str) -> str:
    """oʻ/gʻ dan keyin U+02BB, boshqa joyda U+02BC qoʻyadi."""
    text = re.sub(rf"([oOgG])[{_APOSTROPHES}]", lambda m: m.group(1) + OKINA, text)
    text = re.sub(rf"(?<=[A-Za-z{OKINA}])[{_APOSTROPHES.replace(OKINA, '')}](?=[A-Za-z])", TUTUQ, text)
    return text


# --------------------------------------------------------------------------- kirill → lotin

_CYR_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sh", "ъ": TUTUQ, "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o" + OKINA, "қ": "q", "ғ": "g" + OKINA, "ҳ": "h",
}
_CYR_VOWELS = set("аеёиоуэюяў")


def cyrillic_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "Ѐ" <= c <= "ӿ") / len(letters)


def cyrillic_to_latin(text: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(text):
        low = ch.lower()
        if low == "е":
            prev = text[i - 1].lower() if i > 0 else ""
            # soʻz boshida yoki unlidan keyin "ye"
            lat = "ye" if (not prev.isalpha() or prev in _CYR_VOWELS or prev in "ъь") else "e"
        elif low in _CYR_MAP:
            lat = _CYR_MAP[low]
        else:
            out.append(ch)
            continue
        if ch.isupper() and lat:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            lat = lat.upper() if (nxt.isupper() and len(lat) > 1) else lat[0].upper() + lat[1:]
        out.append(lat)
    return "".join(out)


# --------------------------------------------------------------------------- boʻgʻinlar

_UZ_VOWELS = "aeiouAEIOU"
_RU_VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"


def count_syllables_uz(text: str) -> int:
    """Oʻzbek tilida har bir unli = bitta boʻgʻin (oʻ ham bitta unli)."""
    text = normalize_apostrophes(text)
    count = sum(1 for c in text if c in _UZ_VOWELS)
    count += _count_numbers_syllables(text)
    return count


def _count_numbers_syllables(text: str) -> int:
    total = 0
    for num in re.findall(r"\d+", text):
        if len(num) <= 12:
            total += sum(1 for c in number_to_words(int(num)) if c in _UZ_VOWELS)
    return total


def count_syllables_en(text: str) -> int:
    total = 0
    for word in re.findall(r"[A-Za-z]+", text):
        w = word.lower()
        groups = re.findall(r"[aeiouy]+", w)
        n = len(groups)
        if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
            n -= 1
        if w.endswith("ed") and not w.endswith(("ted", "ded")) and n > 1:
            n -= 1
        total += max(1, n)
    for num in re.findall(r"\d+", text):
        total += max(1, len(num))
    return total


def count_syllables(text: str, language: str) -> int:
    lang = (language or "").lower()[:2]
    if lang == "uz":
        return count_syllables_uz(text)
    if lang == "en":
        return count_syllables_en(text)
    if lang in {"ru", "uk", "be", "kk", "ky", "tg"}:
        return max(1, sum(1 for c in text if c in _RU_VOWELS)) if text.strip() else 0
    # Boshqa tillar: unli harflar guruhlari (lotin + kirill)
    groups = re.findall(r"[aeiouyAEIOUYàáâäèéêëìíîïòóôöùúûüаеёиоуыэюя]+", text)
    return len(groups)


# --------------------------------------------------------------------------- raqamlar

_ONES = ["nol", "bir", "ikki", "uch", "to" + OKINA + "rt", "besh", "olti", "yetti", "sakkiz",
         "to" + OKINA + "qqiz"]
_TENS = ["", "o" + OKINA + "n", "yigirma", "o" + OKINA + "ttiz", "qirq", "ellik", "oltmish",
         "yetmish", "sakson", "to" + OKINA + "qson"]
_SCALES = [(10**12, "trillion"), (10**9, "milliard"), (10**6, "million"), (1000, "ming")]


def _below_thousand(n: int) -> list[str]:
    words: list[str] = []
    h, rest = divmod(n, 100)
    if h:
        words += [_ONES[h], "yuz"]
    t, o = divmod(rest, 10)
    if t:
        words.append(_TENS[t])
    if o:
        words.append(_ONES[o])
    return words


def number_to_words(n: int) -> str:
    if n == 0:
        return _ONES[0]
    if n < 0:
        return "minus " + number_to_words(-n)
    words: list[str] = []
    for value, name in _SCALES:
        if n >= value:
            q, n = divmod(n, value)
            words += _below_thousand(q) + [name]
    words += _below_thousand(n)
    return " ".join(words)


def ordinal_to_words(n: int) -> str:
    base = number_to_words(n)
    return base + ("nchi" if base[-1] in "aeiou" else "inchi")


def decimal_to_words(integer: str, fraction: str) -> str:
    return f"{number_to_words(int(integer))} butun {number_to_words(int(fraction))}"


# --------------------------------------------------------------------------- qisqartmalar

_LETTER_NAMES = {
    "A": "a", "B": "be", "D": "de", "E": "e", "F": "ef", "G": "ge", "H": "ha", "I": "i",
    "J": "je", "K": "ka", "L": "el", "M": "em", "N": "en", "O": "o", "P": "pe", "Q": "qu",
    "R": "er", "S": "es", "T": "te", "U": "u", "V": "ve", "X": "xa", "Y": "ye", "Z": "ze",
    "C": "se", "W": "dabl-yu",
    "O" + OKINA: "o" + OKINA, "G" + OKINA: "g" + OKINA + "e", "SH": "sha", "CH": "che",
}


def spell_abbreviation(abbr: str) -> str:
    """BMT → be-em-te, AQSh → a-qu-sha."""
    abbr = normalize_apostrophes(abbr)
    parts: list[str] = []
    i = 0
    while i < len(abbr):
        two = abbr[i : i + 2].upper()
        if two in _LETTER_NAMES and (two in ("SH", "CH") or two.endswith(OKINA)):
            parts.append(_LETTER_NAMES[two])
            i += 2
            continue
        ch = abbr[i].upper()
        if ch in _LETTER_NAMES:
            parts.append(_LETTER_NAMES[ch])
        i += 1
    return "-".join(parts)
