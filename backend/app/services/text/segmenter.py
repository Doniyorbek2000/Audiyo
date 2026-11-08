"""Kitob / uzun matnni boblar, fasllar, paragraflar va dialog bloklariga ajratish.

Qoidalar:
- Bob: sarlavha regexlari yoki parser bergan tuzilma.
- Fasl: "* * *", "***", "———" kabi ajratgichlar.
- Paragraf: boʻsh qator (yoki parser bergan <p>).
- Dialog: satr boshidagi "— " yoki «…» ichidagi nutq; muallif izohi ("— dedi Anvar.")
  hikoyachi blokiga ajratiladi.
- Har blok ≤ max_chars belgi: gap → ; : → , → boʻshliq boʻyicha boʻlinadi; soʻz hech qachon kesilmaydi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.text.pauses import (
    DIALOGUE_SWITCH_MS,
    block_pause_after,
    detect_intonation,
)
from app.services.text.uzbek import OKINA, TUTUQ

DEFAULT_MAX_CHARS = 2000

_NAME_CHARS = rf"[A-ZÀ-ÝА-ЯЁЎҚҒҲ][\w{OKINA}{TUTUQ}-]*"

CHAPTER_HEADING = re.compile(
    r"^\s*(?:"
    r"\d+\s*[-‑–]?\s*bob\b.*"
    r"|bob\s+[IVXLC\d]+\b.*"
    r"|[IVXLC]+\s+bob\b.*"
    r"|(?:birinchi|ikkinchi|uchinchi|toʻrtinchi|beshinchi|oltinchi|yettinchi|sakkizinchi|toʻqqizinchi|oʻninchi)\s+bob\b.*"
    r"|chapter\s+[IVXLC\d]+\b.*"
    r"|глава\s+[IVXLC\d]+\b.*"
    r"|(?:muqaddima|soʻngsoʻz|soʻzboshi|xotima|epilog|prolog)\s*$"
    r")",
    re.IGNORECASE,
)
SCENE_BREAK = re.compile(r"^\s*(?:\*\s*){3,}$|^\s*(?:[-—–_~]\s*){3,}$|^\s*#\s*$")

SPEECH_VERBS = (
    "dedi", "deydi", "soʻradi", "soʻraydi", "javob berdi", "qichqirdi", "baqirdi", "pichirladi",
    "shivirladi", "kuldi", "yigʻladi", "xitob qildi", "gapirdi", "takrorladi", "davom etdi",
    "eʼtiroz bildirdi", "tushuntirdi", "xoʻrsindi", "gʻoʻldiradi", "said", "asked", "replied",
    "shouted", "whispered", "cried", "сказал", "сказала", "спросил", "спросила", "ответил", "ответила",
)
_VERB_RE = "|".join(re.escape(v) for v in sorted(SPEECH_VERBS, key=len, reverse=True))
_HINT_AFTER = re.compile(rf"\b(?:{_VERB_RE})\b[\s,]+({_NAME_CHARS}(?:\s+{_NAME_CHARS})?)")
_HINT_BEFORE = re.compile(rf"({_NAME_CHARS}(?:\s+{_NAME_CHARS})?)\s+(?:[\w{OKINA}{TUTUQ}]+\s+){{0,3}}?(?:{_VERB_RE})\b")
_PRONOUNS = {"u", "men", "sen", "biz", "siz", "ular", "ul", "he", "she", "i", "they", "он", "она"}

_EMOTION_VERBS = {
    "qichqirdi": "angry", "baqirdi": "angry", "shouted": "angry",
    "pichirladi": "whisper", "shivirladi": "whisper", "whispered": "whisper",
    "kuldi": "happy", "yigʻladi": "sad", "cried": "sad", "xoʻrsindi": "sad",
    "xitob qildi": "excited",
}


@dataclass
class Block:
    block_type: str  # NARRATION | DIALOGUE | HEADING
    text: str
    speaker_hint: str | None = None
    emotion: str = "neutral"
    pause_after_ms: int = 500
    paragraph_index: int = 0


@dataclass
class Chapter:
    index: int
    title: str | None
    blocks: list[Block] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(b.text) for b in self.blocks)


@dataclass
class RawChapter:
    title: str | None
    paragraphs: list[str]


# --------------------------------------------------------------------------- boblar


def split_into_chapters(text: str) -> list[RawChapter]:
    """Tekis matndan boblarni ajratadi. Sarlavha topilmasa — bitta bob."""
    lines = text.split("\n")
    chapters: list[RawChapter] = []
    current = RawChapter(title=None, paragraphs=[])
    buf: list[str] = []

    def flush_paragraph() -> None:
        if buf:
            par = " ".join(s.strip() for s in buf if s.strip())
            if par:
                current.paragraphs.append(par)
            buf.clear()

    for line in lines:
        stripped = line.strip()
        if CHAPTER_HEADING.match(stripped) and len(stripped) <= 120:
            flush_paragraph()
            if current.paragraphs or current.title:
                chapters.append(current)
            current = RawChapter(title=stripped, paragraphs=[])
            continue
        if not stripped:
            flush_paragraph()
            continue
        if SCENE_BREAK.match(stripped):
            flush_paragraph()
            current.paragraphs.append("* * *")
            continue
        # Dialog satrlari har doim yangi paragraf boshlaydi
        if stripped.startswith("—") and buf:
            flush_paragraph()
        buf.append(stripped)
    flush_paragraph()
    if current.paragraphs or current.title:
        chapters.append(current)
    return chapters


# --------------------------------------------------------------------------- uzun matnni boʻlish

_SENTENCE_END = re.compile(r"(?<=[.!?…])[»\"')\]]*\s+(?=[«\"(\[—A-ZÀ-ÝА-ЯЁЎҚҒҲ0-9])")


def _split_by(text: str, pattern: str) -> list[str]:
    parts = re.split(pattern, text)
    return [p.strip() for p in parts if p and p.strip()]


def _pack(pieces: list[str], max_chars: int, joiner: str = " ") -> list[str]:
    out: list[str] = []
    cur = ""
    for p in pieces:
        cand = f"{cur}{joiner}{p}" if cur else p
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def split_long_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    sentences = _split_by(text, _SENTENCE_END)
    pieces: list[str] = []
    for s in sentences:
        if len(s) <= max_chars:
            pieces.append(s)
            continue
        for clause in _split_by(s, r"(?<=[;:])\s+"):
            if len(clause) <= max_chars:
                pieces.append(clause)
                continue
            for sub in _split_by(clause, r"(?<=,)\s+"):
                if len(sub) <= max_chars:
                    pieces.append(sub)
                else:
                    pieces.extend(_pack(sub.split(), max_chars))
    return _pack(pieces, max_chars)


# --------------------------------------------------------------------------- dialoglar


def extract_speaker_hint(remark: str) -> str | None:
    for rx in (_HINT_AFTER, _HINT_BEFORE):
        m = rx.search(remark)
        if m:
            name = m.group(1).strip()
            if name.lower() not in _PRONOUNS and name.split()[0].lower() not in _PRONOUNS:
                return name
    return None


def remark_emotion(remark: str) -> str | None:
    low = remark.lower()
    for verb, emo in _EMOTION_VERBS.items():
        if verb in low:
            return emo
    return None


def _is_remark(prev_speech: str, part: str) -> bool:
    if not part:
        return False
    starts_lower = part[0].islower()
    prev_ok = prev_speech.rstrip().endswith((",", "!", "?", "…", "?!", "!?"))
    has_verb = re.search(rf"\b(?:{_VERB_RE})\b", part.lower()) is not None
    return (starts_lower and prev_ok) or (has_verb and prev_ok)


def parse_dialogue_line(paragraph: str) -> list[tuple[str, str]]:
    """'— Nutq, — dedi u. — Yana nutq.' → [(DIALOGUE, ...), (NARRATION, ...), (DIALOGUE, ...)]."""
    body = paragraph.lstrip("—–- ").strip()
    raw_parts = re.split(r"\s+—\s+", body)
    result: list[tuple[str, str]] = []
    expect_remark = True
    for part in raw_parts:
        if not result:
            result.append(("DIALOGUE", part))
            continue
        kind, prev_text = result[-1]
        if kind == "DIALOGUE" and expect_remark and _is_remark(prev_text, part):
            result.append(("NARRATION", part))
            expect_remark = False
        elif kind == "NARRATION":
            result.append(("DIALOGUE", part))
            expect_remark = True
        else:
            result[-1] = (kind, f"{prev_text} — {part}")
    # Muallif izohidagi oxirgi vergulni olib tashlash: "Salom, — dedi u." → "Salom."
    cleaned: list[tuple[str, str]] = []
    for kind, text in result:
        if kind == "DIALOGUE" and text.endswith(","):
            text = text[:-1].rstrip() + "."
        cleaned.append((kind, text.strip()))
    return [c for c in cleaned if c[1]]


_QUOTE = re.compile(r"«([^«»]+)»")


def parse_quoted_paragraph(paragraph: str) -> list[tuple[str, str]] | None:
    """«…» ichidagi nutqni ajratadi (paragraf boshida yoki ":" dan keyin)."""
    if "«" not in paragraph:
        return None
    parts: list[tuple[str, str]] = []
    pos = 0
    found = False
    for m in _QUOTE.finditer(paragraph):
        before = paragraph[pos : m.start()]
        is_speech = (m.start() == 0) or before.rstrip().endswith(":") or (
            paragraph[m.end() : m.end() + 4].lstrip(" ,").startswith("—")
        )
        if not is_speech:
            continue
        found = True
        if before.strip():
            parts.append(("NARRATION", before.strip().rstrip(":").strip() + ":"))
        parts.append(("DIALOGUE", m.group(1).strip()))
        pos = m.end()
    if not found:
        return None
    rest = paragraph[pos:].strip().lstrip(",").strip().lstrip("—").strip()
    if rest:
        parts.append(("NARRATION", rest))
    return parts


# --------------------------------------------------------------------------- asosiy funksiya


def segment_chapter(
    index: int,
    raw: RawChapter,
    max_chars: int = DEFAULT_MAX_CHARS,
    *,
    is_last_chapter: bool = False,
) -> Chapter:
    chapter = Chapter(index=index, title=raw.title)
    if raw.title:
        chapter.blocks.append(Block("HEADING", raw.title, emotion="neutral", pause_after_ms=0))

    paragraphs = raw.paragraphs
    for p_idx, par in enumerate(paragraphs):
        if par == "* * *":
            if chapter.blocks:
                chapter.blocks[-1].pause_after_ms = block_pause_after(
                    chapter.blocks[-1].text, is_paragraph_end=True, next_is_scene_break=True
                )
            continue

        if par.startswith(("—", "–")) or (par.startswith("- ") and len(par) > 2):
            pieces = parse_dialogue_line(par)
        else:
            pieces = parse_quoted_paragraph(par) or [("NARRATION", par)]

        # Muallif izohidan spiker va emotsiyani olish
        hint = None
        emo_override = None
        for kind, text in pieces:
            if kind == "NARRATION" and any(k == "DIALOGUE" for k, _ in pieces):
                hint = hint or extract_speaker_hint(text)
                emo_override = emo_override or remark_emotion(text)

        par_blocks: list[Block] = []
        for kind, text in pieces:
            for chunk in split_long_text(text, max_chars):
                intonation = detect_intonation(chunk)
                emotion = (emo_override if kind == "DIALOGUE" and emo_override else intonation.emotion)
                par_blocks.append(
                    Block(
                        block_type=kind,
                        text=chunk,
                        speaker_hint=hint if kind == "DIALOGUE" else None,
                        emotion=emotion,
                        paragraph_index=p_idx,
                    )
                )
        for i, b in enumerate(par_blocks):
            last_in_par = i == len(par_blocks) - 1
            next_kind = par_blocks[i + 1].block_type if not last_in_par else None
            b.pause_after_ms = block_pause_after(
                b.text,
                is_paragraph_end=last_in_par,
                speaker_changes=next_kind is not None and next_kind != b.block_type,
            )
        chapter.blocks.extend(par_blocks)

    # Sarlavhadan keyingi pauza va bob oxiri
    for b in chapter.blocks:
        if b.block_type == "HEADING":
            b.pause_after_ms = block_pause_after(b.text, is_paragraph_end=True, is_heading=True)
    if chapter.blocks:
        chapter.blocks[-1].pause_after_ms = block_pause_after(
            chapter.blocks[-1].text, is_paragraph_end=True, is_chapter_end=True
        )
    return chapter


def segment_book(raw_chapters: list[RawChapter], max_chars: int = DEFAULT_MAX_CHARS) -> list[Chapter]:
    out: list[Chapter] = []
    for i, raw in enumerate(raw_chapters):
        ch = segment_chapter(i + 1, raw, max_chars, is_last_chapter=i == len(raw_chapters) - 1)
        if ch.blocks:
            out.append(ch)
    return out


__all__ = [
    "Block",
    "Chapter",
    "RawChapter",
    "DIALOGUE_SWITCH_MS",
    "extract_speaker_hint",
    "parse_dialogue_line",
    "parse_quoted_paragraph",
    "segment_book",
    "segment_chapter",
    "split_into_chapters",
    "split_long_text",
]
