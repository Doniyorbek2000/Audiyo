"""Kitob personajlari reyestri va dialog bloklarini spikerga bogʻlash.

1. Evristika: muallif izohidagi "dedi Kumush" → Kumush (ishonch 0.95).
2. Navbatlashish: ikki kishilik suhbatda izohsiz satrlar navbatma-navbat (ishonch 0.55).
3. LLM: qolgan noaniq satrlar kontekst oynasi bilan (ishonch LLM bergan qiymat).
Ishonch < threshold boʻlgan bloklar UI da qoʻlda tasdiqlash uchun belgilanadi.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from app.services.llm.client import LLMClient, LLMError
from app.services.text.segmenter import Chapter

HINT_CONFIDENCE = 0.95
ALTERNATION_CONFIDENCE = 0.55
LLM_BATCH = 40
CONTEXT_BLOCKS = 3

_FEMALE_ENDINGS = ("oy", "xon", "gul", "niso", "bibi", "bonu", "begim", "poshsha", "a", "ya", "ra")
_FEMALE_EXCEPTIONS = {"musa", "iso", "yahyo", "mustafa", "hamza", "toha", "murtazo", "mirzo", "ota"}


def guess_gender(name: str) -> str:
    first = name.split()[0].lower()
    if first in _FEMALE_EXCEPTIONS:
        return "MALE"
    if first.endswith(_FEMALE_ENDINGS):
        return "FEMALE"
    if first.endswith(("bek", "jon", "boy", "xoʻja", "mirzo", "ali", "ullo", "dor", "zod")):
        return "MALE"
    return "UNKNOWN"


@dataclass
class CharacterInfo:
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    gender: str = "UNKNOWN"
    age_group: str = "ADULT"

    def names(self) -> set[str]:
        return {self.canonical_name.lower(), *(a.lower() for a in self.aliases)}


@dataclass
class Attribution:
    character: str | None  # canonical_name; None = hikoyachi/nomaʼlum
    confidence: float


class CharacterRegistry:
    def __init__(self, characters: list[CharacterInfo]) -> None:
        self.characters = {c.canonical_name: c for c in characters}
        self._index: dict[str, str] = {}
        for c in characters:
            for n in c.names():
                self._index[n] = c.canonical_name

    def resolve(self, name: str | None) -> str | None:
        if not name:
            return None
        key = name.lower().strip()
        if key in self._index:
            return self._index[key]
        first = key.split()[0]
        return self._index.get(first)

    def add(self, info: CharacterInfo) -> None:
        self.characters[info.canonical_name] = info
        for n in info.names():
            self._index.setdefault(n, info.canonical_name)


_REGISTRY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "characters": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "canonical_name": {"type": "STRING"},
                    "aliases": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "gender": {"type": "STRING", "enum": ["MALE", "FEMALE", "UNKNOWN"]},
                    "age_group": {"type": "STRING", "enum": ["CHILD", "YOUNG_ADULT", "ADULT", "ELDERLY"]},
                },
                "required": ["canonical_name", "aliases", "gender", "age_group"],
            },
        }
    },
    "required": ["characters"],
}

_ATTR_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "attributions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "block_ref": {"type": "STRING"},
                    "speaker": {"type": "STRING"},
                    "confidence": {"type": "NUMBER"},
                },
                "required": ["block_ref", "speaker", "confidence"],
            },
        }
    },
    "required": ["attributions"],
}

REGISTRY_SYSTEM = (
    "You analyse fiction (usually Uzbek, sometimes Russian or English) and build a cast list for an "
    "audiobook. Merge nicknames, diminutives, titles and surname-only mentions into one character "
    "(e.g. 'Otabek', 'Otabekbek', 'bek' → canonical 'Otabek'). Only include characters who speak. "
    "Estimate gender and age group from context."
)
ATTR_SYSTEM = (
    "You decide who speaks each dialogue line in a novel. Use the cast list, the author's remarks, "
    "turn-taking and context. Answer with a canonical name from the cast list, or 'UNKNOWN'. "
    "confidence is 0..1."
)


def _iter_dialogues(chapters: list[Chapter]):
    for ch in chapters:
        for i, b in enumerate(ch.blocks):
            if b.block_type == "DIALOGUE":
                yield ch, i, b


def heuristic_registry(chapters: list[Chapter]) -> list[CharacterInfo]:
    counts = Counter(b.speaker_hint for _, _, b in _iter_dialogues(chapters) if b.speaker_hint)
    return [CharacterInfo(name, [], guess_gender(name)) for name, _ in counts.most_common()]


def build_registry(chapters: list[Chapter], llm: LLMClient | None) -> CharacterRegistry:
    base = heuristic_registry(chapters)
    if llm is None:
        return CharacterRegistry(base)
    samples: list[str] = []
    budget = 24000
    for ch, i, b in _iter_dialogues(chapters):
        prev = ch.blocks[i - 1].text if i > 0 else ""
        nxt = ch.blocks[i + 1].text if i + 1 < len(ch.blocks) else ""
        line = f"{prev[-120:]} | «{b.text[:200]}» | {nxt[:120]}"
        budget -= len(line)
        if budget < 0:
            break
        samples.append(line)
    prompt = (
        "Candidate speaker names found by heuristics (with counts): "
        + json.dumps({c.canonical_name: 0 for c in base}, ensure_ascii=False)
        + "\n\nDialogue samples (previous text | line | next text):\n"
        + "\n".join(samples)
    )
    try:
        data = llm.generate_json(REGISTRY_SYSTEM, prompt, _REGISTRY_SCHEMA, temperature=0.1)
    except LLMError:
        return CharacterRegistry(base)
    chars = [
        CharacterInfo(
            canonical_name=c["canonical_name"].strip(),
            aliases=[a.strip() for a in c.get("aliases", []) if a.strip()],
            gender=c.get("gender", "UNKNOWN"),
            age_group=c.get("age_group", "ADULT"),
        )
        for c in data.get("characters", [])
        if c.get("canonical_name", "").strip()
    ]
    registry = CharacterRegistry(chars)
    for c in base:  # LLM tushirib qoldirganlar
        if registry.resolve(c.canonical_name) is None:
            registry.add(c)
    return registry


def attribute(
    chapters: list[Chapter], registry: CharacterRegistry, llm: LLMClient | None
) -> dict[tuple[int, int], Attribution]:
    """Natija: (chapter_index, block_position) → Attribution (faqat DIALOGUE bloklar)."""
    result: dict[tuple[int, int], Attribution] = {}

    # 1. Muallif izohidan
    for ch, i, b in _iter_dialogues(chapters):
        name = registry.resolve(b.speaker_hint)
        result[(ch.index, i)] = Attribution(name, HINT_CONFIDENCE) if name else Attribution(None, 0.0)

    # 2. Navbatlashish: bitta paragraf = bitta replika; ketma-ket paragraflarda A, B, ?, B → A
    for ch in chapters:
        paras: list[tuple[int, list[int]]] = []
        for i, b in enumerate(ch.blocks):
            if b.block_type != "DIALOGUE":
                continue
            if paras and paras[-1][0] == b.paragraph_index:
                paras[-1][1].append(i)
            else:
                paras.append((b.paragraph_index, [i]))
        runs: list[list[tuple[int, list[int]]]] = []
        for para in paras:
            if runs and para[0] - runs[-1][-1][0] == 1:
                runs[-1].append(para)
            else:
                runs.append([para])
        for run in runs:
            _fill_alternation(ch.index, run, result)

    # 3. LLM
    if llm is not None:
        unresolved = [
            (ch, i, b)
            for ch, i, b in _iter_dialogues(chapters)
            if result[(ch.index, i)].confidence < ALTERNATION_CONFIDENCE
        ]
        cast = [
            {"name": c.canonical_name, "aliases": c.aliases, "gender": c.gender}
            for c in registry.characters.values()
        ]
        for j in range(0, len(unresolved), LLM_BATCH):
            chunk = unresolved[j : j + LLM_BATCH]
            items = []
            for ch, i, b in chunk:
                ctx = [
                    f"{'N' if x.block_type != 'DIALOGUE' else 'D'}: {x.text[:200]}"
                    for x in ch.blocks[max(0, i - CONTEXT_BLOCKS) : i]
                ]
                items.append({"block_ref": f"{ch.index}:{i}", "context": ctx, "line": b.text[:400]})
            prompt = (
                "Cast:\n" + json.dumps(cast, ensure_ascii=False)
                + "\n\nLines:\n" + json.dumps(items, ensure_ascii=False, indent=1)
            )
            try:
                data = llm.generate_json(ATTR_SYSTEM, prompt, _ATTR_SCHEMA, temperature=0.1)
            except LLMError:
                break
            for a in data.get("attributions", []):
                m = re.fullmatch(r"(\d+):(\d+)", str(a.get("block_ref", "")))
                if not m:
                    continue
                key = (int(m[1]), int(m[2]))
                if key not in result:
                    continue
                name = registry.resolve(a.get("speaker"))
                conf = float(a.get("confidence") or 0)
                if name and conf > result[key].confidence:
                    result[key] = Attribution(name, round(min(conf, 0.99), 2))
    return result


def _fill_alternation(chapter_index: int, run: list[tuple[int, list[int]]], result) -> None:
    def speaker_of(positions: list[int]) -> str | None:
        return next((result[(chapter_index, p)].character for p in positions
                     if result[(chapter_index, p)].character), None)

    # Paragraf ichida bitta spiker
    for _, positions in run:
        known = speaker_of(positions)
        if known:
            for p in positions:
                if not result[(chapter_index, p)].character:
                    result[(chapter_index, p)] = Attribution(known, HINT_CONFIDENCE)
    if len(run) < 3:
        return
    speakers = [speaker_of(positions) for _, positions in run]
    for k, (_, positions) in enumerate(run):
        if speakers[k]:
            continue
        guess = (speakers[k - 2] if k >= 2 else None) or (speakers[k + 2] if k + 2 < len(run) else None)
        if guess:
            for p in positions:
                result[(chapter_index, p)] = Attribution(guess, ALTERNATION_CONFIDENCE)


def dialogue_shares(
    chapters: list[Chapter], attributions: dict[tuple[int, int], Attribution]
) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for ch, i, b in _iter_dialogues(chapters):
        name = attributions.get((ch.index, i), Attribution(None, 0)).character
        if name:
            totals[name] += len(b.text)
    grand = sum(totals.values()) or 1
    return {name: round(v / grand, 4) for name, v in totals.items()}

