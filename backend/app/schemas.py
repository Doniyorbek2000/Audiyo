"""Pydantic v2 sxemalari (API kirish/chiqish)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import (
    AgeGroup,
    BlockType,
    BookStatus,
    Gender,
    LexiconSource,
    ProjectStatus,
    SegmentStatus,
    TransactionKind,
    TTSMode,
    TTSProvider,
    TTSTier,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str | None
    credit_balance_usd: Decimal
    created_at: datetime


# ------------------------------------------------------------------ voices
class VoiceOut(ORM):
    id: uuid.UUID
    name: str
    provider: TTSProvider
    provider_voice_id: str
    gender: Gender
    age_group: AgeGroup
    is_cloned: bool
    is_narrator: bool
    description: str | None
    is_system: bool = False


# ------------------------------------------------------------------ video projects
class ProjectOut(ORM):
    id: uuid.UUID
    title: str
    source_language: str
    target_language: str
    status: ProjectStatus
    tts_mode: TTSMode
    review_before_tts: bool
    progress: Decimal
    error_message: str | None
    duration_seconds: Decimal | None
    estimated_cost_usd: Decimal | None
    created_at: datetime
    updated_at: datetime


class SpeakerOut(ORM):
    id: uuid.UUID
    speaker_tag: str
    display_name: str | None
    detected_gender: Gender
    detected_age_group: AgeGroup
    speech_seconds: Decimal
    words_per_second: Decimal | None
    tts_tier: TTSTier
    voice_profile_id: uuid.UUID | None
    is_custom_cloned: bool
    sample_url: str | None = None
    voice: VoiceOut | None = None


class SegmentOut(ORM):
    id: uuid.UUID
    speaker_id: uuid.UUID | None
    sequence_order: int
    start_time: Decimal
    end_time: Decimal
    original_text: str
    translated_text_uz: str | None
    emotion_tag: str
    delivery: str | None = None
    source_syllables: int | None
    target_syllables: int | None
    max_syllables: int | None = None
    tts_duration_ms: int | None
    tempo_ratio: Decimal | None
    status: SegmentStatus
    manual_override_flags: bool
    audio_url: str | None = None


class StemsOut(BaseModel):
    original: str | None
    vocals: str | None
    bgm: str | None
    dubbed_dialogue: str | None
    dubbed_mix: str | None


class TimelineOut(BaseModel):
    project: ProjectOut
    duration: float | None
    stems: StemsOut
    peaks: dict | None
    speakers: list[SpeakerOut]
    segments: list[SegmentOut]
    pending_changes: int
    video_url: str | None
    poster_url: str | None = None


class SegmentPatch(BaseModel):
    translated_text_uz: str | None = Field(default=None, max_length=4000)
    speaker_id: uuid.UUID | None = None
    start_time: Decimal | None = Field(default=None, ge=0)
    end_time: Decimal | None = Field(default=None, gt=0)
    emotion_tag: str | None = None
    delivery: str | None = Field(default=None, max_length=200)

    @field_validator("emotion_tag")
    @classmethod
    def _emotion(cls, v: str | None) -> str | None:
        from app.services.llm.translation import EMOTIONS

        if v is not None and v not in EMOTIONS:
            raise ValueError(f"emotion_tag quyidagilardan biri boʻlishi kerak: {', '.join(EMOTIONS)}")
        return v


class SpeakerPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    voice_profile_id: uuid.UUID | None = None
    detected_gender: Gender | None = None
    detected_age_group: AgeGroup | None = None


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    tts_mode: TTSMode | None = None
    review_before_tts: bool | None = None


class ExportOut(BaseModel):
    video_mp4: str | None
    dubbed_audio: str | None
    dialogue_only: str | None
    subtitles_srt: str | None
    subtitles_vtt: str | None


class ActionOut(BaseModel):
    status: str
    message: str


# ------------------------------------------------------------------ books
class BookOut(ORM):
    id: uuid.UUID
    title: str
    author: str | None
    source_format: str
    status: BookStatus
    tts_mode: TTSMode
    progress: Decimal
    error_message: str | None
    narrator_voice_profile_id: uuid.UUID | None
    total_chars: int | None
    estimated_cost_usd: Decimal | None
    soundscape_enabled: bool = True
    directed: bool = False
    created_at: datetime
    updated_at: datetime


class BookPatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    author: str | None = Field(default=None, max_length=255)
    tts_mode: TTSMode | None = None
    narrator_voice_profile_id: uuid.UUID | None = None
    soundscape_enabled: bool | None = None


class ChapterOut(ORM):
    id: uuid.UUID
    chapter_index: int
    title: str | None
    duration_ms: int | None
    block_count: int = 0
    review_count: int = 0
    synthesized_count: int = 0
    audio_url: str | None = None


class CharacterOut(ORM):
    id: uuid.UUID
    canonical_name: str
    aliases: list[str]
    gender: Gender
    age_group: AgeGroup
    dialogue_share: Decimal
    tts_tier: TTSTier
    voice_profile_id: uuid.UUID | None
    is_minor: bool = False
    voice: VoiceOut | None = None


class CharacterPatch(BaseModel):
    canonical_name: str | None = Field(default=None, max_length=255)
    aliases: list[str] | None = None
    gender: Gender | None = None
    age_group: AgeGroup | None = None
    voice_profile_id: uuid.UUID | None = None
    merge_into_id: uuid.UUID | None = None  # bu personajni boshqasiga birlashtirish


class CharacterCreate(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=255)
    gender: Gender = Gender.UNKNOWN
    age_group: AgeGroup = AgeGroup.ADULT


class BlockOut(ORM):
    id: uuid.UUID
    chapter_id: uuid.UUID
    sequence_order: int
    block_type: BlockType
    character_id: uuid.UUID | None
    source_text: str
    tts_text: str | None
    emotion_tag: str
    delivery: str | None = None
    pause_after_ms: int
    attribution_confidence: Decimal | None
    needs_review: bool
    duration_ms: int | None
    status: SegmentStatus
    audio_url: str | None = None


class BlockPatch(BaseModel):
    source_text: str | None = Field(default=None, min_length=1, max_length=20000)  # >2000 avtomatik boʻlinadi
    block_type: BlockType | None = None
    character_id: uuid.UUID | None = None
    clear_character: bool = False  # hikoyachiga qaytarish
    emotion_tag: str | None = None
    delivery: str | None = Field(default=None, max_length=200)
    pause_after_ms: int | None = Field(default=None, ge=0, le=10000)
    needs_review: bool | None = None


class BlockPage(BaseModel):
    items: list[BlockOut]
    total: int


class SceneOut(ORM):
    id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_index: int = 0
    start_seq: int
    end_seq: int
    label: str
    ambience_prompt: str
    intensity: str
    enabled: bool
    has_audio: bool = False
    preview_url: str | None = None


class ScenePatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    ambience_prompt: str | None = Field(default=None, min_length=3, max_length=400)
    intensity: str | None = Field(default=None, pattern="^(low|medium)$")
    enabled: bool | None = None


class LexiconOut(ORM):
    id: uuid.UUID
    book_id: uuid.UUID | None
    term: str
    phonetic_uz: str
    source: LexiconSource
    approved: bool


class LexiconIn(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    phonetic_uz: str = Field(min_length=1, max_length=255)


class LexiconPatch(BaseModel):
    phonetic_uz: str | None = Field(default=None, min_length=1, max_length=255)
    approved: bool | None = None


class EstimateOut(BaseModel):
    total_chars: int
    chars_by_provider: dict[str, int]
    api_cost_usd: Decimal
    charge_usd: Decimal
    balance_usd: Decimal
    sufficient: bool


class BookExportOut(BaseModel):
    m4b: str | None
    chapters_zip: str | None
    chapters: list[dict]


# ------------------------------------------------------------------ billing
class TransactionOut(ORM):
    id: uuid.UUID
    kind: TransactionKind
    amount_usd: Decimal
    balance_after_usd: Decimal
    media_project_id: uuid.UUID | None
    book_project_id: uuid.UUID | None
    payment_id: str | None
    description: str | None
    created_at: datetime


class TopupIn(BaseModel):
    amount_usd: Decimal = Field(gt=0, le=10000)


class WebhookIn(BaseModel):
    payment_id: str = Field(min_length=1, max_length=100)
    user_id: uuid.UUID
    amount_usd: Decimal = Field(gt=0)
    status: str


class UsageRow(BaseModel):
    provider: TTSProvider
    jobs: int
    failed: int
    characters: int
    audio_seconds: float
    api_cost_usd: Decimal
    avg_latency_ms: float
    fallbacks: int


class UsageOut(BaseModel):
    rows: list[UsageRow]
    total_api_cost_usd: Decimal
    total_charge_usd: Decimal
