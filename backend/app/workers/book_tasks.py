"""Kitob / uzun matn konveyeri.

UPLOADED → PARSED → NORMALIZED → SEGMENTED → ATTRIBUTED → LEXICON_APPLIED  (avtomatik)
  ⏸ foydalanuvchi personajlar, ovozlar, leksikon va narxni tekshiradi
→ TTS_DISPATCHED → STITCHED → READY_FOR_EXPORT                              (POST /books/{id}/synthesize)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
import zipfile
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import delete, or_, select

from app import events, storage
from app.config import get_settings
from app.db import sync_session
from app.models import (
    AgeGroup,
    BlockType,
    BookChapter,
    BookCharacter,
    BookProject,
    BookStatus,
    Gender,
    LexiconSource,
    PronunciationEntry,
    SegmentStatus,
    TextBlock,
    TTSMode,
    TTSProvider,
    TTSTier,
)
from app.services import billing
from app.services.llm.attribution import attribute, build_registry, dialogue_shares
from app.services.llm.client import LLMError, LLMNotConfigured, get_llm
from app.services.media import ffmpeg, mixing
from app.services.text import lexicon as lex
from app.services.text.normalizer import (
    expand_abbreviations,
    expand_numbers,
    expand_roman_numerals,
    normalize_punctuation,
)
from app.services.text.parsers import parse_book
from app.services.text.segmenter import segment_book
from app.services.text.uzbek import cyrillic_ratio, cyrillic_to_latin, normalize_apostrophes
from app.services.tts import cost as tts_cost
from app.services.tts.router import (
    SpeakerSpec,
    SpeakerStats,
    VoiceAssignment,
    assign_tiers,
    assign_voices,
    pick_narrator,
)
from app.services.tts.service import (
    SynthItem,
    SynthOutcome,
    build_router,
    effective_assignment,
    load_catalog,
    record_job,
    synthesize_many,
    voice_option,
)
from app.workers.celery_app import celery_app
from app.workers.common import book_stage, fail_book, interpolate, set_book_status, workdir

log = logging.getLogger(__name__)
NARRATOR_KEY = "__narrator__"


def start_pipeline(book_id: uuid.UUID) -> None:
    prepare.delay(str(book_id))


def _guarded(fn):
    def wrapper(book_id: str, *args, **kwargs):
        bid = uuid.UUID(book_id)
        try:
            return fn(bid, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("Kitob konveyer xatosi (%s)", fn.__name__)
            fail_book(bid, f"{fn.__name__}: {exc}")
            raise

    wrapper.__name__ = fn.__name__
    return wrapper


def _key(book_id: uuid.UUID, name: str) -> str:
    return f"books/{book_id}/{name}"


def _optional_llm():
    try:
        return get_llm()
    except LLMNotConfigured:
        log.warning("LLM sozlanmagan — evristik usullar ishlatiladi")
        return None


# =============================================================== 1. Parse → normalize → segment


def _display_normalize(text: str) -> str:
    if cyrillic_ratio(text) > 0.5:
        text = cyrillic_to_latin(text)
    return normalize_punctuation(normalize_apostrophes(text))


@celery_app.task(name="book.prepare")
@_guarded
def prepare(book_id: uuid.UUID) -> None:
    cfg = get_settings()
    with sync_session() as s:
        b = s.get(BookProject, book_id)
        key, fmt = b.source_file_key, b.source_format
    book_stage(book_id, "PARSING", "Fayl oʻqilmoqda", 1)
    with workdir("book", book_id) as wd:
        data = storage.download_file(key, wd / f"source.{fmt}").read_bytes()
    raw = parse_book(data, fmt)
    if not raw:
        raise RuntimeError("Fayldan matn ajratib boʻlmadi")
    set_book_status(book_id, BookStatus.PARSED, f"{len(raw)} ta bob topildi")

    for ch in raw:
        ch.title = _display_normalize(ch.title) if ch.title else None
        ch.paragraphs = [p for p in (_display_normalize(x) for x in ch.paragraphs) if p]
    set_book_status(book_id, BookStatus.NORMALIZED, "Matn normallashtirildi")

    chapters = segment_book(raw, cfg.book_block_max_chars)
    total_chars = sum(c.char_count for c in chapters)
    with sync_session() as s:
        s.execute(delete(BookChapter).where(BookChapter.book_id == book_id))
        for ch in chapters:
            row = BookChapter(book_id=book_id, chapter_index=ch.index, title=ch.title)
            s.add(row)
            s.flush()
            for pos, blk in enumerate(ch.blocks):
                s.add(TextBlock(
                    chapter_id=row.id, sequence_order=pos, block_type=BlockType(blk.block_type),
                    source_text=blk.text, emotion_tag=blk.emotion, pause_after_ms=blk.pause_after_ms,
                ))
        b = s.get(BookProject, book_id)
        b.total_chars = total_chars
    # Segmentlash natijasi atributsiya uchun (speaker_hint, paragraph_index) saqlanadi
    storage.upload_bytes(json.dumps([
        {"index": c.index, "title": c.title, "blocks": [
            {"t": x.block_type, "x": x.text, "h": x.speaker_hint, "e": x.emotion, "p": x.paragraph_index,
             "pa": x.pause_after_ms} for x in c.blocks]}
        for c in chapters
    ], ensure_ascii=False).encode(), _key(book_id, "segments.json"), "application/json")
    blocks = sum(len(c.blocks) for c in chapters)
    set_book_status(book_id, BookStatus.SEGMENTED, f"{blocks} ta blok, {total_chars} belgi")
    attribute_book.delay(str(book_id))


def _load_segmented(book_id: uuid.UUID):
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from app.services.text.segmenter import Block, Chapter

    with TemporaryDirectory() as td:
        data = json.loads(storage.download_file(_key(book_id, "segments.json"), Path(td) / "s.json").read_text())
    return [
        Chapter(c["index"], c["title"], [Block(x["t"], x["x"], x["h"], x["e"], x["pa"], x["p"]) for x in c["blocks"]])
        for c in data
    ]


# =============================================================== 2. Personajlar va ovozlar


@celery_app.task(name="book.attribute")
@_guarded
def attribute_book(book_id: uuid.UUID) -> None:
    cfg = get_settings()
    chapters = _load_segmented(book_id)
    llm = _optional_llm()
    book_stage(book_id, "ATTRIBUTING", "Personajlar reyestri tuzilmoqda", 17)
    registry = build_registry(chapters, llm)
    book_stage(book_id, "ATTRIBUTING", f"{len(registry.characters)} ta personaj — dialoglar bogʻlanmoqda", 22)
    attributions = attribute(chapters, registry, llm)
    shares = dialogue_shares(chapters, attributions)

    with sync_session() as s:
        book = s.get(BookProject, book_id)
        s.execute(delete(BookCharacter).where(BookCharacter.book_id == book_id))
        char_rows: dict[str, BookCharacter] = {}
        for name, info in registry.characters.items():
            if shares.get(name, 0) == 0:
                continue  # gapirmaydigan personajlar
            row = BookCharacter(
                book_id=book_id, canonical_name=name[:255], aliases=info.aliases,
                gender=Gender(info.gender) if info.gender in Gender.__members__ else Gender.UNKNOWN,
                age_group=AgeGroup(info.age_group) if info.age_group in AgeGroup.__members__ else AgeGroup.UNKNOWN,
                dialogue_share=Decimal(str(shares.get(name, 0))),
            )
            s.add(row)
            char_rows[name] = row
        s.flush()

        chapter_rows = {c.chapter_index: c for c in s.execute(
            select(BookChapter).where(BookChapter.book_id == book_id)).scalars()}
        review_count = 0
        for ch in chapters:
            row = chapter_rows[ch.index]
            blocks = {b.sequence_order: b for b in s.execute(
                select(TextBlock).where(TextBlock.chapter_id == row.id)).scalars()}
            for pos, blk in enumerate(ch.blocks):
                if blk.block_type != "DIALOGUE":
                    continue
                a = attributions.get((ch.index, pos))
                tb = blocks[pos]
                if a and a.character and a.character in char_rows:
                    tb.character_id = char_rows[a.character].id
                    tb.attribution_confidence = Decimal(str(round(a.confidence, 2)))
                tb.needs_review = not a or a.confidence < cfg.attribution_review_threshold
                review_count += int(tb.needs_review)

        _assign_book_voices(s, book, list(char_rows.values()))
    set_book_status(book_id, BookStatus.ATTRIBUTED,
                    f"{len(char_rows)} ta personaj; {review_count} ta satr tekshiruv talab qiladi")
    apply_lexicon.delay(str(book_id))


def _assign_book_voices(s, book: BookProject, characters: list[BookCharacter]) -> None:
    cfg = get_settings()
    catalog = load_catalog(s, book.user_id)
    # Hikoyachi: foydalanuvchi tanlamagan boʻlsa, rejimga mos provayderdan neytral ovoz
    if book.narrator_voice_profile_id is None:
        provider = TTSProvider.GEMINI if book.tts_mode is TTSMode.BUDGET else TTSProvider.ELEVENLABS
        narrator = pick_narrator(catalog, provider) or pick_narrator(catalog, TTSProvider.GEMINI) \
            or pick_narrator(catalog, TTSProvider.ELEVENLABS)
        if narrator:
            book.narrator_voice_profile_id = uuid.UUID(narrator.profile_id)
    stats = [SpeakerStats(str(c.id), float(c.dialogue_share)) for c in characters]
    # Asosiy personajlar — dialog ulushi ≥ 5% (sozlanadi) → TIER_1
    tiers = assign_tiers(stats, book.tts_mode, primary_share=cfg.primary_character_dialogue_share,
                         secondary_share=cfg.primary_character_dialogue_share, max_primary=6)
    specs = [SpeakerSpec(str(c.id), tiers[str(c.id)], c.gender, c.age_group,
                         str(c.voice_profile_id) if c.voice_profile_id else None) for c in characters]
    reserved = [str(book.narrator_voice_profile_id)] if book.narrator_voice_profile_id else []
    assignments = assign_voices(specs, catalog, reserved_profile_ids=reserved)
    for c in characters:
        a = assignments[str(c.id)]
        c.voice_profile_id = uuid.UUID(a.primary.profile_id)
        c.tts_tier = TTSTier.TIER_1 if a.primary.provider is TTSProvider.ELEVENLABS else TTSTier.TIER_2


# =============================================================== 3. Talaffuz leksikoni


_LEXICON_SCHEMA = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"term": {"type": "STRING"}, "phonetic_uz": {"type": "STRING"}},
        "required": ["term", "phonetic_uz"]}}},
    "required": ["items"],
}
_LEXICON_SYSTEM = (
    "You write how foreign words and names in Uzbek text should be pronounced, spelled with the Uzbek "
    "Latin alphabet so an Uzbek TTS voice reads them correctly (e.g. 'Shakespeare' → 'Shekspir', "
    "'Washington' → 'Vashington', 'iPhone' → 'ayfon'). Use the established Uzbek spelling when one exists. "
    "Return one item per input term."
)


def load_lexicon(s, book_id: uuid.UUID) -> dict[str, lex.LexiconEntry]:
    rows = s.execute(select(PronunciationEntry).where(
        or_(PronunciationEntry.book_id.is_(None), PronunciationEntry.book_id == book_id))).scalars()
    priority = {LexiconSource.USER: 3, LexiconSource.GLOBAL: 2, LexiconSource.AUTO_SUGGESTED: 1}
    entries = [lex.LexiconEntry(r.term, r.phonetic_uz, priority[r.source] + (1 if r.book_id else 0))
               for r in rows if r.approved or r.source is LexiconSource.AUTO_SUGGESTED]
    return lex.merge_entries(entries)


def tts_text_for(source_text: str, entries: dict[str, lex.LexiconEntry]) -> str:
    text = lex.apply_lexicon(source_text, entries)
    text = expand_roman_numerals(text)
    text = expand_abbreviations(text)
    return expand_numbers(text)


def recompute_tts_texts(s, book_id: uuid.UUID) -> tuple[int, int]:
    """Bloklarning tts_text ini qayta hisoblaydi. Oʻzgargan sintezlangan bloklar PENDING ga qaytadi."""
    entries = load_lexicon(s, book_id)
    changed = total_chars = 0
    q = select(TextBlock).join(BookChapter).where(BookChapter.book_id == book_id)
    for tb in s.execute(q).scalars():
        new = tts_text_for(tb.source_text, entries)
        total_chars += len(new)
        if new != tb.tts_text:
            if tb.tts_text is not None and tb.status is not SegmentStatus.PENDING:
                changed += 1
                tb.status = SegmentStatus.PENDING
                tb.tts_audio_key = None
            tb.tts_text = new
    return changed, total_chars


@celery_app.task(name="book.apply_lexicon")
@_guarded
def apply_lexicon(book_id: uuid.UUID) -> None:
    book_stage(book_id, "LEXICON", "Xorijiy soʻzlar aniqlanmoqda", 31)
    with sync_session() as s:
        known = set(load_lexicon(s, book_id))
        names = {c.canonical_name.lower() for c in s.execute(
            select(BookCharacter).where(BookCharacter.book_id == book_id)).scalars()}
        texts = [t for (t,) in s.execute(select(TextBlock.source_text).join(BookChapter)
                                          .where(BookChapter.book_id == book_id))]
    candidates: dict[str, int] = defaultdict(int)
    for t in texts:
        for term in lex.find_foreign_terms(t, known):
            candidates[term] += 1
    terms = sorted(candidates, key=lambda x: -candidates[x])[:300]
    suggestions = {t: lex.transliterate_foreign(t) for t in terms}
    llm = _optional_llm()
    if llm and terms:
        try:
            for i in range(0, len(terms), 100):
                data = llm.generate_json(_LEXICON_SYSTEM, json.dumps(terms[i:i + 100], ensure_ascii=False),
                                         _LEXICON_SCHEMA, temperature=0.1)
                for item in data.get("items", []):
                    if item.get("term") in suggestions and item.get("phonetic_uz"):
                        suggestions[item["term"]] = normalize_apostrophes(item["phonetic_uz"].strip())
        except LLMError as exc:
            log.warning("Leksikon LLM xatosi: %s", exc)

    with sync_session() as s:
        for term, phon in suggestions.items():
            if term.lower() == phon.lower():
                continue
            s.add(PronunciationEntry(book_id=book_id, term=term[:255], phonetic_uz=phon[:255],
                                     source=LexiconSource.AUTO_SUGGESTED,
                                     approved=term.lower() in names))
        s.flush()
        _, total_chars = recompute_tts_texts(s, book_id)
        book = s.get(BookProject, book_id)
        _, charge = estimate_book_cost(s, book)
        book.estimated_cost_usd = charge
        book.total_chars = total_chars
    set_book_status(book_id, BookStatus.LEXICON_APPLIED,
                    f"{len(suggestions)} ta talaffuz taklifi. Taxminiy narx ${charge:.2f} — tekshirib, sintezni boshlang")


def _block_assignments(s, book: BookProject) -> tuple[dict[str, VoiceAssignment], dict[uuid.UUID, str]]:
    """Personaj → ovoz va hikoyachi ovozi; character_id → consistency key."""
    catalog = load_catalog(s, book.user_id)
    by_id = {v.profile_id: v for v in catalog}
    characters = list(s.execute(select(BookCharacter).where(BookCharacter.book_id == book.id)).scalars())
    for c in characters:
        if c.voice_profile and str(c.voice_profile_id) not in by_id:
            by_id[str(c.voice_profile_id)] = voice_option(c.voice_profile)
    if book.narrator_voice and str(book.narrator_voice_profile_id) not in by_id:
        by_id[str(book.narrator_voice_profile_id)] = voice_option(book.narrator_voice)
    narrator = by_id.get(str(book.narrator_voice_profile_id)) if book.narrator_voice_profile_id else None
    if narrator is None:
        narrator = pick_narrator(catalog, TTSProvider.GEMINI) or pick_narrator(catalog, TTSProvider.ELEVENLABS)
    if narrator is None:
        raise RuntimeError("Hikoyachi ovozi topilmadi")
    fallback_provider = TTSProvider.GEMINI if narrator.provider is TTSProvider.ELEVENLABS else TTSProvider.ELEVENLABS
    result = {NARRATOR_KEY: VoiceAssignment(narrator, pick_narrator(catalog, fallback_provider, narrator.gender))}
    specs = [SpeakerSpec(str(c.id), c.tts_tier, c.gender, c.age_group,
                         str(c.voice_profile_id) if c.voice_profile_id else None) for c in characters]
    result.update(assign_voices(specs, list(by_id.values()), reserved_profile_ids=[narrator.profile_id]))
    keys = {c.id: str(c.id) for c in characters}
    return result, keys


def estimate_book_cost(s, book: BookProject) -> tuple[Decimal, Decimal]:
    assignments, keys = _block_assignments(s, book)
    chars: dict[TTSProvider, int] = defaultdict(int)
    q = select(TextBlock).join(BookChapter).where(BookChapter.book_id == book.id,
                                                   TextBlock.status != SegmentStatus.SYNTHESIZED)
    for tb in s.execute(q).scalars():
        key = keys.get(tb.character_id, NARRATOR_KEY) if tb.block_type is BlockType.DIALOGUE else NARRATOR_KEY
        chars[assignments.get(key, assignments[NARRATOR_KEY]).primary.provider] += len(tb.tts_text or tb.source_text)
    return tts_cost.estimate(chars)


# =============================================================== 4. Sintez


@celery_app.task(name="book.synthesize")
@_guarded
def synthesize(book_id: uuid.UUID) -> None:
    router = build_router()
    available = set(router.clients)
    with sync_session() as s:
        book = s.get(BookProject, book_id)
        user_id = book.user_id
        recompute_tts_texts(s, book_id)
        assignments, keys = _block_assignments(s, book)
        q = (select(TextBlock).join(BookChapter)
             .where(BookChapter.book_id == book_id, TextBlock.status != SegmentStatus.SYNTHESIZED)
             .order_by(BookChapter.chapter_index, TextBlock.sequence_order))
        items: list[SynthItem] = []
        chars: dict[TTSProvider, int] = defaultdict(int)
        for tb in s.execute(q).scalars():
            key = keys.get(tb.character_id, NARRATOR_KEY) if tb.block_type is BlockType.DIALOGUE else NARRATOR_KEY
            a = effective_assignment(assignments.get(key, assignments[NARRATOR_KEY]), available)
            text = tb.tts_text or tb.source_text
            if not re.search(r"\w", text):
                continue
            chars[a.primary.provider] += len(text)
            items.append(SynthItem(tb.id, text, tb.emotion_tag, a, key,
                                   _key(book_id, f"tts/{tb.id}-{uuid.uuid4().hex[:6]}")))
        _, charge = tts_cost.estimate(chars)
        held = Decimal("0")
        if charge > 0:
            billing.hold(s, user_id, charge, book_project_id=book_id)
            held = charge
        book.estimated_cost_usd = charge
    events.publish("book", book_id, "cost", stage="TTS", message=f"Rezerv ${charge:.4f}",
                   data={"estimate_usd": float(charge)})

    total = len(items)
    state = {"n": 0, "api": Decimal("0"), "failed": 0}

    def on_done(o: SynthOutcome) -> None:
        state["n"] += 1
        with sync_session() as s2:
            tb = s2.get(TextBlock, o.item.item_id)
            record_job(s2, user_id, o, text_block_id=o.item.item_id)
            if o.routed:
                state["api"] += o.routed.api_cost_usd
                tb.tts_audio_key, tb.duration_ms, tb.status = o.storage_key, o.duration_ms, SegmentStatus.SYNTHESIZED
            else:
                state["failed"] += 1
                tb.status = SegmentStatus.FAILED
        if state["n"] % 5 == 0 or state["n"] == total or not o.routed:
            events.publish("book", book_id, "block", stage="TTS",
                           progress=interpolate(35, 85, state["n"] / max(total, 1)),
                           message=f"Sintez: {state['n']}/{total}",
                           data={"block_id": str(o.item.item_id), "error": o.error,
                                 "spent_usd": float(tts_cost.customer_charge(state["api"]))})

    try:
        with workdir("book-tts", book_id) as wd:
            synthesize_many(router, items, workdir=wd, on_done=on_done)
    finally:
        actual = tts_cost.customer_charge(state["api"])
        with sync_session() as s:
            billing.settle(s, user_id, held, actual, book_project_id=book_id)
        events.publish("book", book_id, "cost", stage="TTS", message=f"Yakuniy narx ${actual:.4f}",
                       data={"charged_usd": float(actual)})
    if state["failed"]:
        raise RuntimeError(f"{state['failed']} ta blok sintez qilinmadi — qayta urinib koʻring")
    set_book_status(book_id, BookStatus.TTS_DISPATCHED, f"{total} ta blok ovozlashtirildi")
    stitch.delay(str(book_id))


# =============================================================== 5. Birlashtirish va eksport


@celery_app.task(name="book.stitch")
@_guarded
def stitch(book_id: uuid.UUID) -> None:
    with sync_session() as s:
        book = s.get(BookProject, book_id)
        title, author = book.title, book.author
        chapters = [(c.id, c.chapter_index, c.title, [(b.tts_audio_key, b.pause_after_ms) for b in c.blocks])
                    for c in book.chapters]
    with workdir("stitch", book_id) as wd:
        chapter_wavs, marks, mp3s = [], [], []
        cursor_ms = 0
        silence_cache: dict[int, object] = {}
        for n, (cid, idx, ch_title, blocks) in enumerate(chapters):
            parts = []
            for i, (key, pause) in enumerate(blocks):
                if not key:
                    continue
                raw = storage.download_file(key, wd / f"c{idx}" / f"{i}{'.' + key.rsplit('.', 1)[-1]}")
                parts.append(ffmpeg.to_wav(raw, wd / f"c{idx}" / f"{i}.norm.wav", channels=1))
                if pause > 0:
                    if pause not in silence_cache:
                        silence_cache[pause] = ffmpeg.make_silence(wd / f"silence_{pause}.wav", pause / 1000)
                    parts.append(silence_cache[pause])
            if not parts:
                continue
            joined = ffmpeg.concat_wavs(parts, wd / f"chapter_{idx}.raw.wav", wd)
            final = ffmpeg.loudnorm(joined, wd / f"chapter_{idx}.wav", integrated=mixing.BOOK_LOUDNESS_LUFS)
            dur_ms = int(ffmpeg.duration_seconds(final) * 1000)
            label = ch_title or ("Kirish" if n == 0 else f"{idx}-qism")
            mp3 = mixing.export_mp3(final, wd / f"{idx:03d}.mp3", label, track=idx, album=title)
            key = storage.upload_file(mp3, _key(book_id, f"chapters/{idx:03d}.mp3"), "audio/mpeg")
            with sync_session() as s:
                row = s.get(BookChapter, cid)
                row.audio_key, row.duration_ms = key, dur_ms
            chapter_wavs.append(final)
            mp3s.append(mp3)
            marks.append(mixing.ChapterMark(label, cursor_ms, cursor_ms + dur_ms))
            cursor_ms += dur_ms
            book_stage(book_id, "STITCHING", f"Bob {n + 1}/{len(chapters)} tayyor",
                       interpolate(85, 95, (n + 1) / max(len(chapters), 1)))
        if not chapter_wavs:
            raise RuntimeError("Birlashtirish uchun audio yoʻq")
        set_book_status(book_id, BookStatus.STITCHED, "Boblar birlashtirildi")
        m4b = mixing.export_m4b(chapter_wavs, marks, title, author, wd / "book.m4b", wd)
        zip_path = wd / "chapters.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for mp3 in mp3s:
                zf.write(mp3, mp3.name)
        m4b_key = storage.upload_file(m4b, _key(book_id, "output/book.m4b"), "audio/mp4")
        zip_key = storage.upload_file(zip_path, _key(book_id, "output/chapters.zip"), "application/zip")
    with sync_session() as s:
        book = s.get(BookProject, book_id)
        book.output_m4b_key, book.output_zip_key = m4b_key, zip_key
    set_book_status(book_id, BookStatus.READY_FOR_EXPORT, f"«{title}» audiokitobi tayyor")
