"""TTS provayderlari uchun umumiy interfeys va xatolar."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TTSError(RuntimeError):
    retryable: bool = False


class ProviderTimeout(TTSError):
    retryable = True


class RateLimited(TTSError):
    """Vaqtinchalik cheklov (429 concurrency) — qayta urinish mumkin."""

    retryable = True


class ProviderUnavailable(TTSError):
    """5xx — qayta urinish mumkin."""

    retryable = True


class QuotaExceeded(TTSError):
    """Kvota/kredit tugagan — shu ish davomida provayder oʻchiriladi."""


class AuthError(TTSError):
    pass


class BadRequest(TTSError):
    pass


class ProviderNotConfigured(TTSError):
    pass


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_id: str
    emotion: str = "neutral"
    language: str = "uz"
    speed: float = 1.0


@dataclass
class TTSResult:
    audio: bytes
    extension: str  # "mp3" | "wav"
    characters: int
    duration_seconds: float | None = None


class TTSProviderClient(Protocol):
    name: str

    def synthesize(self, request: TTSRequest) -> TTSResult: ...


# Emotsiyalar → ElevenLabs voice_settings
ELEVENLABS_EMOTION_SETTINGS: dict[str, dict[str, float]] = {
    "neutral": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.0},
    "serious": {"stability": 0.65, "similarity_boost": 0.75, "style": 0.1},
    "happy": {"stability": 0.40, "similarity_boost": 0.75, "style": 0.45},
    "excited": {"stability": 0.30, "similarity_boost": 0.75, "style": 0.65},
    "sad": {"stability": 0.45, "similarity_boost": 0.80, "style": 0.50},
    "angry": {"stability": 0.25, "similarity_boost": 0.80, "style": 0.75},
    "fearful": {"stability": 0.30, "similarity_boost": 0.80, "style": 0.60},
    "surprised": {"stability": 0.35, "similarity_boost": 0.75, "style": 0.55},
    "whisper": {"stability": 0.70, "similarity_boost": 0.70, "style": 0.30},
    "tender": {"stability": 0.60, "similarity_boost": 0.80, "style": 0.35},
    "sarcastic": {"stability": 0.40, "similarity_boost": 0.75, "style": 0.50},
    "curious": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.30},
    "hesitant": {"stability": 0.50, "similarity_boost": 0.75, "style": 0.25},
    "anxious": {"stability": 0.35, "similarity_boost": 0.80, "style": 0.50},
}

# Emotsiyalar → Gemini TTS uslub koʻrsatmasi
GEMINI_EMOTION_STYLE: dict[str, str] = {
    "neutral": "Read naturally in Uzbek, with clear diction",
    "serious": "Say in a serious, measured Uzbek voice",
    "happy": "Say cheerfully in Uzbek",
    "excited": "Say with excitement and energy in Uzbek",
    "sad": "Say sadly, softly in Uzbek",
    "angry": "Say angrily and forcefully in Uzbek",
    "fearful": "Say fearfully, with a trembling voice in Uzbek",
    "surprised": "Say with surprise in Uzbek",
    "whisper": "Whisper in Uzbek",
    "tender": "Say tenderly and warmly in Uzbek",
    "sarcastic": "Say sarcastically in Uzbek",
    "curious": "Say curiously, as a genuine question, in Uzbek",
    "hesitant": "Say hesitantly, with natural pauses, in Uzbek",
    "anxious": "Say anxiously in Uzbek",
}
