"""Video loyihalar: yuklash, vaqt jadvali, segment/spiker tahriri, qayta render, eksport, SSE."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select

from app import events, storage
from app.config import get_settings
from app.deps import ProjectDep, SessionDep, UserDep
from app.models import (
    DialogueSegment,
    MediaProject,
    ProjectStatus,
    SegmentStatus,
    Speaker,
    TTSJob,
    TTSMode,
    VoiceProfile,
)
from app.schemas import (
    ActionOut,
    ExportOut,
    ProjectOut,
    ProjectPatch,
    SegmentOut,
    SegmentPatch,
    SpeakerOut,
    SpeakerPatch,
    StemsOut,
    TimelineOut,
    VoiceOut,
)
from app.services.llm.translation import syllable_budget
from app.services.text.uzbek import count_syllables_uz, normalize_apostrophes

router = APIRouter(prefix="/projects", tags=["projects"])

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".flac"}
# Konveyer toʻxtagan holatlar (tahrir va qayta render mumkin)
IDLE_STATUSES = {ProjectStatus.TRANSLATED, ProjectStatus.READY_FOR_EXPORT, ProjectStatus.FAILED}


def _tasks():
    from app.workers import video_tasks

    return video_tasks


def _voice_out(v: VoiceProfile | None) -> VoiceOut | None:
    if v is None:
        return None
    out = VoiceOut.model_validate(v)
    out.is_system = v.user_id is None
    return out


def _segment_out(seg: DialogueSegment) -> SegmentOut:
    out = SegmentOut.model_validate(seg)
    out.max_syllables = syllable_budget(seg.target_duration_ms, get_settings().atempo_max)[1]
    out.audio_url = storage.presigned_url(seg.aligned_audio_key or seg.tts_audio_key)
    return out


# ------------------------------------------------------------------ CRUD


@router.post("/upload", response_model=ProjectOut, status_code=201)
async def upload_project(
    user: UserDep,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="Video yoki audio fayl")],
    title: Annotated[str | None, Form(max_length=255)] = None,
    source_language: Annotated[str, Form(max_length=10)] = "auto",
    tts_mode: Annotated[TTSMode, Form()] = TTSMode.BALANCED,
    review_before_tts: Annotated[bool, Form()] = False,
) -> MediaProject:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Qoʻllab-quvvatlanadigan formatlar: {', '.join(sorted(VIDEO_EXTENSIONS))}")
    project_id = uuid.uuid4()
    key = f"projects/{project_id}/source{ext}"
    await run_in_threadpool(storage.upload_fileobj, file.file, key, file.content_type)
    project = MediaProject(
        id=project_id,
        user_id=user.id,
        title=(title or Path(file.filename or "Loyiha").stem)[:255],
        source_language=source_language.lower(),
        tts_mode=tts_mode,
        review_before_tts=review_before_tts,
        source_video_key=key,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    _tasks().start_pipeline(project_id)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: UserDep, session: SessionDep) -> list[MediaProject]:
    q = select(MediaProject).where(MediaProject.user_id == user.id).order_by(MediaProject.created_at.desc())
    return list((await session.scalars(q)).all())


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project: ProjectDep) -> MediaProject:
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def patch_project(project: ProjectDep, body: ProjectPatch, session: SessionDep) -> MediaProject:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await session.commit()
    await session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project: ProjectDep, session: SessionDep) -> None:
    await session.execute(delete(MediaProject).where(MediaProject.id == project.id))
    await session.commit()


# ------------------------------------------------------------------ vaqt jadvali


async def _pending_changes(session, project_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(DialogueSegment).where(
            DialogueSegment.project_id == project_id,
            DialogueSegment.status.in_([SegmentStatus.TRANSLATED, SegmentStatus.SYNTHESIZED, SegmentStatus.FAILED]),
        )
    ) or 0


@router.get("/{project_id}/timeline", response_model=TimelineOut)
async def timeline(project: ProjectDep, session: SessionDep) -> TimelineOut:
    speakers = (await session.scalars(
        select(Speaker).where(Speaker.project_id == project.id).order_by(Speaker.speaker_tag))).unique().all()
    segments = (await session.scalars(
        select(DialogueSegment).where(DialogueSegment.project_id == project.id)
        .order_by(DialogueSegment.start_time))).all()
    speaker_out = []
    for sp in speakers:
        o = SpeakerOut.model_validate(sp)
        o.sample_url = storage.presigned_url(sp.sample_audio_key)
        o.voice = _voice_out(sp.voice_profile)
        speaker_out.append(o)
    return TimelineOut(
        project=ProjectOut.model_validate(project),
        duration=float(project.duration_seconds) if project.duration_seconds else None,
        stems=StemsOut(
            original=storage.presigned_url(project.original_audio_key),
            vocals=storage.presigned_url(project.isolated_vocal_key),
            bgm=storage.presigned_url(project.isolated_bgm_key),
            dubbed_dialogue=storage.presigned_url(project.dubbed_dialogue_key),
            dubbed_mix=storage.presigned_url(project.dubbed_mix_key),
        ),
        peaks=project.waveform_peaks,
        speakers=speaker_out,
        segments=[_segment_out(s) for s in segments],
        pending_changes=await _pending_changes(session, project.id),
        video_url=storage.presigned_url(project.dubbed_video_key or project.source_video_key),
        poster_url=storage.presigned_url(project.poster_key),
    )


# ------------------------------------------------------------------ segment tahriri


@router.patch("/{project_id}/segments/{segment_id}", response_model=SegmentOut)
async def patch_segment(
    project: ProjectDep, segment_id: uuid.UUID, body: SegmentPatch, session: SessionDep
) -> SegmentOut:
    seg = await session.get(DialogueSegment, segment_id)
    if seg is None or seg.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment topilmadi")
    data = body.model_dump(exclude_unset=True)
    needs_synth = needs_align = False

    if "translated_text_uz" in data and data["translated_text_uz"] is not None:
        text = normalize_apostrophes(data["translated_text_uz"].strip())
        if text != (seg.translated_text_uz or ""):
            seg.translated_text_uz = text
            seg.target_syllables = count_syllables_uz(text)
            seg.manual_override_flags = True
            needs_synth = True
    if "emotion_tag" in data and data["emotion_tag"] and data["emotion_tag"] != seg.emotion_tag:
        seg.emotion_tag = data["emotion_tag"]
        needs_synth = True
    if "delivery" in data and (data["delivery"] or None) != seg.delivery:
        seg.delivery = (data["delivery"] or "").strip() or None
        needs_synth = True
    if "speaker_id" in data and data["speaker_id"] != seg.speaker_id:
        if data["speaker_id"] is not None:
            sp = await session.get(Speaker, data["speaker_id"])
            if sp is None or sp.project_id != project.id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Spiker bu loyihaga tegishli emas")
        seg.speaker_id = data["speaker_id"]
        needs_synth = True
    start = data.get("start_time", seg.start_time) or seg.start_time
    end = data.get("end_time", seg.end_time) or seg.end_time
    if end <= start:
        raise HTTPException(422, "end_time start_time dan katta boʻlishi kerak")
    if project.duration_seconds and end > project.duration_seconds + Decimal("0.5"):
        raise HTTPException(422, "Segment video uzunligidan oshib ketdi")
    if start != seg.start_time or end != seg.end_time:
        seg.start_time, seg.end_time = start, end
        needs_align = True

    if needs_synth and seg.translated_text_uz:
        seg.status = SegmentStatus.TRANSLATED
        seg.tts_audio_key = None
        seg.aligned_audio_key = None
    elif needs_align and seg.tts_audio_key:
        seg.status = SegmentStatus.SYNTHESIZED
        seg.aligned_audio_key = None
    await session.commit()
    await session.refresh(seg)
    return _segment_out(seg)


@router.post("/{project_id}/segments/{segment_id}/retranslate", response_model=ActionOut, status_code=202)
async def retranslate_segment(project: ProjectDep, segment_id: uuid.UUID, session: SessionDep) -> ActionOut:
    seg = await session.get(DialogueSegment, segment_id)
    if seg is None or seg.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment topilmadi")
    _ensure_idle(project)
    seg.manual_override_flags = False
    seg.status = SegmentStatus.PENDING
    await session.commit()
    _tasks().translate.delay(str(project.id), only_segment_ids=[str(segment_id)])
    return ActionOut(status="queued", message="Segment qayta tarjima qilinadi va ovozlashtiriladi")


# ------------------------------------------------------------------ spikerlar


@router.patch("/{project_id}/speakers/{speaker_id}", response_model=SpeakerOut)
async def patch_speaker(project: ProjectDep, speaker_id: uuid.UUID, body: SpeakerPatch, session: SessionDep) -> SpeakerOut:
    sp = await session.get(Speaker, speaker_id)
    if sp is None or sp.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Spiker topilmadi")
    data = body.model_dump(exclude_unset=True)
    if "voice_profile_id" in data and data["voice_profile_id"] != sp.voice_profile_id:
        vp = await session.get(VoiceProfile, data["voice_profile_id"]) if data["voice_profile_id"] else None
        if data["voice_profile_id"] and (vp is None or (vp.user_id not in (None, project.user_id))):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ovoz topilmadi")
        sp.voice_profile_id = data["voice_profile_id"]
        sp.is_custom_cloned = bool(vp and vp.is_cloned)
        # Ovoz aktyori almashtirildi → barcha segmentlari qayta sintez qilinadi
        segs = await session.scalars(select(DialogueSegment).where(DialogueSegment.speaker_id == sp.id))
        for seg in segs:
            if seg.translated_text_uz:
                seg.status = SegmentStatus.TRANSLATED
                seg.tts_audio_key = seg.aligned_audio_key = None
    for field in ("display_name", "detected_gender", "detected_age_group"):
        if field in data and data[field] is not None:
            setattr(sp, field, data[field])
    await session.commit()
    sp = (await session.scalars(select(Speaker).where(Speaker.id == speaker_id)
                                .execution_options(populate_existing=True))).unique().one()
    out = SpeakerOut.model_validate(sp)
    out.sample_url = storage.presigned_url(sp.sample_audio_key)
    out.voice = _voice_out(sp.voice_profile)
    return out


@router.post("/{project_id}/speakers/{speaker_id}/clone", response_model=ActionOut, status_code=202)
async def clone_speaker_voice(project: ProjectDep, speaker_id: uuid.UUID, session: SessionDep) -> ActionOut:
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ovoz klonlash uchun ElevenLabs sozlanmagan")
    sp = await session.get(Speaker, speaker_id)
    if sp is None or sp.project_id != project.id or not sp.sample_audio_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Spiker yoki uning namunasi topilmadi")
    _tasks().clone_voice.delay(str(project.id), str(speaker_id))
    return ActionOut(status="queued", message="Ovoz klonlanmoqda; tugagach «Qayta render» tugmasini bosing")


# ------------------------------------------------------------------ konveyerni boshqarish


def _ensure_idle(project: MediaProject) -> None:
    """Konveyer ishlayotgan paytda qayta render qilishga ruxsat berilmaydi."""
    if project.status not in IDLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Loyiha hali qayta ishlanmoqda — tugashini kuting")


@router.post("/{project_id}/start-tts", response_model=ActionOut, status_code=202)
async def start_tts(project: ProjectDep) -> ActionOut:
    """review_before_tts rejimida ssenariy tasdiqlangandan keyin dublyajni boshlash."""
    if project.status is not ProjectStatus.TRANSLATED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dublyajni faqat TRANSLATED holatidan boshlash mumkin")
    _tasks().dispatch_tts.delay(str(project.id))
    return ActionOut(status="queued", message="Ovozlashtirish boshlandi")


@router.post("/{project_id}/rerender", response_model=ActionOut, status_code=202)
async def rerender(project: ProjectDep, session: SessionDep) -> ActionOut:
    """Qoʻlda kiritilgan oʻzgarishlardan keyin faqat kerakli bosqichlarni qayta ishlatish."""
    _ensure_idle(project)
    counts = dict((await session.execute(
        select(DialogueSegment.status, func.count()).where(DialogueSegment.project_id == project.id)
        .group_by(DialogueSegment.status))).all())
    t = _tasks()
    if counts.get(SegmentStatus.PENDING):
        t.translate.delay(str(project.id), only_segment_ids=[
            str(x) for x in await session.scalars(select(DialogueSegment.id).where(
                DialogueSegment.project_id == project.id, DialogueSegment.status == SegmentStatus.PENDING))])
        msg = "Tarjimadan boshlab qayta ishlanadi"
    elif counts.get(SegmentStatus.TRANSLATED) or counts.get(SegmentStatus.FAILED):
        t.dispatch_tts.delay(str(project.id))
        msg = "Oʻzgargan segmentlar qayta ovozlashtiriladi"
    elif counts.get(SegmentStatus.SYNTHESIZED):
        t.align_timing.delay(str(project.id))
        msg = "Vaqt qayta moslanadi"
    else:
        t.master.delay(str(project.id))
        msg = "Audio qayta mikslanadi"
    events.publish("project", project.id, "status", status=project.status.value, stage="RERENDER", message=msg)
    return ActionOut(status="queued", message=msg)


@router.post("/{project_id}/retry", response_model=ActionOut, status_code=202)
async def retry(project: ProjectDep, session: SessionDep) -> ActionOut:
    """FAILED loyihani mos bosqichdan qayta ishga tushirish."""
    if project.status is not ProjectStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Faqat FAILED loyihani qayta ishga tushirish mumkin")
    t = _tasks()
    has_segments = await session.scalar(select(func.count()).select_from(DialogueSegment)
                                        .where(DialogueSegment.project_id == project.id))
    if not project.isolated_vocal_key:
        t.separate_stems.delay(str(project.id))
    elif not has_segments:
        t.transcribe.delay(str(project.id))
    else:
        return await rerender(project, session)
    return ActionOut(status="queued", message="Qayta ishga tushirildi")


# ------------------------------------------------------------------ eksport va xarajat


@router.get("/{project_id}/export", response_model=ExportOut)
async def export(project: ProjectDep) -> ExportOut:
    if project.status is not ProjectStatus.READY_FOR_EXPORT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Loyiha hali eksportga tayyor emas")
    base = "".join(c for c in project.title if c.isalnum() or c in " -_").strip() or "audiyo"
    return ExportOut(
        video_mp4=storage.presigned_url(project.dubbed_video_key, f"{base}.uz.mp4"),
        dubbed_audio=storage.presigned_url(project.dubbed_mix_key, f"{base}.uz.m4a"),
        dialogue_only=storage.presigned_url(project.dubbed_dialogue_key, f"{base}.dialogue.flac"),
        subtitles_srt=storage.presigned_url(project.subtitles_srt_key, f"{base}.uz.srt"),
        subtitles_vtt=storage.presigned_url(project.subtitles_vtt_key, f"{base}.uz.vtt"),
    )


@router.get("/{project_id}/costs")
async def costs(project: ProjectDep, session: SessionDep) -> dict:
    rows = (await session.execute(
        select(TTSJob.provider_name, func.count(), func.sum(TTSJob.token_character_count),
               func.sum(TTSJob.api_cost_usd), func.avg(TTSJob.execution_latency_ms))
        .join(DialogueSegment, DialogueSegment.id == TTSJob.segment_id)
        .where(DialogueSegment.project_id == project.id)
        .group_by(TTSJob.provider_name))).all()
    from app.services.tts.cost import customer_charge

    total = sum((r[3] or Decimal("0")) for r in rows)
    return {
        "providers": [
            {"provider": r[0].value, "jobs": r[1], "characters": int(r[2] or 0),
             "api_cost_usd": float(r[3] or 0), "avg_latency_ms": float(r[4] or 0)}
            for r in rows
        ],
        "api_cost_usd": float(total),
        "charge_usd": float(customer_charge(total)),
        "estimated_usd": float(project.estimated_cost_usd or 0),
    }


# ------------------------------------------------------------------ SSE


@router.get("/{project_id}/events")
async def project_events(project: ProjectDep, request: Request) -> StreamingResponse:
    snapshot = events.build_event("project", str(project.id), "snapshot", status=project.status.value,
                                  progress=float(project.progress), message=project.error_message)

    async def stream():
        yield f"event: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        async for message in events.subscribe("project", str(project.id)):
            if await request.is_disconnected():
                break
            if message is None:
                yield ": keep-alive\n\n"
                continue
            kind = json.loads(message).get("type", "message")
            yield f"event: {kind}\ndata: {message}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
