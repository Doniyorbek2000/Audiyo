"""Celery ilovasi va navbatlar.

Navbatlar (ishchilar alohida jarayon/mashinalarda izolyatsiya qilinadi):
  gpu — Demucs, WhisperX (GPU instansiyalar, concurrency=1)
  cpu — FFmpeg vaqt moslash, mikslash, eksport
  io  — LLM tarjima, TTS API chaqiruvlari, S3 yuklashlar (yuqori concurrency)
"""
from celery import Celery
from kombu import Queue

from app.config import get_settings

_s = get_settings()

celery_app = Celery("audiyo", broker=_s.redis_url, backend=_s.redis_url,
                    include=["app.workers.video_tasks", "app.workers.book_tasks"])

celery_app.conf.update(
    task_queues=[Queue("gpu"), Queue("cpu"), Queue("io")],
    task_default_queue="io",
    task_routes={
        "video.separate_stems": {"queue": "gpu"},
        "video.transcribe": {"queue": "gpu"},
        "video.translate": {"queue": "io"},
        "video.dispatch_tts": {"queue": "io"},
        "video.align_timing": {"queue": "cpu"},
        "video.master": {"queue": "cpu"},
        "video.clone_voice": {"queue": "io"},
        "book.prepare": {"queue": "cpu"},
        "book.attribute": {"queue": "io"},
        "book.apply_lexicon": {"queue": "io"},
        "book.synthesize": {"queue": "io"},
        "book.stitch": {"queue": "cpu"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=24 * 3600,
    broker_connection_retry_on_startup=True,
    task_time_limit=8 * 3600,
)
