"""LLM yordamida oʻzbekcha (lotin) dublyaj ssenariysi va davomiylik moslashuvi.

Oʻzbek tili agglyutinativ: tarjima odatda manbadan 15–30% uzunroq chiqadi. Shuning uchun har segmentga
boʻgʻin byudjeti beriladi:
    max_syllables   = duration_s × UZ_SYLLABLES_PER_SECOND × atempo_max
    ideal_syllables = duration_s × UZ_SYLLABLES_PER_SECOND
Byudjetdan oshgan segmentlar qisqartirish uchun qayta yuboriladi.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.services.llm.client import LLMClient
from app.services.text.uzbek import count_syllables, count_syllables_uz, normalize_apostrophes

UZ_SYLLABLES_PER_SECOND = 5.5
BATCH_SIZE = 30
MAX_SHORTEN_PASSES = 2

EMOTIONS = [
    "neutral", "happy", "sad", "angry", "excited", "fearful", "surprised",
    "whisper", "tender", "sarcastic", "serious", "curious", "hesitant", "anxious",
]

LANGUAGE_NAMES = {
    "en": "English", "ru": "Russian", "tr": "Turkish", "ko": "Korean", "ja": "Japanese",
    "zh": "Chinese", "ar": "Arabic", "fa": "Persian", "hi": "Hindi", "de": "German",
    "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "kk": "Kazakh",
}

SYSTEM_PROMPT = """You are a senior dubbing script adapter for Uzbek (Latin script, 2023 orthography).
Translate each segment so that it can be SPOKEN by a voice actor within the given time window.

Hard rules:
1. Output Uzbek in Latin script only. Use ʻ (U+02BB) in oʻ, gʻ and ʼ (U+02BC) for tutuq belgisi.
2. Respect the syllable budget for each segment: target_uz_text must have at most `max_syllables`
   syllables (in Uzbek every vowel a, e, i, o, u, oʻ is one syllable). Aim for `ideal_syllables`.
   Uzbek is agglutinative and tends to be longer — compress: drop filler words, use shorter synonyms,
   prefer active voice, merge suffixes, avoid repeating the subject, keep meaning and tone.
3. Write numbers as words. Do not add stage directions, brackets, notes or quotes.
4. Keep character names consistent; transliterate foreign names phonetically for an Uzbek reader
   (e.g. "Washington" → "Vashington", "Harry" → "Garri") and reuse the glossary when given.
