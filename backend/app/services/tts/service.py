"""TTS ni DB va S3 bilan bogʻlovchi yordamchilar (Celery ishchilari uchun, sync)."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.models import TTSJob, TTSJobStatus, TTSProvider, VoiceProfile
from app.services.tts.base import TTSRequest
from app.services.tts.elevenlabs import ElevenLabsClient
from app.services.tts.gemini import GeminiTTSClient
from app.services.tts.router import RoutedResult, TTSFailed, TTSRouter, VoiceAssignment, VoiceOption

log = logging.getLogger(__name__)

PARALLELISM = 4


def voice_option(v: VoiceProfile) -> VoiceOption:
    return VoiceOption(
        profile_id=str(v.id),
        provider=v.provider,
        voice_id=v.provider_voice_id,
        gender=v.gender,
        age_group=v.age_group,
        is_narrator=v.is_narrator,
        is_cloned=v.is_cloned,
    )


def load_catalog(session: Session, user_id: uuid.UUID) -> list[VoiceOption]:
    """Tizim ovozlari + foydalanuvchining shaxsiy (klonlangan) ovozlari, sozlangan provayderlar boʻyicha."""
    s = get_settings()
    enabled = []
    if s.elevenlabs_api_key:
        enabled.append(TTSProvider.ELEVENLABS)
    if s.gemini_api_key:
        enabled.append(TTSProvider.GEMINI)
    rows = session.execute(
        select(VoiceProfile).where(
            or_(VoiceProfile.user_id.is_(None), VoiceProfile.user_id == user_id),
            VoiceProfile.provider.in_(enabled or list(TTSProvider)),
        )
    ).scalars()
    return [voice_option(v) for v in rows]


def build_router() -> TTSRouter:
    s = get_settings()
    clients = {}
    if s.elevenlabs_api_key:
        clients[TTSProvider.ELEVENLABS] = ElevenLabsClient()
    if s.gemini_api_key:
        clients[TTSProvider.GEMINI] = GeminiTTSClient()
    if not clients:
        raise RuntimeError("Hech bir TTS provayderi sozlanmagan (ELEVENLABS_API_KEY yoki GEMINI_API_KEY)")
    return TTSRouter(clients, max_retries=s.tts_max_retries, max_wait_s=s.rate_limit_max_wait_seconds)


def effective_assignment(assignment: VoiceAssignment, available: set[TTSProvider]) -> VoiceAssignment:
    """Asosiy provayder sozlanmagan boʻlsa — zaxirani asosiy qilib oladi."""
    if assignment.primary.provider in available or assignment.fallback is None:
        return assignment
    return VoiceAssignment(primary=assignment.fallback, fallback=None)


@dataclass
class SynthItem:
    item_id: uuid.UUID  # segment_id yoki text_block_id
    text: str
    emotion: str
    assignment: VoiceAssignment
    consistency_key: str
    storage_key_prefix: str  # masalan "projects/<id>/tts/<segment_id>"


@dataclass
class SynthOutcome:
    item: SynthItem
    routed: RoutedResult | None
    storage_key: str | None
    duration_ms: int | None
    error: str | None


def _duration_ms(routed: RoutedResult, local_path) -> int:
    if routed.result.duration_seconds:
        return int(routed.result.duration_seconds * 1000)
    from app.services.media import ffmpeg

    return int(ffmpeg.duration_seconds(local_path) * 1000)


def synthesize_many(
    router: TTSRouter,
    items: list[SynthItem],
    *,
    workdir,
    on_done: Callable[[SynthOutcome], None],
    parallelism: int | None = None,
) -> list[SynthOutcome]:
    """Parallel sintez; har natija tayyor boʻlishi bilan on_done (asosiy oqimda) chaqiriladi."""
    workdir.mkdir(parents=True, exist_ok=True)

    def work(item: SynthItem) -> SynthOutcome:
        try:
            routed = router.synthesize(TTSRequest(text=item.text, voice_id="", emotion=item.emotion),
                                       item.assignment, item.consistency_key)
        except TTSFailed as exc:
            return SynthOutcome(item, None, None, None, str(exc))
        local = workdir / f"{item.item_id}.{routed.result.extension}"
        local.write_bytes(routed.result.audio)
        key = f"{item.storage_key_prefix}.{routed.result.extension}"
        storage.upload_file(local, key, "audio/mpeg" if routed.result.extension == "mp3" else "audio/wav")
        return SynthOutcome(item, routed, key, _duration_ms(routed, local), None)

    outcomes: list[SynthOutcome] = []
    with ThreadPoolExecutor(max_workers=parallelism or get_settings().tts_parallelism) as pool:
        futures = [pool.submit(work, it) for it in items]
        for fut in as_completed(futures):
            try:
                outcome = fut.result()
            except Exception as exc:  # noqa: BLE001 — S3 va boshqa kutilmagan xatolar
                log.exception("TTS ishida kutilmagan xato")
                idx = futures.index(fut)
                outcome = SynthOutcome(items[idx], None, None, None, f"Kutilmagan xato: {exc}")
            outcomes.append(outcome)
            on_done(outcome)
    return outcomes


def record_job(
    session: Session,
    user_id: uuid.UUID,
    outcome: SynthOutcome,
    *,
    segment_id: uuid.UUID | None = None,
    text_block_id: uuid.UUID | None = None,
) -> TTSJob:
    if outcome.routed:
        r = outcome.routed
        job = TTSJob(
            user_id=user_id,
            segment_id=segment_id,
            text_block_id=text_block_id,
            provider_name=r.provider,
            fallback_from=r.fallback_from,
            status=TTSJobStatus.SUCCEEDED,
            token_character_count=r.result.characters,
            audio_seconds=Decimal(str(round((outcome.duration_ms or 0) / 1000, 3))),
            api_cost_usd=r.api_cost_usd,
            execution_latency_ms=r.latency_ms,
            retry_count=r.retry_count,
        )
    else:
        job = TTSJob(
            user_id=user_id,
            segment_id=segment_id,
            text_block_id=text_block_id,
            provider_name=outcome.item.assignment.primary.provider,
            status=TTSJobStatus.FAILED,
            token_character_count=len(outcome.item.text),
            error_message=(outcome.error or "")[:2000],
        )
    session.add(job)
    return job
