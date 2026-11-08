"""SQLAlchemy ORM modellari (migrations/001_init.sql bilan mos)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


# ----------------------------- ENUMlar -----------------------------
class ProjectStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    STEM_SEPARATION = "STEM_SEPARATION"
    TRANSCRIBED = "TRANSCRIBED"
    TRANSLATED = "TRANSLATED"
    TTS_DISPATCHED = "TTS_DISPATCHED"
    TIMING_ALIGNED = "TIMING_ALIGNED"
    MASTERED = "MASTERED"
    READY_FOR_EXPORT = "READY_FOR_EXPORT"
    FAILED = "FAILED"


class BookStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    SEGMENTED = "SEGMENTED"
    ATTRIBUTED = "ATTRIBUTED"
    LEXICON_APPLIED = "LEXICON_APPLIED"
    TTS_DISPATCHED = "TTS_DISPATCHED"
    STITCHED = "STITCHED"
    READY_FOR_EXPORT = "READY_FOR_EXPORT"
    FAILED = "FAILED"


class SegmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    TRANSLATED = "TRANSLATED"
    SYNTHESIZED = "SYNTHESIZED"
    ALIGNED = "ALIGNED"
    FAILED = "FAILED"


class BlockType(str, enum.Enum):
    NARRATION = "NARRATION"
    DIALOGUE = "DIALOGUE"
    HEADING = "HEADING"


class Gender(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNKNOWN = "UNKNOWN"


class AgeGroup(str, enum.Enum):
    CHILD = "CHILD"
    YOUNG_ADULT = "YOUNG_ADULT"
    ADULT = "ADULT"
    ELDERLY = "ELDERLY"
    UNKNOWN = "UNKNOWN"


class TTSProvider(str, enum.Enum):
    ELEVENLABS = "elevenlabs"
    GEMINI = "gemini"


class TTSTier(str, enum.Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class TTSMode(str, enum.Enum):
    PREMIUM = "PREMIUM"  # hamma spiker ElevenLabs
    BALANCED = "BALANCED"  # asosiylar ElevenLabs, qolgani Gemini
    BUDGET = "BUDGET"  # hammasi Gemini


class TTSJobStatus(str, enum.Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class TransactionKind(str, enum.Enum):
    BONUS = "BONUS"
    TOPUP = "TOPUP"
    HOLD = "HOLD"
    SETTLE = "SETTLE"
    REFUND = "REFUND"


class LexiconSource(str, enum.Enum):
    USER = "USER"
    GLOBAL = "GLOBAL"
    AUTO_SUGGESTED = "AUTO_SUGGESTED"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# ----------------------------- Jadvallar -----------------------------
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    credit_balance_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[TTSProvider] = mapped_column(pg_enum(TTSProvider, "tts_provider"))
    provider_voice_id: Mapped[str] = mapped_column(String(100))
    gender: Mapped[Gender] = mapped_column(pg_enum(Gender, "gender"), default=Gender.UNKNOWN)
    age_group: Mapped[AgeGroup] = mapped_column(pg_enum(AgeGroup, "age_group"), default=AgeGroup.ADULT)
    is_cloned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_narrator: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MediaProject(Base):
    __tablename__ = "media_projects"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    source_language: Mapped[str] = mapped_column(String(10))
    target_language: Mapped[str] = mapped_column(String(10), default="uz")
    status: Mapped[ProjectStatus] = mapped_column(
        pg_enum(ProjectStatus, "project_status"), default=ProjectStatus.UPLOADED
    )
    tts_mode: Mapped[TTSMode] = mapped_column(pg_enum(TTSMode, "tts_mode"), default=TTSMode.BALANCED)
    review_before_tts: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    source_video_key: Mapped[str] = mapped_column(Text)
    original_audio_key: Mapped[str | None] = mapped_column(Text)
    isolated_bgm_key: Mapped[str | None] = mapped_column(Text)
    isolated_vocal_key: Mapped[str | None] = mapped_column(Text)
    dubbed_dialogue_key: Mapped[str | None] = mapped_column(Text)
    dubbed_mix_key: Mapped[str | None] = mapped_column(Text)
    dubbed_video_key: Mapped[str | None] = mapped_column(Text)
    subtitles_srt_key: Mapped[str | None] = mapped_column(Text)
    subtitles_vtt_key: Mapped[str | None] = mapped_column(Text)
    poster_key: Mapped[str | None] = mapped_column(Text)
    waveform_peaks: Mapped[dict | None] = mapped_column(JSONB)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    speakers: Mapped[list[Speaker]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Speaker.speaker_tag"
    )
    segments: Mapped[list[DialogueSegment]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="DialogueSegment.sequence_order"
    )


class Speaker(Base):
    __tablename__ = "speakers"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("media_projects.id", ondelete="CASCADE"))
    speaker_tag: Mapped[str] = mapped_column(String(50))
    display_name: Mapped[str | None] = mapped_column(String(100))
    detected_gender: Mapped[Gender] = mapped_column(pg_enum(Gender, "gender"), default=Gender.UNKNOWN)
    detected_age_group: Mapped[AgeGroup] = mapped_column(
        pg_enum(AgeGroup, "age_group"), default=AgeGroup.UNKNOWN
    )
    speech_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0"))
    words_per_second: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    sample_audio_key: Mapped[str | None] = mapped_column(Text)
    tts_tier: Mapped[TTSTier] = mapped_column(pg_enum(TTSTier, "tts_tier"), default=TTSTier.TIER_2)
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="SET NULL")
    )
    elevenlabs_voice_id: Mapped[str | None] = mapped_column(String(100))
    is_custom_cloned: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[MediaProject] = relationship(back_populates="speakers")
    voice_profile: Mapped[VoiceProfile | None] = relationship(lazy="joined")


class DialogueSegment(Base):
    __tablename__ = "dialogue_segments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("media_projects.id", ondelete="CASCADE"))
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("speakers.id", ondelete="SET NULL"))
    sequence_order: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    end_time: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    original_text: Mapped[str] = mapped_column(Text)
    translated_text_uz: Mapped[str | None] = mapped_column(Text)
    emotion_tag: Mapped[str] = mapped_column(String(30), default="neutral")
    delivery: Mapped[str | None] = mapped_column(Text)
    source_syllables: Mapped[int | None] = mapped_column(Integer)
    target_syllables: Mapped[int | None] = mapped_column(Integer)
    words: Mapped[list | None] = mapped_column(JSONB)
    tts_audio_key: Mapped[str | None] = mapped_column(Text)
    tts_duration_ms: Mapped[int | None] = mapped_column(Integer)
    tempo_ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    aligned_audio_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SegmentStatus] = mapped_column(
        pg_enum(SegmentStatus, "segment_status"), default=SegmentStatus.PENDING
    )
    manual_override_flags: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[MediaProject] = relationship(back_populates="segments")
    speaker: Mapped[Speaker | None] = relationship()

    @property
    def target_duration_ms(self) -> int:
        return int((self.end_time - self.start_time) * 1000)


class BookProject(Base):
    __tablename__ = "book_projects"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    source_file_key: Mapped[str] = mapped_column(Text)
    source_format: Mapped[str] = mapped_column(String(10))
    status: Mapped[BookStatus] = mapped_column(pg_enum(BookStatus, "book_status"), default=BookStatus.UPLOADED)
    tts_mode: Mapped[TTSMode] = mapped_column(pg_enum(TTSMode, "tts_mode"), default=TTSMode.BALANCED)
    progress: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    narrator_voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="SET NULL")
    )
    total_chars: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    output_m4b_key: Mapped[str | None] = mapped_column(Text)
    output_zip_key: Mapped[str | None] = mapped_column(Text)
    soundscape_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    directed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chapters: Mapped[list[BookChapter]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="BookChapter.chapter_index"
    )
    characters: Mapped[list[BookCharacter]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="BookCharacter.canonical_name"
    )
    narrator_voice: Mapped[VoiceProfile | None] = relationship(lazy="joined")


class BookChapter(Base):
    __tablename__ = "book_chapters"
    id: Mapped[uuid.UUID] = _uuid_pk()
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("book_projects.id", ondelete="CASCADE"))
    chapter_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    audio_key: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    book: Mapped[BookProject] = relationship(back_populates="chapters")
    blocks: Mapped[list[TextBlock]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="TextBlock.sequence_order"
    )


class BookCharacter(Base):
    __tablename__ = "book_characters"
    id: Mapped[uuid.UUID] = _uuid_pk()
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("book_projects.id", ondelete="CASCADE"))
    canonical_name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    gender: Mapped[Gender] = mapped_column(pg_enum(Gender, "gender"), default=Gender.UNKNOWN)
    age_group: Mapped[AgeGroup] = mapped_column(pg_enum(AgeGroup, "age_group"), default=AgeGroup.UNKNOWN)
    dialogue_share: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    tts_tier: Mapped[TTSTier] = mapped_column(pg_enum(TTSTier, "tts_tier"), default=TTSTier.TIER_2)
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="SET NULL")
    )
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False)

    book: Mapped[BookProject] = relationship(back_populates="characters")
    voice_profile: Mapped[VoiceProfile | None] = relationship(lazy="joined")


class TextBlock(Base):
    __tablename__ = "text_blocks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("book_chapters.id", ondelete="CASCADE"))
    sequence_order: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[BlockType] = mapped_column(pg_enum(BlockType, "block_type"))
    character_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("book_characters.id", ondelete="SET NULL")
    )
    source_text: Mapped[str] = mapped_column(Text)
    tts_text: Mapped[str | None] = mapped_column(Text)
    emotion_tag: Mapped[str] = mapped_column(String(30), default="neutral")
    pause_after_ms: Mapped[int] = mapped_column(Integer, default=500)
    delivery: Mapped[str | None] = mapped_column(Text)
    attribution_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    tts_audio_key: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[SegmentStatus] = mapped_column(
        pg_enum(SegmentStatus, "segment_status"), default=SegmentStatus.PENDING
    )

    chapter: Mapped[BookChapter] = relationship(back_populates="blocks")
    character: Mapped[BookCharacter | None] = relationship()


class BookScene(Base):
    """Muhit tovushi qoʻyiladigan sahna: bob ichidagi bloklar oraligʻi."""

    __tablename__ = "book_scenes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("book_chapters.id", ondelete="CASCADE"))
    start_seq: Mapped[int] = mapped_column(Integer)
    end_seq: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(120))
    ambience_prompt: Mapped[str] = mapped_column(Text)
    intensity: Mapped[str] = mapped_column(String(10), default="low")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sfx_key: Mapped[str | None] = mapped_column(Text)


class PronunciationEntry(Base):
    __tablename__ = "pronunciation_lexicon"
    id: Mapped[uuid.UUID] = _uuid_pk()
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("book_projects.id", ondelete="CASCADE"))
    term: Mapped[str] = mapped_column(String(255))
    phonetic_uz: Mapped[str] = mapped_column(String(255))
    source: Mapped[LexiconSource] = mapped_column(
        pg_enum(LexiconSource, "lexicon_source"), default=LexiconSource.USER
    )
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TTSJob(Base):
    __tablename__ = "tts_jobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dialogue_segments.id", ondelete="CASCADE")
    )
    text_block_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("text_blocks.id", ondelete="CASCADE"))
    provider_name: Mapped[TTSProvider] = mapped_column(pg_enum(TTSProvider, "tts_provider"))
    fallback_from: Mapped[TTSProvider | None] = mapped_column(pg_enum(TTSProvider, "tts_provider"))
    status: Mapped[TTSJobStatus] = mapped_column(pg_enum(TTSJobStatus, "tts_job_status"))
    token_character_count: Mapped[int] = mapped_column(Integer)
    audio_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0"))
    api_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    execution_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[TransactionKind] = mapped_column(pg_enum(TransactionKind, "transaction_kind"))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    balance_after_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    media_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_projects.id", ondelete="SET NULL")
    )
    book_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("book_projects.id", ondelete="SET NULL")
    )
    payment_id: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
