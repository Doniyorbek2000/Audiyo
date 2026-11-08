"""Ilova sozlamalari (muhit oʻzgaruvchilaridan oʻqiladi)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Audiyo"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Maʼlumotlar bazasi / navbat
    database_url: str = "postgresql+psycopg://audiyo:audiyo@localhost:5432/audiyo"
    redis_url: str = "redis://localhost:6379/0"

    # Autentifikatsiya
    jwt_secret: str = "change-me-in-production"
    jwt_ttl_minutes: int = 60 * 24 * 7

    # S3 / MinIO
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_public_endpoint_url: str | None = None  # brauzer uchun (presigned URL)
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_bucket: str = "audiyo"
    presign_ttl_seconds: int = 3600

    # Provayderlar
    elevenlabs_api_key: str | None = None
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gemini_text_model: str = "gemini-2.5-flash"
    tts_timeout_seconds: float = 60.0
    tts_max_retries: int = 3

    # Narxlar (USD) — provayder tarifiga qarab yangilang
    elevenlabs_usd_per_1k_chars: float = 0.30
    gemini_tts_usd_per_1k_chars: float = 0.02
    gemini_tts_usd_per_audio_second: float = 0.0
    platform_markup: float = 1.5  # mijozdan olinadigan koeffitsient
    signup_bonus_usd: float = 2.0
    payment_webhook_secret: str | None = None
    max_upload_mb: int = 4096

    # Konveyer
    work_dir: str = "/tmp/audiyo"
    whisper_model: str = "large-v3"
    whisper_device: str = "cuda"
    hf_token: str | None = None  # pyannote diarizatsiya uchun
    demucs_model: str = "htdemucs"
    atempo_min: float = 0.85
    atempo_max: float = 1.25
    book_block_max_chars: int = 2000
    primary_character_dialogue_share: float = 0.05
    attribution_review_threshold: float = 0.7


@lru_cache
def get_settings() -> Settings:
    return Settings()
