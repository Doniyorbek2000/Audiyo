"""Ikki marta oʻralgan Gemini WAV fayllarini tuzatish: `python -m app.tools.repair_tts_wav [--dry-run]`.

Tuzatishdan oldingi versiya `gemini-3.8-flash-tts` qaytargan tayyor WAV ni xom PCM deb
qayta oʻragan edi: ichki RIFF sarlavhasi har blok boshida "chirsillash" sifatida eshitiladi.
Skript S3 dagi blok/segment audio fayllarini tekshiradi va ichki sarlavhani olib tashlaydi.
"""
from __future__ import annotations

import argparse
import io
import tempfile
import wave
from pathlib import Path

from sqlalchemy import or_, select

from app import storage
from app.db import sync_session
from app.models import DialogueSegment, TextBlock
from app.services.tts.gemini import decode_audio_payload, pcm_to_wav


def repair_bytes(data: bytes) -> bytes | None:
    """Ichida ikkinchi RIFF boʻlsa — tuzatilgan WAV, aks holda None."""
    if data[:4] != b"RIFF":
        return None
    with wave.open(io.BytesIO(data), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        rate = wf.getframerate()
    if frames[:4] != b"RIFF":
        return None
    pcm, inner_rate, channels = decode_audio_payload(frames, rate)
    return pcm_to_wav(pcm, inner_rate, channels)


def main(dry_run: bool = False) -> None:
    fixed = checked = 0
    with sync_session() as s, tempfile.TemporaryDirectory() as td:
        rows = list(s.execute(select(TextBlock).where(TextBlock.tts_audio_key.like("%.wav"))).scalars())
        rows += list(s.execute(select(DialogueSegment).where(
            or_(DialogueSegment.tts_audio_key.like("%.wav")))).scalars())
        for row in rows:
            checked += 1
            local = storage.download_file(row.tts_audio_key, Path(td) / "a.wav")
            repaired = repair_bytes(local.read_bytes())
            if repaired is None:
                continue
            fixed += 1
            if dry_run:
                continue
            storage.upload_bytes(repaired, row.tts_audio_key, "audio/wav")
            with wave.open(io.BytesIO(repaired)) as wf:
                ms = int(wf.getnframes() / wf.getframerate() * 1000)
            if isinstance(row, TextBlock):
                row.duration_ms = ms
            else:
                row.tts_duration_ms = ms
                row.aligned_audio_key = None  # vaqt moslash qayta bajarilishi kerak
    print(f"Tekshirildi: {checked}, tuzatildi: {fixed}{' (dry-run)' if dry_run else ''}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(ap.parse_args().dry_run)
