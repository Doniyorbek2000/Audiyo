"""Kitob / uzun matn loyihalari: yuklash, boblar, bloklar, personajlar, leksikon, narx, sintez, eksport."""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app import events, storage
from app.deps import BookDep, SessionDep, UserDep
from app.models import (
    BlockType,
    BookChapter,
    BookCharacter,
    BookProject,
    BookScene,
    BookStatus,
    LexiconSource,
    PronunciationEntry,
    SegmentStatus,
    TextBlock,
    TTSMode,
    TTSTier,
    TTSProvider,
    VoiceProfile,
)
from app.schemas import (
    ActionOut,
    BlockOut,
    BlockPage,
    BlockPatch,
    BookExportOut,
    BookOut,
    BookPatch,
    ChapterOut,
    CharacterCreate,
    CharacterOut,
    CharacterPatch,
    EstimateOut,
    LexiconIn,
    LexiconOut,
    LexiconPatch,
    SceneOut,
    ScenePatch,
    VoiceOut,
)
from app.services.text.parsers import SUPPORTED_FORMATS, UnsupportedFormat, detect_format
from app.services.text.segmenter import split_long_text
from app.services.text.uzbek import normalize_apostrophes

router = APIRouter(prefix="/books", tags=["books"])

EDITABLE = {BookStatus.ATTRIBUTED, BookStatus.LEXICON_APPLIED, BookStatus.READY_FOR_EXPORT, BookStatus.FAILED}
MAX_BOOK_BYTES = 50 * 1024 * 1024


def _tasks():
    from app.workers import book_tasks

    return book_tasks


def _voice_out(v: VoiceProfile | None) -> VoiceOut | None:
    if v is None:
        return None
    out = VoiceOut.model_validate(v)
    out.is_system = v.user_id is None
    return out


def _block_out(b: TextBlock) -> BlockOut:
    out = BlockOut.model_validate(b)
    out.audio_url = storage.presigned_url(b.tts_audio_key)
    return out


def _ensure_editable(book: BookProject) -> None:
    if book.status not in EDITABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Kitob hali qayta ishlanmoqda — tugashini kuting")


async def _check_voice(session, voice_id: uuid.UUID | None, user_id: uuid.UUID) -> VoiceProfile | None:
    if voice_id is None:
        return None
    vp = await session.get(VoiceProfile, voice_id)
    if vp is None or vp.user_id not in (None, user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ovoz topilmadi")
    return vp


# ------------------------------------------------------------------ CRUD


@router.post("/upload", response_model=BookOut, status_code=201)
async def upload_book(
    user: UserDep,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="EPUB, FB2, DOCX, PDF yoki TXT")],
    title: Annotated[str | None, Form(max_length=255)] = None,
    author: Annotated[str | None, Form(max_length=255)] = None,
    tts_mode: Annotated[TTSMode, Form()] = TTSMode.BALANCED,
) -> BookProject:
    try:
        fmt = detect_format(file.filename or "")
    except UnsupportedFormat:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Qoʻllab-quvvatlanadigan formatlar: {', '.join(sorted(SUPPORTED_FORMATS))}") from None
    data = await file.read()
    if len(data) > MAX_BOOK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fayl 50 MB dan katta")
    book_id = uuid.uuid4()
    key = f"books/{book_id}/source.{fmt}"
    await run_in_threadpool(storage.upload_bytes, data, key, file.content_type)
    book = BookProject(id=book_id, user_id=user.id, title=(title or Path(file.filename or "Kitob").stem)[:255],
                       author=author, source_file_key=key, source_format=fmt, tts_mode=tts_mode)
    session.add(book)
    await session.commit()
    await session.refresh(book)
    _tasks().start_pipeline(book_id)
    return book


@router.get("", response_model=list[BookOut])
async def list_books(user: UserDep, session: SessionDep) -> list[BookProject]:
    q = select(BookProject).where(BookProject.user_id == user.id).order_by(BookProject.created_at.desc())
    return list((await session.scalars(q)).unique().all())


@router.get("/{book_id}", response_model=BookOut)
async def get_book(book: BookDep) -> BookProject:
    return book


