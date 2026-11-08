"""Audiokitob "rejissyori": har blok uchun ijro koʻrsatmasi, nomsiz spikerlar va muhit sahnalari.

LLM bobni boʻlaklab oʻqiydi va qaytaradi:
- blocks: emotsiya, qisqa ijro koʻrsatmasi (TTS uslub promptiga qoʻshiladi), nomsiz dialog
  spikerining roli/jinsi/yoshi (alohida ovoz berish uchun);
- scenes: matn tinglovchini aniq jismoniy joyga olib kirgan oraliqlar va ularning muhit tovushi
  (olomon gʻovuri, yomgʻir, maktab hovlisi ...). Mavhum/tushuntiruvchi matnga sahna qoʻyilmaydi.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from app.services.llm.client import LLMClient, LLMError
from app.services.llm.translation import EMOTIONS
from app.services.text.uzbek import normalize_apostrophes

log = logging.getLogger(__name__)

WINDOW = 45  # bitta soʻrovdagi bloklar
CONTEXT = 3  # oldingi oynadan kontekst
MAX_TEXT = 700
MIN_SCENE_BLOCKS = 2
NARRATOR_ROLES = {"muallif", "hikoyachi", "men", "roviy", "author", "narrator"}

SYSTEM = """You are the director of an Uzbek audiobook. You read a chapter as numbered blocks and decide how
each block should be PERFORMED, so the listener is drawn into the book.

For every block return:
- emotion: one of the allowed values.
- delivery: a short English performance note for the voice actor (max 12 words), e.g.
  "warm, reflective storytelling", "tense, hushed, slightly faster", "shocked, voice breaking".
  Narration is told by one narrator: vary pace and colour with the content, never flat.
  Dialogue is acted by the speaker: match their situation and feeling.
- For DIALOGUE blocks whose speaker is not named (speaker is null): speaker_role in Uzbek Latin
  (1–3 words, e.g. "Hamshira", "Sinfdosh", "Shifokor", "Ona"), speaker_gender and speaker_age
  inferred from context. Use the same role name for the same person. If the line is spoken by the
  author / first-person narrator himself, use speaker_role "Muallif". Otherwise speaker_role is "".

Also return scenes: block ranges where the text places the listener in a concrete physical setting
that has a characteristic background sound (a crowd, a school yard, a hospital ward, rain, a street,
a forest, a kitchen, a stadium). Rules:
- Only for vivid, situated passages (stories, memories, anecdotes). Never for abstract explanation,
  advice, lists or summaries — most of a non-fiction chapter has NO scene.
- A scene spans at least 2 blocks; scenes never overlap; at most one scene per 8 blocks.
- ambience_prompt: English description for a sound-effects generator of a seamless background bed,
  no music, no intelligible words, e.g. "busy high school gym, distant indistinct chatter, sneakers squeaking".
