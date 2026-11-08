"""Dinamik TTS marshrutlash: daraja tanlash, ovoz tayinlash, qayta urinish, fallback, xarajat.

Darajalar:
  TIER_1 → ElevenLabs Multilingual v2 (asosiy qahramonlar, keng emotsional diapazon, klonlangan ovozlar)
  TIER_2 → Google Gemini TTS (ikkilamchi spikerlar, monologlar, budjet rejimi)

Ovoz izchilligi: daraja va ovoz SPIKER darajasida tanlanadi (segment darajasida emas), shuning uchun
bitta personaj butun film/kitob davomida bir xil ovozda gapiradi. Provayder ishdan chiqsa, spiker
oʻzining oldindan tayinlangan zaxira ovoziga "yopishib" qoladi (sticky fallback).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from app.models import AgeGroup, Gender, TTSMode, TTSProvider, TTSTier
from app.services.tts.base import (
    AuthError,
    BadRequest,
    ProviderNotConfigured,
    QuotaExceeded,
    RateLimited,
    TTSError,
    TTSProviderClient,
    TTSRequest,
    TTSResult,
)
from app.services.tts.cost import api_cost

EMOTIONAL_TAGS = {"angry", "sad", "excited", "fearful", "surprised", "whisper", "tender", "sarcastic", "anxious"}

TIER_PROVIDER = {TTSTier.TIER_1: TTSProvider.ELEVENLABS, TTSTier.TIER_2: TTSProvider.GEMINI}
OTHER_PROVIDER = {TTSProvider.ELEVENLABS: TTSProvider.GEMINI, TTSProvider.GEMINI: TTSProvider.ELEVENLABS}


# =============================================================== darajani tanlash


@dataclass
class SpeakerStats:
    key: str
    speech_share: float  # 0..1 — umumiy nutq vaqtidagi ulushi
    emotional_ratio: float = 0.0  # emotsional segmentlar ulushi
    segment_count: int = 0
    is_cloned: bool = False


def assign_tiers(
    stats: list[SpeakerStats],
    mode: TTSMode,
    *,
    primary_share: float = 0.15,
    secondary_share: float = 0.05,
    max_primary: int = 4,
    emotional_threshold: float = 0.35,
) -> dict[str, TTSTier]:
    """BALANCED rejim qoidalari:
    1. Klonlangan ovozli spiker → TIER_1 (klon faqat ElevenLabs da).
    2. Nutq ulushi ≥ primary_share → asosiy qahramon → TIER_1.
    3. Nutq ulushi ≥ secondary_share va emotsional segmentlar ≥ emotional_threshold → TIER_1.
    4. Hech kim TIER_1 boʻlmasa, eng koʻp gapiruvchi TIER_1.
    TIER_1 soni max_primary bilan cheklanadi (eng katta ball boʻyicha). Qolganlari TIER_2.
    """
    if mode is TTSMode.PREMIUM:
        return {s.key: TTSTier.TIER_1 for s in stats}
    if mode is TTSMode.BUDGET:
        return {s.key: (TTSTier.TIER_1 if s.is_cloned else TTSTier.TIER_2) for s in stats}

    def score(s: SpeakerStats) -> float:
        return s.speech_share + 0.5 * s.emotional_ratio * s.speech_share

    candidates = [
        s
        for s in stats
        if s.is_cloned
        or s.speech_share >= primary_share
        or (s.speech_share >= secondary_share and s.emotional_ratio >= emotional_threshold)
    ]
    if not candidates and stats:
        candidates = [max(stats, key=lambda s: s.speech_share)]
    cloned = [s for s in candidates if s.is_cloned]
    others = sorted((s for s in candidates if not s.is_cloned), key=score, reverse=True)
    primary = {s.key for s in cloned} | {s.key for s in others[: max(0, max_primary - len(cloned))]}
    return {s.key: (TTSTier.TIER_1 if s.key in primary else TTSTier.TIER_2) for s in stats}


# =============================================================== ovoz tayinlash


@dataclass(frozen=True)
class VoiceOption:
    profile_id: str
    provider: TTSProvider
    voice_id: str
    gender: Gender = Gender.UNKNOWN
    age_group: AgeGroup = AgeGroup.ADULT
    is_narrator: bool = False
    is_cloned: bool = False


@dataclass(frozen=True)
class SpeakerSpec:
    key: str
    tier: TTSTier
    gender: Gender = Gender.UNKNOWN
    age_group: AgeGroup = AgeGroup.UNKNOWN
    preferred_profile_id: str | None = None  # foydalanuvchi tanlagan yoki avval tayinlangan


@dataclass(frozen=True)
class VoiceAssignment:
    primary: VoiceOption
    fallback: VoiceOption | None


_AGE_ORDER = [AgeGroup.CHILD, AgeGroup.YOUNG_ADULT, AgeGroup.ADULT, AgeGroup.ELDERLY]


def _match_score(speaker: SpeakerSpec, voice: VoiceOption, usage: int) -> float:
    score = 0.0
    if speaker.gender is not Gender.UNKNOWN:
        if voice.gender is speaker.gender:
            score += 6
        elif voice.gender is not Gender.UNKNOWN:
            score -= 10
    if speaker.age_group in _AGE_ORDER and voice.age_group in _AGE_ORDER:
        diff = abs(_AGE_ORDER.index(speaker.age_group) - _AGE_ORDER.index(voice.age_group))
        score += {0: 3, 1: 1}.get(diff, -2)
    elif voice.age_group in (AgeGroup.ADULT, AgeGroup.YOUNG_ADULT):
        score += 1
    if voice.is_narrator:
        score -= 2  # hikoyachi ovozini personajlarga bermaslikka harakat qilamiz
    score -= 4 * usage  # takrorlanishni kamaytirish
    return score


def _pick(speaker: SpeakerSpec, pool: list[VoiceOption], usage: dict[str, int]) -> VoiceOption | None:
    if not pool:
        return None
    best = max(pool, key=lambda v: (_match_score(speaker, v, usage.get(v.profile_id, 0)), v.voice_id))
    usage[best.profile_id] = usage.get(best.profile_id, 0) + 1
    return best


def assign_voices(
    speakers: list[SpeakerSpec],
    catalog: Iterable[VoiceOption],
    *,
    reserved_profile_ids: Iterable[str] = (),
) -> dict[str, VoiceAssignment]:
    """Har spikerga asosiy (daraja provayderida) va zaxira (boshqa provayderda) ovoz tanlaydi.
    Bir xil ovoz ikki spikerga faqat katalog yetmasa beriladi."""
    catalog = list(catalog)
    by_id = {v.profile_id: v for v in catalog}
    by_provider: dict[TTSProvider, list[VoiceOption]] = {p: [] for p in TTSProvider}
    for v in catalog:
        by_provider[v.provider].append(v)
    usage: dict[str, int] = {pid: 1 for pid in reserved_profile_ids}
    fallback_usage: dict[str, int] = dict(usage)

    result: dict[str, VoiceAssignment] = {}
    # Avval foydalanuvchi tanlagan ovozlar band qilinadi
    for sp in speakers:
        if sp.preferred_profile_id and sp.preferred_profile_id in by_id:
            usage[sp.preferred_profile_id] = usage.get(sp.preferred_profile_id, 0) + 1
    for sp in speakers:
        provider = TIER_PROVIDER[sp.tier]
        if sp.preferred_profile_id and sp.preferred_profile_id in by_id:
            primary = by_id[sp.preferred_profile_id]
        else:
            pool = [v for v in by_provider[provider] if not v.is_cloned]
            primary = _pick(sp, pool, usage) or _pick(sp, [v for v in catalog if not v.is_cloned], usage)
        if primary is None:
            raise ValueError("Ovozlar katalogi boʻsh")
        fb_pool = [v for v in by_provider[OTHER_PROVIDER[primary.provider]] if not v.is_cloned]
        fallback = _pick(
            SpeakerSpec(sp.key, sp.tier, sp.gender if sp.gender is not Gender.UNKNOWN else primary.gender,
                        sp.age_group if sp.age_group is not AgeGroup.UNKNOWN else primary.age_group),
            fb_pool,
            fallback_usage,
        )
        result[sp.key] = VoiceAssignment(primary, fallback)
    return result


def pick_narrator(catalog: Iterable[VoiceOption], provider: TTSProvider, gender: Gender = Gender.MALE) -> VoiceOption | None:
    options = [v for v in catalog if v.provider is provider]
    narrators = [v for v in options if v.is_narrator] or options
    if not narrators:
        return None
    same = [v for v in narrators if v.gender is gender]
    return (same or narrators)[0]


# =============================================================== aylanma uzgich


class CircuitBreaker:
    """Ketma-ket xatolar soni chegaradan oshsa, provayder cooldown davomida chetlab oʻtiladi.
    Kvota tugasa — ish oxirigacha yopiq."""

    def __init__(self, threshold: int = 5, cooldown_s: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.failures = 0
        self.open_until = 0.0
        self.permanently_open = False
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return not self.permanently_open and self.clock() >= self.open_until

    def success(self) -> None:
        with self._lock:
            self.failures = 0

    def failure(self, permanent: bool = False) -> None:
        with self._lock:
            if permanent:
                self.permanently_open = True
                return
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = self.clock() + self.cooldown_s
                self.failures = 0


# =============================================================== marshrutlash


class TTSFailed(TTSError):
    def __init__(self, message: str, attempts: list[AttemptRecord]):
        super().__init__(message)
        self.attempts = attempts


@dataclass
class AttemptRecord:
    provider: TTSProvider
    retries: int
    error: str | None
    latency_ms: int


@dataclass
class RoutedResult:
    result: TTSResult
    provider: TTSProvider
    voice: VoiceOption
    fallback_from: TTSProvider | None
    retry_count: int
    latency_ms: int
    api_cost_usd: Decimal
    attempts: list[AttemptRecord] = field(default_factory=list)


class TTSRouter:
    def __init__(
        self,
        clients: dict[TTSProvider, TTSProviderClient],
        *,
        max_retries: int = 3,
        backoff_base_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        breakers: dict[TTSProvider, CircuitBreaker] | None = None,
        max_wait_s: float = 90.0,
    ) -> None:
        self.max_wait_s = max_wait_s
        self.clients = clients
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.sleep = sleep
        self.breakers = breakers or {p: CircuitBreaker() for p in TTSProvider}
        self._sticky: dict[str, bool] = {}
        self._lock = threading.Lock()

    def is_sticky_fallback(self, consistency_key: str) -> bool:
        return self._sticky.get(consistency_key, False)

    def _try_provider(self, voice: VoiceOption, request: TTSRequest) -> tuple[TTSResult | None, AttemptRecord]:
        client = self.clients.get(voice.provider)
        started = time.monotonic()
        if client is None:
            return None, AttemptRecord(voice.provider, 0, "provayder ulanmagan", 0)
        breaker = self.breakers[voice.provider]
        retries = 0
        last_error: str | None = None
        while True:
            if not breaker.allow():
                last_error = last_error or "provayder vaqtincha oʻchirilgan (circuit open)"
                break
            try:
                result = client.synthesize(TTSRequest(
                    text=request.text, voice_id=voice.voice_id, emotion=request.emotion,
                    language=request.language, speed=request.speed,
                ))
                breaker.success()
                return result, AttemptRecord(voice.provider, retries, None, int((time.monotonic() - started) * 1000))
            except (QuotaExceeded, AuthError, ProviderNotConfigured) as exc:
                breaker.failure(permanent=True)
                last_error = str(exc)
                break
            except BadRequest as exc:
                last_error = str(exc)
                break
            except RateLimited as exc:
                # Daqiqalik limit provayder nosozligi emas: breaker ochilmaydi, server aytgan vaqt kutiladi
                last_error = str(exc)
                if retries >= self.max_retries + 3:
                    break
                wait = exc.retry_after if exc.retry_after else self.backoff_base_s * (2**retries)
                self.sleep(min(wait, self.max_wait_s))
                retries += 1
            except TTSError as exc:
                last_error = str(exc)
                breaker.failure()
                if not exc.retryable or retries >= self.max_retries:
                    break
                self.sleep(self.backoff_base_s * (2**retries))
                retries += 1
        return None, AttemptRecord(voice.provider, retries, last_error, int((time.monotonic() - started) * 1000))

    def synthesize(
        self, request: TTSRequest, assignment: VoiceAssignment, consistency_key: str
    ) -> RoutedResult:
        attempts: list[AttemptRecord] = []
        order: list[tuple[VoiceOption, TTSProvider | None]] = []
        if self.is_sticky_fallback(consistency_key) and assignment.fallback:
            order.append((assignment.fallback, assignment.primary.provider))
        else:
            order.append((assignment.primary, None))
            if assignment.fallback:
                order.append((assignment.fallback, assignment.primary.provider))

        for voice, fallback_from in order:
            result, record = self._try_provider(voice, request)
            attempts.append(record)
            if result is None:
                continue
            if fallback_from is not None:
                with self._lock:
                    self._sticky[consistency_key] = True
            total_retries = sum(a.retries for a in attempts) + (len(attempts) - 1)
            cost = api_cost(voice.provider, result.characters, result.duration_seconds or 0.0)
            return RoutedResult(
                result=result,
                provider=voice.provider,
                voice=voice,
                fallback_from=fallback_from,
                retry_count=total_retries,
                latency_ms=sum(a.latency_ms for a in attempts),
                api_cost_usd=cost,
                attempts=attempts,
            )
        raise TTSFailed(
            "TTS barcha provayderlarda muvaffaqiyatsiz: " + "; ".join(f"{a.provider.value}: {a.error}" for a in attempts),
            attempts,
        )