@router.patch("/{book_id}", response_model=BookOut)
async def patch_book(book: BookDep, body: BookPatch, session: SessionDep) -> BookProject:
    data = body.model_dump(exclude_unset=True)
    if "narrator_voice_profile_id" in data and data["narrator_voice_profile_id"] != book.narrator_voice_profile_id:
        _ensure_editable(book)
        await _check_voice(session, data["narrator_voice_profile_id"], book.user_id)
        # Hikoyachi ovozi oʻzgardi → hikoya bloklari qayta sintez qilinadi
        chapter_ids = select(BookChapter.id).where(BookChapter.book_id == book.id)
        await session.execute(update(TextBlock).where(
            TextBlock.chapter_id.in_(chapter_ids),
            or_(TextBlock.block_type != BlockType.DIALOGUE, TextBlock.character_id.is_(None)),
        ).values(status=SegmentStatus.PENDING, tts_audio_key=None))
    for field, value in data.items():
        setattr(book, field, value)
    await session.commit()
    await session.refresh(book)
    return book


@router.delete("/{book_id}", status_code=204)
async def delete_book(book: BookDep, session: SessionDep) -> None:
    await session.execute(delete(BookProject).where(BookProject.id == book.id))
    await session.commit()


# ------------------------------------------------------------------ boblar va bloklar


@router.get("/{book_id}/chapters", response_model=list[ChapterOut])
async def chapters(book: BookDep, session: SessionDep) -> list[ChapterOut]:
    stats = {
        r[0]: r[1:]
        for r in (await session.execute(
            select(
                TextBlock.chapter_id,
                func.count(),
                func.sum(case((TextBlock.needs_review, 1), else_=0)),
                func.sum(case((TextBlock.status == SegmentStatus.SYNTHESIZED, 1), else_=0)),
            ).join(BookChapter).where(BookChapter.book_id == book.id).group_by(TextBlock.chapter_id)
        )).all()
    }
    rows = (await session.scalars(select(BookChapter).where(BookChapter.book_id == book.id)
                                  .order_by(BookChapter.chapter_index))).all()
    out = []
    for c in rows:
        o = ChapterOut.model_validate(c)
        total, review, done = stats.get(c.id, (0, 0, 0))
        o.block_count, o.review_count, o.synthesized_count = int(total), int(review or 0), int(done or 0)
        o.audio_url = storage.presigned_url(c.audio_key)
        out.append(o)
    return out


@router.get("/{book_id}/blocks", response_model=BlockPage)
async def blocks(
    book: BookDep,
    session: SessionDep,
    chapter: Annotated[int | None, Query(description="chapter_index")] = None,
    needs_review: bool | None = None,
    character_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> BlockPage:
    q = select(TextBlock).join(BookChapter).where(BookChapter.book_id == book.id)
    if chapter is not None:
        q = q.where(BookChapter.chapter_index == chapter)
    if needs_review is not None:
        q = q.where(TextBlock.needs_review.is_(needs_review))
    if character_id is not None:
        q = q.where(TextBlock.character_id == character_id)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.scalars(q.order_by(BookChapter.chapter_index, TextBlock.sequence_order)
                                  .offset(offset).limit(limit))).all()
    return BlockPage(items=[_block_out(b) for b in rows], total=total or 0)