- label: short Uzbek Latin description, e.g. "Maktab sport zali".
- intensity: "low" (subtle) or "medium".
"""

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "blocks": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "seq": {"type": "INTEGER"},
                    "emotion": {"type": "STRING", "enum": list(EMOTIONS)},
                    "delivery": {"type": "STRING"},
                    "speaker_role": {"type": "STRING"},
                    "speaker_gender": {"type": "STRING", "enum": ["MALE", "FEMALE", "UNKNOWN"]},
                    "speaker_age": {"type": "STRING", "enum": ["CHILD", "YOUNG_ADULT", "ADULT", "ELDERLY"]},
                },
                "required": ["seq", "emotion", "delivery"],
            },
        },
        "scenes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start_seq": {"type": "INTEGER"},
                    "end_seq": {"type": "INTEGER"},
                    "label": {"type": "STRING"},
                    "ambience_prompt": {"type": "STRING"},
                    "intensity": {"type": "STRING", "enum": ["low", "medium"]},
                },
                "required": ["start_seq", "end_seq", "label", "ambience_prompt", "intensity"],
            },
        },
    },
    "required": ["blocks", "scenes"],
}


@dataclass
class BlockIn:
    seq: int
    block_type: str  # NARRATION | DIALOGUE | HEADING
    text: str
    speaker: str | None = None  # maʼlum personaj nomi


@dataclass
class BlockDirection:
    seq: int
    emotion: str = "neutral"
    delivery: str = ""
    speaker_role: str = ""
    speaker_gender: str = "UNKNOWN"
    speaker_age: str = "ADULT"


@dataclass
class Scene:
    start_seq: int
    end_seq: int
    label: str
    ambience_prompt: str
    intensity: str = "low"


@dataclass
class ChapterDirection:
    blocks: dict[int, BlockDirection] = field(default_factory=dict)
    scenes: list[Scene] = field(default_factory=list)


def _clean_delivery(s: str) -> str:
    s = " ".join(str(s or "").split())
    words = s.split()
    return " ".join(words[:14]).strip(" .;")


def _payload(blocks: list[BlockIn], context: list[BlockIn], title: str | None) -> str:
    def item(b: BlockIn) -> dict:
        return {"seq": b.seq, "type": b.block_type, "speaker": b.speaker, "text": b.text[:MAX_TEXT]}

    parts = []
    if title:
        parts.append(f"Chapter: {title}")
    if context:
        parts.append("Context (already directed, do not return):\n" + json.dumps([item(b) for b in context],
                                                                                ensure_ascii=False))
    parts.append(f"Allowed emotions: {', '.join(EMOTIONS)}")
    parts.append("Blocks:\n" + json.dumps([item(b) for b in blocks], ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


def normalize_scenes(raw: list[Scene], valid: list[int]) -> list[Scene]:
    """Oraliqni chegaralaydi, qisqa va ustma-ust sahnalarni olib tashlaydi."""
    if not valid:
        return []
    lo, hi = min(valid), max(valid)
    out: list[Scene] = []
    for sc in sorted(raw, key=lambda s: s.start_seq):
        start, end = max(lo, sc.start_seq), min(hi, sc.end_seq)
        if end - start + 1 < MIN_SCENE_BLOCKS or not sc.ambience_prompt.strip():
            continue
        if out and start <= out[-1].end_seq:
            continue  # ustma-ust — birinchisi qoladi
        intensity = sc.intensity if sc.intensity in ("low", "medium") else "low"
        out.append(Scene(start, end, sc.label.strip()[:120] or "Sahna", sc.ambience_prompt.strip()[:400], intensity))
    return out


def canonical_role(role: str) -> str | None:
    """Rol nomini birlashtiradi (apostrof variantlari, registr). Muallif/hikoyachi → None (hikoyachi ovozi)."""
    r = normalize_apostrophes(" ".join(role.split())).strip(" .,:;\"'")
    if not r:
        return None
    if r.lower() in NARRATOR_ROLES:
        return None
    # Atoqli ot ("Laslo Polgar") — registr saqlanadi; oddiy rol ("hamshira") — bosh harf bilan
    if any(c.isupper() for c in r[1:]) and not r.isupper():
        return r
    return r[:1].upper() + r[1:].lower()


def direct_chapter(llm: LLMClient, blocks: list[BlockIn], title: str | None = None,
                   retry_delay_s: float = 10.0) -> ChapterDirection:
    result = ChapterDirection()
    if not blocks:
        return result
    scenes: list[Scene] = []
    for i in range(0, len(blocks), WINDOW):
        window = blocks[i : i + WINDOW]
        context = blocks[max(0, i - CONTEXT) : i]
        data = None
        for attempt in range(2):  # band model / uzilish — bir marta qayta urinish
            try:
                data = llm.generate_json(SYSTEM, _payload(window, context, title), _SCHEMA, temperature=0.4)
                break
            except LLMError as exc:
                log.warning("Rejissyor: oyna %s, urinish %s: %s", i, attempt + 1, str(exc)[:200])
                if attempt == 0:
                    time.sleep(retry_delay_s)
        if data is None:
            log.warning("Rejissyor: oyna %s o'tkazib yuborildi", i)
            continue
        wanted = {b.seq: b for b in window}
        for d in data.get("blocks", []) or []:
            seq = d.get("seq")
            if seq not in wanted:
                continue
            b = wanted[seq]
            role = ""
            if b.block_type == "DIALOGUE" and not b.speaker:
                role = canonical_role(str(d.get("speaker_role") or "")) or ""
            result.blocks[seq] = BlockDirection(
                seq=seq,
                emotion=d.get("emotion") if d.get("emotion") in EMOTIONS else "neutral",
                delivery=_clean_delivery(d.get("delivery", "")),
                speaker_role=role[:60],
                speaker_gender=d.get("speaker_gender") or "UNKNOWN",
                speaker_age=d.get("speaker_age") or "ADULT",
            )
        for sc in data.get("scenes", []) or []:
            try:
                scenes.append(Scene(int(sc["start_seq"]), int(sc["end_seq"]), str(sc.get("label", "")),
                                    str(sc.get("ambience_prompt", "")), str(sc.get("intensity", "low"))))
            except (KeyError, TypeError, ValueError):
                continue
    result.scenes = normalize_scenes(scenes, [b.seq for b in blocks])
    return result
