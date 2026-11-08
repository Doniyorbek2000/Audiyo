"""Video dublyaj konveyeri.

UPLOADED → STEM_SEPARATION → TRANSCRIBED → TRANSLATED → TTS_DISPATCHED → TIMING_ALIGNED → MASTERED
→ READY_FOR_EXPORT. Har bosqich tugagach keyingisini navbatga qoʻyadi (review_before_tts bundan mustasno).
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select

from app import events, storage
from app.config import get_settings
from app.db import sync_session
from app.models import (
    AgeGroup,
    DialogueSegment,
    Gender,
    MediaProject,
    ProjectStatus,
    SegmentStatus,
    Speaker,
    TTSProvider,
    TTSTier,
    VoiceProfile,
)
from app.services import billing
from app.services.llm.client import LLMNotConfigured, get_llm
from app.services.llm.translation import SourceSegment, translate_segments
from app.services.media import alignment, ffmpeg, mixing, separation, subtitles
from app.services.tts import cost as tts_cost
from app.services.tts.router import (
    EMOTIONAL_TAGS,
    SpeakerSpec,
    SpeakerStats,
    VoiceAssignment,
    assign_tiers,
    assign_voices,
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
from app.workers.common import (
    fail_project,
    interpolate,
    project_stage,
    set_project_status,
    workdir,
)

log = logging.getLogger(__name__)

MAX_SHORTEN_ROUNDS = 1


def start_pipeline(project_id: uuid.UUID) -> None:
    separate_stems.delay(str(project_id))


def _guarded(fn):
    """Har qanday xatoda loyihani FAILED holatiga oʻtkazadi."""

    def wrapper(project_id: str, *args, **kwargs):
        pid = uuid.UUID(project_id)
        try:
            return fn(pid, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("Video konveyer xatosi (%s)", fn.__name__)
            fail_project(pid, f"{fn.__name__}: {exc}")
            raise

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _key(project_id: uuid.UUID, name: str) -> str:
    return f"projects/{project_id}/{name}"


# =============================================================== 1. Ovozni ajratish (GPU)


@celery_app.task(name="video.separate_stems")
@_guarded
def separate_stems(project_id: uuid.UUID) -> None:
    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        video_key = p.source_video_key
    project_stage(project_id, "STEM_SEPARATION", "Video yuklab olinmoqda", 2)
    with workdir("video", project_id) as wd:
        src = storage.download_file(video_key, wd / ("source" + Path(video_key).suffix))
        if not ffmpeg.has_stream(src, "audio"):
            raise RuntimeError("Videoda audio yoʻlakcha topilmadi")
        audio = ffmpeg.extract_audio(src, wd / "original.wav", channels=2)
        duration = ffmpeg.duration_seconds(audio)
        poster = ffmpeg.poster_frame(src, wd / "poster.jpg", at_seconds=min(1.0, duration / 2))
        poster_key = storage.upload_file(poster, _key(project_id, "poster.jpg"), "image/jpeg") if poster else None
        project_stage(project_id, "STEM_SEPARATION", "Vokal va fon ajratilmoqda (Demucs)", 5)
        stems = separation.separate(audio, wd / "stems")
        project_stage(project_id, "STEM_SEPARATION", f"Ajratildi ({stems.method}), yuklanmoqda", 12)

        keys = {}
        for name, path in (("original", audio), ("vocals", stems.vocals), ("bgm", stems.accompaniment)):
            flac = wd / f"{name}.flac"
            ffmpeg.run(["-i", str(path), "-c:a", "flac", str(flac)])
            keys[name] = storage.upload_file(flac, _key(project_id, f"stems/{name}.flac"), "audio/flac")
        peaks = {name: ffmpeg.waveform_peaks(path) for name, path in
                 (("original", audio), ("vocals", stems.vocals), ("bgm", stems.accompaniment))}

    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        p.duration_seconds = Decimal(str(round(duration, 3)))
        p.original_audio_key = keys["original"]
        p.isolated_vocal_key = keys["vocals"]
        p.isolated_bgm_key = keys["bgm"]
        p.poster_key = poster_key
        p.waveform_peaks = {"duration": duration, **peaks}
    set_project_status(project_id, ProjectStatus.STEM_SEPARATION, f"Ovoz ajratildi ({stems.method})")
    transcribe.delay(str(project_id))


# =============================================================== 2. STT + diarizatsiya (GPU)


@celery_app.task(name="video.transcribe")
@_guarded
def transcribe(project_id: uuid.UUID) -> None:
    from app.services.media.transcription import transcribe as run_whisperx

    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        vocal_key, lang = p.isolated_vocal_key, p.source_language
    project_stage(project_id, "TRANSCRIBING", "Nutq matnga oʻgirilmoqda (WhisperX)", 17)
    with workdir("video", project_id) as wd:
        vocals_flac = storage.download_file(vocal_key, wd / "vocals.flac")
        vocals = ffmpeg.to_wav(vocals_flac, wd / "vocals.wav", channels=1)
        transcript = run_whisperx(vocals, None if lang == "auto" else lang)
        project_stage(project_id, "TRANSCRIBING", f"{len(transcript.segments)} ta segment, "
                      f"{len(transcript.speakers)} ta spiker aniqlandi", 30)

        # Spiker namunalari (eng uzun segmentlardan ~20 s)
        samples: dict[str, str] = {}
        for tag in transcript.speakers:
            segs = sorted((x for x in transcript.segments if x.speaker == tag), key=lambda x: -x.duration)
            pieces, total = [], 0.0
            for i, seg in enumerate(segs):
                if total >= 20:
                    break
                pieces.append(ffmpeg.cut(vocals, wd / f"sample_{tag}_{i}.wav", seg.start, seg.end))
                total += seg.duration
            if pieces:
                joined = ffmpeg.concat_wavs(pieces, wd / f"sample_{tag}.wav", wd)
                mp3 = wd / f"sample_{tag}.mp3"
                ffmpeg.run(["-i", str(joined), "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)])
                samples[tag] = storage.upload_file(mp3, _key(project_id, f"speakers/{tag}.mp3"), "audio/mpeg")

    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        if lang == "auto":
            p.source_language = transcript.language
        s.execute(delete(DialogueSegment).where(DialogueSegment.project_id == project_id))
        s.execute(delete(Speaker).where(Speaker.project_id == project_id))
        speaker_ids: dict[str, uuid.UUID] = {}
        for tag, info in sorted(transcript.speakers.items()):
            sp = Speaker(
                project_id=project_id,
                speaker_tag=tag,
                display_name=tag.replace("SPEAKER_", "Spiker "),
                detected_gender=Gender(info.gender),
                detected_age_group=AgeGroup(info.age_group),
                speech_seconds=Decimal(str(info.speech_seconds)),
                words_per_second=Decimal(str(info.words_per_second)),
                sample_audio_key=samples.get(tag),
            )
            s.add(sp)
            s.flush()
            speaker_ids[tag] = sp.id
        for order, seg in enumerate(transcript.segments):
            s.add(DialogueSegment(
                project_id=project_id,
                speaker_id=speaker_ids.get(seg.speaker),
                sequence_order=order,
                start_time=Decimal(str(seg.start)),
                end_time=Decimal(str(max(seg.end, seg.start + 0.05))),
                original_text=seg.text,
                words=[{"w": w.text, "s": round(w.start, 3), "e": round(w.end, 3)} for w in seg.words],
            ))
    set_project_status(project_id, ProjectStatus.TRANSCRIBED, "Transkripsiya tayyor")
    translate.delay(str(project_id))


# =============================================================== 3. Tarjima (IO)


@celery_app.task(name="video.translate")
@_guarded
def translate(project_id: uuid.UUID, only_segment_ids: list[str] | None = None, shorten_round: int = 0) -> None:
    s_cfg = get_settings()
    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        title, lang, review = p.title, p.source_language, p.review_before_tts
        q = select(DialogueSegment).where(DialogueSegment.project_id == project_id).order_by(DialogueSegment.sequence_order)
        segs = s.execute(q).scalars().all()
        speakers = {sp.id: sp for sp in s.execute(select(Speaker).where(Speaker.project_id == project_id)).scalars()}
        wanted = set(only_segment_ids or [])
        sources = [
            SourceSegment(
                segment_id=str(x.id),
                speaker_id=speakers[x.speaker_id].speaker_tag if x.speaker_id in speakers else "SPEAKER_00",
                source_text=x.original_text,
                start_ms=int(x.start_time * 1000),
                end_ms=int(x.end_time * 1000),
                gender=speakers[x.speaker_id].detected_gender.value if x.speaker_id in speakers else "UNKNOWN",
            )
            for x in segs
            if (not wanted or str(x.id) in wanted) and not x.manual_override_flags
        ]
    if sources:
        project_stage(project_id, "TRANSLATING", f"{len(sources)} ta segment tarjima qilinmoqda", 38)
        try:
            llm = get_llm()
        except LLMNotConfigured as exc:
            raise RuntimeError(str(exc)) from exc
        # Qisqartirish raundlarida boʻgʻin byudjeti torayadi (TTS kutilganidan sekin gapirgan)
        atempo_budget = s_cfg.atempo_max * (0.8**shorten_round)
        result = translate_segments(llm, sources, lang, atempo_max=atempo_budget, title=title)
        by_id = {t.segment_id: t for t in result.segments}
        with sync_session() as s:
            for seg in s.execute(select(DialogueSegment).where(DialogueSegment.id.in_(
                    [uuid.UUID(k) for k in by_id]))).scalars():
                t = by_id[str(seg.id)]
                seg.translated_text_uz = t.target_uz_text
                seg.emotion_tag = t.emotion_tag
                seg.delivery = t.delivery or None
                seg.source_syllables = t.source_syllables
                seg.target_syllables = t.target_syllables
                seg.status = SegmentStatus.TRANSLATED
                seg.tts_audio_key = None
                seg.aligned_audio_key = None
    set_project_status(project_id, ProjectStatus.TRANSLATED, "Tarjima tayyor")
    if review and shorten_round == 0 and not only_segment_ids:
        events.publish("project", project_id, "status", status=ProjectStatus.TRANSLATED.value,
                       stage="AWAITING_REVIEW", message="Ssenariyni tekshirib, dublyajni ishga tushiring")
        return
    dispatch_tts.delay(str(project_id), shorten_round=shorten_round)


# =============================================================== 4. TTS (IO)


def _speaker_stats(speakers: list[Speaker], segs: list[DialogueSegment]) -> list[SpeakerStats]:
    total = sum(float(sp.speech_seconds) for sp in speakers) or 1.0
    emotional = defaultdict(int)
    counts = defaultdict(int)
    for seg in segs:
        if seg.speaker_id:
            counts[seg.speaker_id] += 1
            if seg.emotion_tag in EMOTIONAL_TAGS:
                emotional[seg.speaker_id] += 1
    return [
        SpeakerStats(
            key=str(sp.id),
            speech_share=float(sp.speech_seconds) / total,
            emotional_ratio=emotional[sp.id] / counts[sp.id] if counts[sp.id] else 0.0,
            segment_count=counts[sp.id],
            is_cloned=sp.is_custom_cloned,
        )
        for sp in speakers
    ]


def resolve_speaker_voices(session, project: MediaProject) -> dict[str, VoiceAssignment]:
    """Darajalar va ovozlarni tayinlash (foydalanuvchi tanlagan ovozlar saqlanadi)."""
    speakers = list(session.execute(select(Speaker).where(Speaker.project_id == project.id)).scalars())
    segs = list(session.execute(select(DialogueSegment).where(DialogueSegment.project_id == project.id)).scalars())
    tiers = assign_tiers(_speaker_stats(speakers, segs), project.tts_mode,
                         secondary_share=get_settings().primary_character_dialogue_share)
    catalog = load_catalog(session, project.user_id)
    extra = [voice_option(sp.voice_profile) for sp in speakers
             if sp.voice_profile and str(sp.voice_profile_id) not in {v.profile_id for v in catalog}]
    specs = [
        SpeakerSpec(
            key=str(sp.id),
            tier=TTSTier.TIER_1 if (sp.voice_profile and sp.voice_profile.provider is TTSProvider.ELEVENLABS
                                    and sp.voice_profile_id) else tiers[str(sp.id)],
            gender=sp.detected_gender,
            age_group=sp.detected_age_group,
            preferred_profile_id=str(sp.voice_profile_id) if sp.voice_profile_id else None,
        )
        for sp in speakers
    ]
    assignments = assign_voices(specs, catalog + extra)
    for sp in speakers:
        a = assignments[str(sp.id)]
        sp.voice_profile_id = uuid.UUID(a.primary.profile_id)
        sp.tts_tier = TTSTier.TIER_1 if a.primary.provider is TTSProvider.ELEVENLABS else TTSTier.TIER_2
        sp.elevenlabs_voice_id = a.primary.voice_id if a.primary.provider is TTSProvider.ELEVENLABS else None
    return assignments


@celery_app.task(name="video.dispatch_tts")
@_guarded
def dispatch_tts(project_id: uuid.UUID, shorten_round: int = 0) -> None:
    router = build_router()
    available = set(router.clients)
    with sync_session() as s:
        project = s.get(MediaProject, project_id)
        user_id = project.user_id
        assignments = resolve_speaker_voices(s, project)
        pending = list(s.execute(
            select(DialogueSegment).where(
                DialogueSegment.project_id == project_id,
                DialogueSegment.translated_text_uz.is_not(None),
                DialogueSegment.status.in_([SegmentStatus.TRANSLATED, SegmentStatus.FAILED]),
            ).order_by(DialogueSegment.sequence_order)
        ).scalars())
        default_key = next(iter(assignments), None)
        items = []
        chars_by_provider: dict[TTSProvider, int] = defaultdict(int)
        for seg in pending:
            text = (seg.translated_text_uz or "").strip()
            if not text:
                continue
            key = str(seg.speaker_id) if seg.speaker_id and str(seg.speaker_id) in assignments else default_key
            assignment = effective_assignment(assignments[key], available)
            chars_by_provider[assignment.primary.provider] += len(text)
            items.append(SynthItem(seg.id, text, seg.emotion_tag, assignment, key,
                                   _key(project_id, f"tts/{seg.id}-{uuid.uuid4().hex[:6]}"),
                                   style=seg.delivery, role="character"))
        api_estimate, charge_estimate = tts_cost.estimate(chars_by_provider)
        project.estimated_cost_usd = charge_estimate
        held = Decimal("0")
        if charge_estimate > 0:
            billing.hold(s, user_id, charge_estimate, media_project_id=project_id)
            held = charge_estimate
    events.publish("project", project_id, "cost", stage="TTS",
                   message=f"Taxminiy narx ${charge_estimate:.4f}", data={"estimate_usd": float(charge_estimate)})

    total = len(items)
    done = {"n": 0, "api_cost": Decimal("0"), "failed": 0}

    def on_done(outcome: SynthOutcome) -> None:
        done["n"] += 1
        with sync_session() as s2:
            seg = s2.get(DialogueSegment, outcome.item.item_id)
            record_job(s2, user_id, outcome, segment_id=outcome.item.item_id)
            if outcome.routed:
                done["api_cost"] += outcome.routed.api_cost_usd
                seg.tts_audio_key = outcome.storage_key
                seg.tts_duration_ms = outcome.duration_ms
                seg.aligned_audio_key = None
                seg.status = SegmentStatus.SYNTHESIZED
            else:
                done["failed"] += 1
                seg.status = SegmentStatus.FAILED
        events.publish(
            "project", project_id, "segment", stage="TTS",
            progress=interpolate(50, 75, done["n"] / max(total, 1)),
            message=f"Sintez: {done['n']}/{total}",
            data={
                "segment_id": str(outcome.item.item_id),
                "status": "SYNTHESIZED" if outcome.routed else "FAILED",
                "provider": outcome.routed.provider.value if outcome.routed else None,
                "fallback_from": outcome.routed.fallback_from.value if outcome.routed and outcome.routed.fallback_from else None,
                "error": outcome.error,
                "spent_usd": float(tts_cost.customer_charge(done["api_cost"])),
            },
        )

    try:
        with workdir("tts", project_id) as wd:
            synthesize_many(router, items, workdir=wd, on_done=on_done)
    finally:
        actual = tts_cost.customer_charge(done["api_cost"])
        with sync_session() as s:
            billing.settle(s, user_id, held, actual, media_project_id=project_id)
        events.publish("project", project_id, "cost", stage="TTS", message=f"Yakuniy narx ${actual:.4f}",
                       data={"charged_usd": float(actual), "estimate_usd": float(held)})

    if done["failed"]:
        raise RuntimeError(f"{done['failed']} ta segment sintez qilinmadi — qayta urinib koʻring")
    set_project_status(project_id, ProjectStatus.TTS_DISPATCHED, f"{total} ta segment ovozlashtirildi")
    align_timing.delay(str(project_id), shorten_round=shorten_round)


# =============================================================== 5. Vaqtni moslash (CPU)


@celery_app.task(name="video.align_timing")
@_guarded
def align_timing(project_id: uuid.UUID, shorten_round: int = 0) -> None:
    cfg = get_settings()
    with sync_session() as s:
        segs = list(s.execute(select(DialogueSegment).where(DialogueSegment.project_id == project_id)
                              .order_by(DialogueSegment.start_time)).scalars())
        next_start = {x.id: (float(segs[i + 1].start_time) if i + 1 < len(segs) else None) for i, x in enumerate(segs)}
        todo = [(x.id, x.tts_audio_key, float(x.start_time), float(x.end_time), x.manual_override_flags)
                for x in segs if x.tts_audio_key and (x.status == SegmentStatus.SYNTHESIZED or not x.aligned_audio_key)]
    too_long: list[str] = []
    with workdir("align", project_id) as wd:
        for i, (seg_id, key, start, end, manual) in enumerate(todo):
            src = storage.download_file(key, wd / f"{seg_id}{Path(key).suffix}")
            dur = ffmpeg.duration_seconds(src)
            plan = alignment.plan_alignment(dur, start, end, next_start[seg_id], tempo_min=cfg.atempo_min, tempo_max=cfg.atempo_max)
            if plan.needs_retranslation and not manual and shorten_round < MAX_SHORTEN_ROUNDS:
                too_long.append(str(seg_id))
            out = alignment.apply_alignment(src, wd / f"{seg_id}.aligned.wav", plan)
            flac = wd / f"{seg_id}.flac"
            ffmpeg.run(["-i", str(out), "-c:a", "flac", str(flac)])
            aligned_key = storage.upload_file(flac, _key(project_id, f"aligned/{seg_id}.flac"), "audio/flac")
            with sync_session() as s:
                seg = s.get(DialogueSegment, seg_id)
                seg.aligned_audio_key = aligned_key
                seg.tempo_ratio = Decimal(str(plan.tempo_ratio))
                seg.status = SegmentStatus.ALIGNED
            project_stage(project_id, "ALIGNING", f"Vaqt moslash: {i + 1}/{len(todo)}",
                          interpolate(75, 85, (i + 1) / max(len(todo), 1)))

    if too_long:
        # Tarjimani qisqartirib, qayta sintez qilish (bir marta)
        project_stage(project_id, "ALIGNING", f"{len(too_long)} ta segment uzun — tarjima qisqartirilmoqda")
        with sync_session() as s:
            for seg in s.execute(select(DialogueSegment).where(
                    DialogueSegment.id.in_([uuid.UUID(x) for x in too_long]))).scalars():
                seg.status = SegmentStatus.PENDING
        translate.delay(str(project_id), only_segment_ids=too_long, shorten_round=shorten_round + 1)
        return
    set_project_status(project_id, ProjectStatus.TIMING_ALIGNED, "Vaqt moslandi")
    master.delay(str(project_id))


# =============================================================== 6. Mikslash va eksport (CPU)


@celery_app.task(name="video.master")
@_guarded
def master(project_id: uuid.UUID) -> None:
    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        video_key, bgm_key, duration = p.source_video_key, p.isolated_bgm_key, float(p.duration_seconds or 0)
        source_lang, title = p.source_language, p.title
        segs = list(s.execute(select(DialogueSegment).where(DialogueSegment.project_id == project_id)
                              .order_by(DialogueSegment.start_time)).scalars())
        clips = [(x.id, x.aligned_audio_key, float(x.start_time)) for x in segs if x.aligned_audio_key]
        cues = [subtitles.Cue(float(x.start_time), float(x.end_time), x.translated_text_uz)
                for x in segs if x.translated_text_uz]
    if not clips:
        raise RuntimeError("Moslangan audio segmentlar yoʻq")
    project_stage(project_id, "MASTERING", "Dialog yoʻlakchasi yigʻilmoqda", 86)
    with workdir("master", project_id) as wd:
        placements = []
        for seg_id, key, start in clips:
            local = storage.download_file(key, wd / "clips" / f"{seg_id}.flac")
            placements.append(alignment.Placement(local, start, ffmpeg.duration_seconds(local)))
        dialogue = alignment.build_timeline_track(placements, duration, wd / "dialogue.wav", wd / "timeline")
        project_stage(project_id, "MASTERING", "Fon bilan mikslash (sidechain ducking)", 90)
        bgm = storage.download_file(bgm_key, wd / "bgm.flac")
        mix = mixing.mix_with_ducking(dialogue, bgm, wd / "mix.wav")

        srt = wd / "subtitles.uz.srt"
        srt.write_text(subtitles.to_srt(cues), encoding="utf-8")
        vtt = wd / "subtitles.uz.vtt"
        vtt.write_text(subtitles.to_vtt(cues), encoding="utf-8")

        project_stage(project_id, "MASTERING", "Video bilan birlashtirilmoqda", 93)
        video = storage.download_file(video_key, wd / ("source" + Path(video_key).suffix))
        out_mp4 = mixing.mux_video(video, mix, wd / "dubbed.mp4", subtitles_srt=srt,
                                   original_language=_iso639_2(source_lang))
        dialogue_flac = wd / "dialogue.flac"
        ffmpeg.run(["-i", str(dialogue), "-c:a", "flac", str(dialogue_flac)])
        mix_m4a = wd / "mix.m4a"
        ffmpeg.run(["-i", str(mix), "-c:a", "aac", "-b:a", "192k", str(mix_m4a)])

        keys = {
            "dialogue": storage.upload_file(dialogue_flac, _key(project_id, "output/dialogue.flac"), "audio/flac"),
            "mix": storage.upload_file(mix_m4a, _key(project_id, "output/mix.m4a"), "audio/mp4"),
            "video": storage.upload_file(out_mp4, _key(project_id, "output/dubbed.mp4"), "video/mp4"),
            "srt": storage.upload_file(srt, _key(project_id, "output/subtitles.uz.srt"), "application/x-subrip"),
            "vtt": storage.upload_file(vtt, _key(project_id, "output/subtitles.uz.vtt"), "text/vtt"),
        }
        dub_peaks = ffmpeg.waveform_peaks(dialogue)

    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        p.dubbed_dialogue_key = keys["dialogue"]
        p.dubbed_mix_key = keys["mix"]
        p.dubbed_video_key = keys["video"]
        p.subtitles_srt_key = keys["srt"]
        p.subtitles_vtt_key = keys["vtt"]
        p.waveform_peaks = {**(p.waveform_peaks or {}), "dubbed": dub_peaks}
    set_project_status(project_id, ProjectStatus.MASTERED, "Mastering tugadi")
    set_project_status(project_id, ProjectStatus.READY_FOR_EXPORT, f"«{title}» eksportga tayyor")


_ISO = {"en": "eng", "ru": "rus", "tr": "tur", "ko": "kor", "ja": "jpn", "zh": "zho", "ar": "ara", "fa": "fas",
        "hi": "hin", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "kk": "kaz", "uz": "uzb"}


def _iso639_2(code: str) -> str:
    return _ISO.get((code or "")[:2], "und")


# =============================================================== Ovoz klonlash (IO)


@celery_app.task(name="video.clone_voice")
@_guarded
def clone_voice(project_id: uuid.UUID, speaker_id: str) -> None:
    from app.services.tts.elevenlabs import ElevenLabsClient

    sid = uuid.UUID(speaker_id)
    with sync_session() as s:
        sp = s.get(Speaker, sid)
        p = s.get(MediaProject, project_id)
        if not sp or not sp.sample_audio_key:
            raise RuntimeError("Spiker namunasi topilmadi")
        sample_key, name, user_id = sp.sample_audio_key, sp.display_name or sp.speaker_tag, p.user_id
        gender, age = sp.detected_gender, sp.detected_age_group
    project_stage(project_id, "CLONING", f"{name} ovozi klonlanmoqda")
    with workdir("clone", project_id) as wd:
        sample = storage.download_file(sample_key, wd / "sample.mp3")
        voice_id = ElevenLabsClient().clone_voice(f"{name} ({str(project_id)[:8]})", [sample],
                                                  "Audiyo: loyiha spikeri ovozi")
    with sync_session() as s:
        vp = VoiceProfile(user_id=user_id, name=f"{name} (klon)", provider=TTSProvider.ELEVENLABS,
                          provider_voice_id=voice_id, gender=gender,
                          age_group=age if age is not AgeGroup.UNKNOWN else AgeGroup.ADULT, is_cloned=True)
        s.add(vp)
        s.flush()
        sp = s.get(Speaker, sid)
        sp.voice_profile_id = vp.id
        sp.is_custom_cloned = True
        sp.elevenlabs_voice_id = voice_id
        sp.tts_tier = TTSTier.TIER_1
        # Bu spikerning barcha segmentlari yangi ovoz bilan qayta sintez qilinadi
        for seg in s.execute(select(DialogueSegment).where(DialogueSegment.speaker_id == sid)).scalars():
            if seg.translated_text_uz:
                seg.status = SegmentStatus.TRANSLATED
    events.publish("project", project_id, "status", stage="CLONED", message=f"{name} ovozi klonlandi",
                   data={"speaker_id": speaker_id, "voice_id": voice_id})