@router.patch("/{book_id}/blocks/{block_id}", response_model=list[BlockOut])
async def patch_block(book: BookDep, block_id: uuid.UUID, body: BlockPatch, session: SessionDep) -> list[BlockOut]:
    """Blokni tahrirlash. Matn 2000 belgidan oshsa, blok avtomatik boʻlinadi (roʻyxat qaytadi)."""
    _ensure_editable(book)
    tb = await session.get(TextBlock, block_id)
    chapter = await session.get(BookChapter, tb.chapter_id) if tb else None
    if tb is None or chapter is None or chapter.book_id != book.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blok topilmadi")
    data = body.model_dump(exclude_unset=True)
    resynth = False
    if data.get("character_id"):
        ch = await session.get(BookCharacter, data["character_id"])
        if ch is None or ch.book_id != book.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Personaj topilmadi")
        if ch.id != tb.character_id:
            tb.character_id, tb.block_type, resynth = ch.id, BlockType.DIALOGUE, True
        tb.needs_review = False
        tb.attribution_confidence = Decimal("1.00")
    if data.get("clear_character"):
        tb.character_id, tb.needs_review, resynth = None, False, True
    if data.get("block_type") and data["block_type"] != tb.block_type:
        tb.block_type, resynth = data["block_type"], True
    if data.get("emotion_tag") and data["emotion_tag"] != tb.emotion_tag:
        tb.emotion_tag, resynth = data["emotion_tag"], True
    if "delivery" in data and ((data["delivery"] or "").strip() or None) != tb.delivery:
        tb.delivery, resynth = (data["delivery"] or "").strip() or None, True
    if "pause_after_ms" in data and data["pause_after_ms"] is not None:
        tb.pause_after_ms = data["pause_after_ms"]  # faqat stitching ga taʼsir qiladi
    if "needs_review" in data and data["needs_review"] is not None:
        tb.needs_review = data["needs_review"]

    created: list[TextBlock] = []
    if data.get("source_text"):
        text = normalize_apostrophes(data["source_text"].strip())
        if text != tb.source_text:
            pieces = split_long_text(text)
            tb.source_text, tb.tts_text, resynth = pieces[0], None, True
            if len(pieces) > 1:
                # Keyingi bloklarni surish va yangilarini qoʻshish
                await session.execute(update(TextBlock).where(
                    TextBlock.chapter_id == chapter.id, TextBlock.sequence_order > tb.sequence_order
                ).values(sequence_order=TextBlock.sequence_order + 10000))
                await session.flush()
                for i, piece in enumerate(pieces[1:], 1):
                    nb = TextBlock(chapter_id=chapter.id, sequence_order=tb.sequence_order + i,
                                   block_type=tb.block_type, character_id=tb.character_id, source_text=piece,
                                   emotion_tag=tb.emotion_tag, pause_after_ms=tb.pause_after_ms)
                    session.add(nb)
                    created.append(nb)
                tb.pause_after_ms = 300
                await session.flush()
                await session.execute(update(TextBlock).where(
                    TextBlock.chapter_id == chapter.id, TextBlock.sequence_order > 10000
                ).values(sequence_order=TextBlock.sequence_order - 10000 + len(created)))
    if resynth:
        tb.status, tb.tts_audio_key = SegmentStatus.PENDING, None
    await session.commit()
    if any(k in data for k in ("source_text",)):
        await session.run_sync(lambda s: _tasks().recompute_tts_texts(s, book.id))
        await session.commit()
    for b in [tb, *created]:
        await session.refresh(b)
    return [_block_out(b) for b in [tb, *created]]


# ------------------------------------------------------------------ personajlar


async def _character_out(session, c: BookCharacter) -> CharacterOut:
    o = CharacterOut.model_validate(c)
    o.voice = _voice_out(await session.get(VoiceProfile, c.voice_profile_id) if c.voice_profile_id else None)
    return o


@router.get("/{book_id}/characters", response_model=list[CharacterOut])
async def characters(book: BookDep, session: SessionDep) -> list[CharacterOut]:
    rows = (await session.scalars(select(BookCharacter).where(BookCharacter.book_id == book.id)
                                  .order_by(BookCharacter.dialogue_share.desc()))).unique().all()
    return [await _character_out(session, c) for c in rows]


@router.post("/{book_id}/characters", response_model=CharacterOut, status_code=201)
async def create_character(book: BookDep, body: CharacterCreate, session: SessionDep) -> CharacterOut:
    _ensure_editable(book)
    c = BookCharacter(book_id=book.id, canonical_name=body.canonical_name.strip(), aliases=[],
                      gender=body.gender, age_group=body.age_group, tts_tier=TTSTier.TIER_2)
    session.add(c)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bunday personaj mavjud") from None
    await session.refresh(c)
    return await _character_out(session, c)


