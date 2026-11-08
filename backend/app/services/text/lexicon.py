"""Xorijiy soʻzlar va nomlar uchun talaffuz leksikoni.

Ustuvorlik: loyiha (USER) → global (GLOBAL) → avtomatik taklif (AUTO_SUGGESTED).
Almashtirish faqat TTS matnida bajariladi; oʻzbek qoʻshimchalari saqlanadi:
  "Shakespeare'ning" → "Shekspirning", "Google'da" → "Guglda".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.text.uzbek import OKINA, TUTUQ

_APOS = "'’ʼ`"
_WORD_CHARS = "A-Za-z0-9" + OKINA + TUTUQ + "À-ÿ"


@dataclass(frozen=True)
class LexiconEntry:
    term: str
    phonetic_uz: str
    priority: int = 0  # katta = ustuvorroq (USER=3, GLOBAL=2, AUTO=1)


def merge_entries(*groups: list[LexiconEntry]) -> dict[str, LexiconEntry]:
    merged: dict[str, LexiconEntry] = {}
    for group in groups:
        for e in group:
            key = e.term.lower()
            if key not in merged or e.priority >= merged[key].priority:
                merged[key] = e
    return merged


def _match_case(original: str, replacement: str) -> str:
    if original[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_lexicon(text: str, entries: dict[str, LexiconEntry] | list[LexiconEntry]) -> str:
    if isinstance(entries, list):
        entries = merge_entries(entries)
    if not entries or not text:
        return text
    terms = sorted(entries.values(), key=lambda e: len(e.term), reverse=True)
    alternation = "|".join(re.escape(e.term) for e in terms)
    pattern = re.compile(
        rf"(?<![{_WORD_CHARS}])({alternation})(?:[{_APOS}]([a-z{OKINA}]+))?(?![{_WORD_CHARS}])",
        re.IGNORECASE,
    )

    def repl(m: re.Match) -> str:
        entry = entries[m[1].lower()]
        out = _match_case(m[1], entry.phonetic_uz)
        if m[2]:
            out += m[2]  # oʻzbek qoʻshimchasi apostrofsiz qoʻshiladi
        return out

    return pattern.sub(repl, text)


# ------------------------------------------------------------- xorijiy soʻzlarni aniqlash

# Oʻzbek lotin alifbosida uchramaydigan harf birikmalari
_FOREIGN_MARKERS = re.compile(
    r"w|c(?!h)|th|ph|ck|ee|oo|ou|gh|tion|[àáâäãåèéêëìíîïòóôöõùúûüçñßøæœ]",
    re.IGNORECASE,
)
_TOKEN = re.compile(rf"[{_WORD_CHARS}]+")


def is_probably_foreign(word: str) -> bool:
    if len(word) < 3 or not re.search(r"[A-Za-zÀ-ÿ]", word):
        return False
    if OKINA in word:
        return False  # oʻ / gʻ — oʻzbekcha
    return bool(_FOREIGN_MARKERS.search(word))


def find_foreign_terms(text: str, known: set[str] | None = None) -> list[str]:
    known = {k.lower() for k in (known or set())}
    seen: dict[str, str] = {}
    for token in _TOKEN.findall(text):
        base = re.split(rf"[{_APOS}]", token)[0]
        if is_probably_foreign(base) and base.lower() not in known:
            seen.setdefault(base.lower(), base)
    return list(seen.values())


_TRANSLIT_RULES: list[tuple[str, str]] = [
    (r"tion", "shn"),
    (r"sch", "sh"),
    (r"ough", "o"),
    (r"augh", "o"),
    (r"igh", "ay"),
    (r"th", "s"),
    (r"ph", "f"),
    (r"ck", "k"),
    (r"gh", "g"),
    (r"qu", "kv"),
    (r"ee", "i"),
    (r"ea", "i"),
    (r"oo", "u"),
    (r"ou", "au"),
    (r"ay", "ey"),
    (r"c(?=[eiy])", "s"),
    (r"c", "k"),
    (r"w", "v"),
    (r"x", "ks"),
    (r"(?<=[^aeiou])y\b", "i"),
    (r"([bdfgklmnprstvz])\1", r"\1"),
    (r"[àáâäãå]", "a"),
    (r"[èéêë]", "e"),
    (r"[ìíîï]", "i"),
    (r"[òóôöõø]", "o"),
    (r"[ùúûü]", "u"),
    (r"ç", "s"),
    (r"ñ", "ny"),
    (r"ß", "ss"),
    (r"e\b", ""),
]


def transliterate_foreign(word: str) -> str:
    """Qoidaga asoslangan taxminiy fonetik yozuv (LLM mavjud boʻlmasa ishlatiladi)."""
    low = word.lower()
    if word[:1].isupper() and low.startswith("th"):
        low = "t" + low[2:]  # Thomas → Tomas, Thompson → Tompson
    for pattern, repl in _TRANSLIT_RULES:
        new = re.sub(pattern, repl, low)
        if new:  # soʻz butunlay yoʻqolib qolmasin
            low = new
    return _match_case(word, low)


def suggest_entries(text: str, known: set[str] | None = None) -> list[LexiconEntry]:
    return [LexiconEntry(t, transliterate_foreign(t), priority=1) for t in find_foreign_terms(text, known)]
