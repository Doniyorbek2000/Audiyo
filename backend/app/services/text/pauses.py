"""Tinish belgilari asosida pauza va intonatsiya qoidalari."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Blok ichidagi pauzalar (ms)
COMMA_MS = 250
SEMICOLON_MS = 350
SENTENCE_MS = 500
ELLIPSIS_MS = 700
DIALOGUE_SWITCH_MS = 400
PARAGRAPH_MS = 800
SCENE_BREAK_MS = 1500
CHAPTER_END_MS = 2500
HEADING_MS = 1200


@dataclass(frozen=True)
class Intonation:
    contour: str  # falling | rising | emphatic | trailing | continuing
    emotion: str


def terminal_pause_ms(text: str) -> int:
    t = text.rstrip(" »\"')]")
    if not t:
        return SENTENCE_MS
    if t.endswith("…"):
        return ELLIPSIS_MS
    if t[-1] in ".!?":
        return SENTENCE_MS
    if t[-1] in ";:":
        return SEMICOLON_MS
    if t[-1] in ",—–-":
        return COMMA_MS
    return SENTENCE_MS


def block_pause_after(
    text: str,
    *,
    is_paragraph_end: bool,
    next_is_scene_break: bool = False,
    is_chapter_end: bool = False,
    speaker_changes: bool = False,
    is_heading: bool = False,
) -> int:
    if is_chapter_end:
        return CHAPTER_END_MS
    if is_heading:
        return HEADING_MS
    if next_is_scene_break:
        return SCENE_BREAK_MS
    pause = terminal_pause_ms(text)
    if is_paragraph_end:
        pause = max(pause, PARAGRAPH_MS)
    if speaker_changes:
        pause = max(pause, DIALOGUE_SWITCH_MS)
    return pause


_QUESTION_PARTICLES = re.compile(r"(mi|chi|a)\s*\?$|\b(nima|kim|qanday|qachon|qayerda|nega|nimaga|qancha|qaysi)\b", re.I)


def detect_intonation(text: str) -> Intonation:
    t = text.strip().rstrip("»\"' ")
    if t.endswith("?!") or t.endswith("!?"):
        return Intonation("emphatic", "surprised")
    if t.endswith("?"):
        return Intonation("rising", "curious" if _QUESTION_PARTICLES.search(t) else "neutral")
    if t.endswith("!"):
        return Intonation("emphatic", "excited")
    if t.endswith("…"):
        return Intonation("trailing", "hesitant")
    if t.endswith((",", ";", ":", "—")):
        return Intonation("continuing", "neutral")
    return Intonation("falling", "neutral")


def render_inline_pauses_ssml(text: str) -> str:
    """ElevenLabs uchun <break> teglari (faqat tabiiy pauzalardan uzunroq joylarda)."""
    text = re.sub(r"…\s*", f'… <break time="{ELLIPSIS_MS / 1000:.1f}s" /> ', text)
    text = re.sub(r"\s+—\s+", f' — <break time="{COMMA_MS / 1000:.2f}s" /> ', text)
    text = re.sub(r";\s*", f'; <break time="{SEMICOLON_MS / 1000:.2f}s" /> ', text)
    return re.sub(r"\s{2,}", " ", text).strip()