@router.patch("/{book_id}/characters/{character_id}", response_model=CharacterOut | None)
async def patch_character(book: BookDep, character_id: uuid.UUID, body: CharacterPatch, session: SessionDep):
    _ensure_editable(book)
    c = await session.get(BookCharacter, character_id)
    if c is None or c.book_id != book.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personaj topilmadi")
    data = body.model_dump(exclude_unset=True)
    chapter_ids = select(BookChapter.id).where(BookChapter.book_id == book.id)

    if data.get("merge_into_id"):
        target = await session.get(BookCharacter, data["merge_into_id"])
        if target is None or target.book_id != book.id or target.id == c.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Birlashtirish uchun personaj topilmadi")
        await session.execute(update(TextBlock).where(TextBlock.chapter_id.in_(chapter_ids),
                                                      TextBlock.character_id == c.id)
                              .values(character_id=target.id, status=SegmentStatus.PENDING, tts_audio_key=None))
        target.aliases = sorted({*target.aliases, c.canonical_name, *c.aliases} - {target.canonical_name})
        target.dialogue_share = target.dialogue_share + c.dialogue_share
        await session.delete(c)
        await session.commit()
        return None

    if "voice_profile_id" in data and data["voice_profile_id"] != c.voice_profile_id:
        vp = await _check_voice(session, data["voice_profile_id"], book.user_id)
        c.voice_profile_id = data["voice_profile_id"]
        if vp:
            c.tts_tier = TTSTier.TIER_1 if vp.provider is TTSProvider.ELEVENLABS else TTSTier.TIER_2
        await session.execute(update(TextBlock).where(TextBlock.chapter_id.in_(chapter_ids),
                                                      TextBlock.character_id == c.id)
                              .values(status=SegmentStatus.PENDING, tts_audio_key=None))
    for field in ("canonical_name", "aliases", "gender", "age_group"):
        if field in data and data[field] is not None:
            setattr(c, field, data[field])
    await session.commit()
    await session.refresh(c)
    return await _character_out(session, c)


# ------------------------------------------------------------------ muhit sahnalari


def _scene_out(sc: BookScene, chapter_index: int) -> SceneOut:
    o = SceneOut.model_validate(sc)
    o.chapter_index = chapter_index
    o.has_audio = bool(sc.sfx_key)
    o.preview_url = storage.presigned_url(sc.sfx_key)
    return o


@router.get("/{book_id}/scenes", response_model=list[SceneOut])
async def scenes(book: BookDep, session: SessionDep) -> list[SceneOut]:
    rows = (await session.execute(
        select(BookScene, BookChapter.chapter_index).join(BookChapter, BookChapter.id == BookScene.chapter_id)
        .where(BookChapter.book_id == book.id).order_by(BookChapter.chapter_index, BookScene.start_seq))).all()
    return [_scene_out(sc, idx) for sc, idx in rows]


@router.patch("/{book_id}/scenes/{scene_id}", response_model=SceneOut)
async def patch_scene(book: BookDep, scene_id: uuid.UUID, body: ScenePatch, session: SessionDep) -> SceneOut:
    _ensure_editable(book)
    sc = await session.get(BookScene, scene_id)
    chapter = await session.get(BookChapter, sc.chapter_id) if sc else None
    if sc is None or chapter is None or chapter.book_id != book.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sahna topilmadi")
    data = body.model_dump(exclude_unset=True)
    if data.get("ambience_prompt") and data["ambience_prompt"].strip() != sc.ambience_prompt:
        sc.ambience_prompt, sc.sfx_key = data["ambience_prompt"].strip(), None  # yangi tovush yaratiladi
    for field in ("label", "intensity", "enabled"):
        if field in data and data[field] is not None:
            setattr(sc, field, data[field])
    await session.commit()
    await session.refresh(sc)
    return _scene_out(sc, chapter.chapter_index)