5. Address forms: use "siz" for polite/formal, "sen" between close friends, family or when angry.
6. Preserve the emotion; choose emotion_tag from the allowed list.
7. Return exactly one item per input segment, same segment_id, same order.
"""

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "segments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "segment_id": {"type": "STRING"},
                    "speaker_id": {"type": "STRING"},
                    "source_text": {"type": "STRING"},
                    "target_uz_text": {"type": "STRING"},
                    "target_duration_ms": {"type": "INTEGER"},
                    "emotion_tag": {"type": "STRING", "enum": EMOTIONS},
                },
                "required": [
                    "segment_id", "speaker_id", "source_text", "target_uz_text",
                    "target_duration_ms", "emotion_tag",
                ],
            },
        },
        "glossary": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"source": {"type": "STRING"}, "uz": {"type": "STRING"}},
                "required": ["source", "uz"],
            },
        },
    },
    "required": ["segments"],
}


@dataclass
class SourceSegment:
    segment_id: str
    speaker_id: str
    source_text: str
    start_ms: int
    end_ms: int
    gender: str = "UNKNOWN"

    @property
    def duration_ms(self) -> int:
        return max(1, self.end_ms - self.start_ms)


@dataclass
class TranslatedSegment:
    segment_id: str
    speaker_id: str
    source_text: str
    target_uz_text: str
    target_duration_ms: int
    emotion_tag: str
    source_syllables: int
    target_syllables: int
    max_syllables: int

    @property
    def over_budget(self) -> bool:
        return self.target_syllables > self.max_syllables


@dataclass
class TranslationResult:
    segments: list[TranslatedSegment]
    glossary: dict[str, str] = field(default_factory=dict)


def syllable_budget(duration_ms: int, atempo_max: float = 1.25) -> tuple[int, int]:
    seconds = duration_ms / 1000
    ideal = max(1, round(seconds * UZ_SYLLABLES_PER_SECOND))
    maximum = max(2, math.floor(seconds * UZ_SYLLABLES_PER_SECOND * atempo_max))
    return ideal, maximum


def _segment_payload(seg: SourceSegment, source_lang: str, atempo_max: float) -> dict[str, Any]:
    ideal, maximum = syllable_budget(seg.duration_ms, atempo_max)
    return {
        "segment_id": seg.segment_id,
        "speaker_id": seg.speaker_id,
        "speaker_gender": seg.gender,
        "source_text": seg.source_text,
        "source_syllables": count_syllables(seg.source_text, source_lang),
        "target_duration_ms": seg.duration_ms,
        "ideal_syllables": ideal,
        "max_syllables": maximum,
    }


def _build_prompt(
    batch: list[SourceSegment],
    source_lang: str,
    atempo_max: float,
    glossary: dict[str, str],
    context: list[str],
    title: str | None,
) -> str:
    import json

    lang_name = LANGUAGE_NAMES.get(source_lang[:2], source_lang)
    parts = [f"Source language: {lang_name}. Target: Uzbek (Latin)."]
    if title:
        parts.append(f"Title: {title}")
    if glossary:
        parts.append("Glossary (keep consistent):\n" + "\n".join(f"- {k} → {v}" for k, v in glossary.items()))
    if context:
        parts.append("Previous lines (context only, do not translate):\n" + "\n".join(context[-6:]))
    parts.append(f"Allowed emotion_tag values: {', '.join(EMOTIONS)}")
    items = [_segment_payload(s, source_lang, atempo_max) for s in batch]
    parts.append("Segments:\n" + json.dumps(items, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


def _shorten_prompt(items: list[TranslatedSegment]) -> str:
    import json

    payload = [
        {
            "segment_id": t.segment_id,
            "speaker_id": t.speaker_id,
            "source_text": t.source_text,
            "current_uz_text": t.target_uz_text,
            "current_syllables": t.target_syllables,
            "max_syllables": t.max_syllables,
            "target_duration_ms": t.target_duration_ms,
            "emotion_tag": t.emotion_tag,
        }
        for t in items
    ]
    return (
        "These Uzbek dubbing lines are TOO LONG for their time windows. Rewrite each so it has at most "
        "`max_syllables` syllables while keeping the meaning and tone. Put the new line in target_uz_text.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )


def _to_translated(raw: dict[str, Any], src: SourceSegment, source_lang: str, atempo_max: float) -> TranslatedSegment:
    text = normalize_apostrophes(str(raw.get("target_uz_text", "")).strip())
    emotion = raw.get("emotion_tag") if raw.get("emotion_tag") in EMOTIONS else "neutral"
    _, maximum = syllable_budget(src.duration_ms, atempo_max)
    return TranslatedSegment(
        segment_id=src.segment_id,
        speaker_id=src.speaker_id,
        source_text=src.source_text,
        target_uz_text=text,
        target_duration_ms=src.duration_ms,
        emotion_tag=emotion,
        source_syllables=count_syllables(src.source_text, source_lang),
        target_syllables=count_syllables_uz(text),
        max_syllables=maximum,
    )


def translate_segments(
    llm: LLMClient,
    segments: list[SourceSegment],
    source_lang: str,
    *,
    atempo_max: float = 1.25,
    title: str | None = None,
    glossary: dict[str, str] | None = None,
    batch_size: int = BATCH_SIZE,
) -> TranslationResult:
    glossary = dict(glossary or {})
    by_id = {s.segment_id: s for s in segments}
    results: dict[str, TranslatedSegment] = {}
    context: list[str] = []

    for i in range(0, len(segments), batch_size):
        batch = segments[i : i + batch_size]
        data = llm.generate_json(
            SYSTEM_PROMPT, _build_prompt(batch, source_lang, atempo_max, glossary, context, title), _SCHEMA
        )
        returned = {str(item.get("segment_id")): item for item in data.get("segments", [])}
        for g in data.get("glossary", []) or []:
            if g.get("source") and g.get("uz"):
                glossary.setdefault(g["source"], g["uz"])
        missing = [s for s in batch if s.segment_id not in returned]
        if missing:
            # Bitta-bitta qayta soʻrash (LLM baʼzan elementlarni tushirib qoldiradi)
            for s in missing:
                retry = llm.generate_json(
                    SYSTEM_PROMPT, _build_prompt([s], source_lang, atempo_max, glossary, context, title), _SCHEMA
                )
                items = retry.get("segments", [])
                if items:
                    returned[s.segment_id] = items[0]
        for s in batch:
            raw = returned.get(s.segment_id)
            if raw is None:
                raise ValueError(f"Segment {s.segment_id} tarjima qilinmadi")
            t = _to_translated(raw, s, source_lang, atempo_max)
            results[s.segment_id] = t
            context.append(f"[{s.speaker_id}] {s.source_text} → {t.target_uz_text}")

    # Byudjetdan oshganlarni qisqartirish
    for _ in range(MAX_SHORTEN_PASSES):
        over = [t for t in results.values() if t.over_budget]
        if not over:
            break
        for j in range(0, len(over), batch_size):
            chunk = over[j : j + batch_size]
            data = llm.generate_json(SYSTEM_PROMPT, _shorten_prompt(chunk), _SCHEMA, temperature=0.2)
            for item in data.get("segments", []):
                sid = str(item.get("segment_id"))
                if sid in by_id:
                    candidate = _to_translated(item, by_id[sid], source_lang, atempo_max)
                    if candidate.target_syllables < results[sid].target_syllables and candidate.target_uz_text:
                        candidate.emotion_tag = results[sid].emotion_tag
                        results[sid] = candidate

    return TranslationResult(segments=[results[s.segment_id] for s in segments], glossary=glossary)