@router.post("/{book_id}/restitch", response_model=ActionOut, status_code=202)
async def restitch(book: BookDep, session: SessionDep) -> ActionOut:
    """Sahna yoki pauza oʻzgargandan soʻng audioni qayta yigʻish (TTS qayta chaqirilmaydi)."""
    if book.status not in (BookStatus.READY_FOR_EXPORT, BookStatus.FAILED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Avval sintezni yakunlang")
    book.status, book.error_message = BookStatus.TTS_DISPATCHED, None
    await session.commit()
    _tasks().stitch.delay(str(book.id))
    return ActionOut(status="queued", message="Audiokitob qayta yigʻilmoqda")


# ------------------------------------------------------------------ leksikon


@router.get("/{book_id}/lexicon", response_model=list[LexiconOut])
async def lexicon(book: BookDep, session: SessionDep, include_global: bool = False) -> list[PronunciationEntry]:
    cond = PronunciationEntry.book_id == book.id
    if include_global:
        cond = or_(cond, PronunciationEntry.book_id.is_(None))
    q = select(PronunciationEntry).where(cond).order_by(PronunciationEntry.approved, PronunciationEntry.term)
    return list((await session.scalars(q)).all())


async def _reapply_lexicon(session, book: BookProject) -> None:
    await session.run_sync(lambda s: _tasks().recompute_tts_texts(s, book.id))
    await session.commit()


@router.post("/{book_id}/lexicon", response_model=LexiconOut, status_code=201)
async def add_lexicon(book: BookDep, body: LexiconIn, session: SessionDep) -> PronunciationEntry:
    _ensure_editable(book)
    existing = await session.scalar(select(PronunciationEntry).where(
        PronunciationEntry.book_id == book.id, func.lower(PronunciationEntry.term) == body.term.lower()))
    if existing:
        existing.phonetic_uz, existing.source, existing.approved = body.phonetic_uz, LexiconSource.USER, True
        entry = existing
    else:
        entry = PronunciationEntry(book_id=book.id, term=body.term.strip(),
                                   phonetic_uz=normalize_apostrophes(body.phonetic_uz.strip()),
                                   source=LexiconSource.USER, approved=True)
        session.add(entry)
    await session.commit()
    await _reapply_lexicon(session, book)
    await session.refresh(entry)
    return entry


@router.patch("/{book_id}/lexicon/{entry_id}", response_model=LexiconOut)
async def patch_lexicon(book: BookDep, entry_id: uuid.UUID, body: LexiconPatch, session: SessionDep) -> PronunciationEntry:
    _ensure_editable(book)
    entry = await session.get(PronunciationEntry, entry_id)
    if entry is None or entry.book_id != book.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    if body.phonetic_uz is not None:
        entry.phonetic_uz = normalize_apostrophes(body.phonetic_uz.strip())
        entry.source = LexiconSource.USER
        entry.approved = True
    if body.approved is not None:
        entry.approved = body.approved
    await session.commit()
    await _reapply_lexicon(session, book)
    await session.refresh(entry)
    return entry


@router.delete("/{book_id}/lexicon/{entry_id}", status_code=204)
async def delete_lexicon(book: BookDep, entry_id: uuid.UUID, session: SessionDep) -> None:
    _ensure_editable(book)
    entry = await session.get(PronunciationEntry, entry_id)
    if entry is None or entry.book_id != book.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    await session.delete(entry)
    await session.commit()
    await _reapply_lexicon(session, book)


# ------------------------------------------------------------------ narx, sintez, eksport


def _parse_chapters(chapters: str | None) -> list[int] | None:
    if not chapters:
        return None
    try:
        out = sorted({int(x) for x in chapters.replace(" ", "").split(",") if x})
    except ValueError:
        raise HTTPException(422, "chapters: vergul bilan ajratilgan bob raqamlari, masalan 1,2") from None
    return out or None


@router.get("/{book_id}/estimate", response_model=EstimateOut)
async def estimate(
    book: BookDep, user: UserDep, session: SessionDep,
    chapters: Annotated[str | None, Query(description="Faqat shu boblar, masalan 1,2")] = None,
) -> EstimateOut:
    only = _parse_chapters(chapters)
    if book.status in (BookStatus.UPLOADED, BookStatus.PARSED, BookStatus.NORMALIZED, BookStatus.SEGMENTED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Kitob hali tahlil qilinmoqda")

    def compute(s):
        from app.services.tts import cost as tts_cost

        t = _tasks()
        assignments, keys = t._block_assignments(s, s.get(BookProject, book.id))
        chars: dict[TTSProvider, int] = defaultdict(int)
        q = select(TextBlock).join(BookChapter).where(BookChapter.book_id == book.id,
                                                       TextBlock.status != SegmentStatus.SYNTHESIZED)
        if only:
            q = q.where(BookChapter.chapter_index.in_(only))
        for tb in s.execute(q).scalars():
            key = keys.get(tb.character_id, t.NARRATOR_KEY) if tb.block_type is BlockType.DIALOGUE else t.NARRATOR_KEY
            a = assignments.get(key, assignments[t.NARRATOR_KEY])
            chars[a.primary.provider] += len(tb.tts_text or tb.source_text)
        api, charge = tts_cost.estimate(chars)
        return chars, api, charge

    chars, api, charge = await session.run_sync(compute)
    await session.refresh(user)
    return EstimateOut(
        total_chars=sum(chars.values()),
        chars_by_provider={p.value: n for p, n in chars.items()},
        api_cost_usd=api,
        charge_usd=charge,
        balance_usd=user.credit_balance_usd,
        sufficient=user.credit_balance_usd >= charge,
    )


@router.post("/{book_id}/synthesize", response_model=ActionOut, status_code=202)
async def synthesize(
    book: BookDep, user: UserDep, session: SessionDep,
    chapters: Annotated[str | None, Query(description="Faqat shu boblar, masalan 1,2")] = None,
) -> ActionOut:
    if book.status not in (BookStatus.LEXICON_APPLIED, BookStatus.READY_FOR_EXPORT, BookStatus.FAILED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Sintezni hozir boshlab boʻlmaydi")
    est = await estimate(book, user, session, chapters)
    if not est.sufficient:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                            f"Kredit yetarli emas: kerak ${est.charge_usd:.2f}, balans ${est.balance_usd:.2f}")
    if book.status is BookStatus.FAILED:
        book.status, book.error_message = BookStatus.LEXICON_APPLIED, None
        await session.commit()
    _tasks().synthesize.delay(str(book.id), chapters=_parse_chapters(chapters))
    return ActionOut(status="queued", message=f"Sintez boshlandi (taxminan ${est.charge_usd:.2f})")


@router.post("/{book_id}/retry", response_model=ActionOut, status_code=202)
async def retry(book: BookDep, session: SessionDep) -> ActionOut:
    if book.status is not BookStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Faqat FAILED kitobni qayta ishga tushirish mumkin")
    t = _tasks()
    n_chapters = await session.scalar(select(func.count()).select_from(BookChapter)
                                      .where(BookChapter.book_id == book.id))
    n_chars = await session.scalar(select(func.count()).select_from(BookCharacter)
                                   .where(BookCharacter.book_id == book.id))
    pending = await session.scalar(select(func.count()).select_from(TextBlock).join(BookChapter).where(
        BookChapter.book_id == book.id, TextBlock.status != SegmentStatus.SYNTHESIZED))
    has_tts_text = await session.scalar(select(func.count()).select_from(TextBlock).join(BookChapter)
                                        .where(BookChapter.book_id == book.id, TextBlock.tts_text.is_not(None)))
    # Holat xato oldidagi bosqichga qaytariladi, shunda UI va SSE jarayonni toʻgʻri koʻrsatadi
    if not n_chapters:
        task, resume = t.prepare, BookStatus.UPLOADED
    elif not n_chars and not has_tts_text:
        task, resume = t.attribute_book, BookStatus.SEGMENTED
    elif not has_tts_text:
        task, resume = t.apply_lexicon, BookStatus.ATTRIBUTED
    elif pending:
        task, resume = t.synthesize, BookStatus.LEXICON_APPLIED
    else:
        task, resume = t.stitch, BookStatus.TTS_DISPATCHED
    book.status, book.error_message = resume, None
    await session.commit()
    task.delay(str(book.id))
    return ActionOut(status="queued", message="Qayta ishga tushirildi")


@router.get("/{book_id}/export", response_model=BookExportOut)
async def export(book: BookDep, session: SessionDep) -> BookExportOut:
    if book.status is not BookStatus.READY_FOR_EXPORT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Audiokitob hali tayyor emas")
    base = "".join(c for c in book.title if c.isalnum() or c in " -_").strip() or "audiokitob"
    rows = (await session.scalars(select(BookChapter).where(BookChapter.book_id == book.id)
                                  .order_by(BookChapter.chapter_index))).all()
    return BookExportOut(
        m4b=storage.presigned_url(book.output_m4b_key, f"{base}.m4b"),
        chapters_zip=storage.presigned_url(book.output_zip_key, f"{base}.zip"),
        chapters=[{"index": c.chapter_index, "title": c.title, "duration_ms": c.duration_ms,
                   "mp3": storage.presigned_url(c.audio_key, f"{c.chapter_index:03d}.mp3")} for c in rows],
    )


@router.get("/{book_id}/events")
async def book_events(book: BookDep, request: Request) -> StreamingResponse:
    snapshot = events.build_event("book", str(book.id), "snapshot", status=book.status.value,
                                  progress=float(book.progress), message=book.error_message)

    async def stream():
        yield f"event: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        async for message in events.subscribe("book", str(book.id)):
            if await request.is_disconnected():
                break
            if message is None:
                yield ": keep-alive\n\n"
                continue
            yield f"event: {json.loads(message).get('type', 'message')}\ndata: {message}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
