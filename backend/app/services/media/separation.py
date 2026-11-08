"""Ovozni ajratish: Demucs v4 (Hybrid Transformer) → vocals.wav + accompaniment.wav.

GPU tugunida `demucs` paketi oʻrnatilgan boʻlishi kerak. Ishlab chiqish muhitida demucs boʻlmasa,
oddiy "markaziy kanalni ayirish" (karaoke) usuli zaxira sifatida ishlatiladi — sifati past, faqat test uchun.
"""
from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.services.media import ffmpeg

log = logging.getLogger(__name__)


@dataclass
class Stems:
    vocals: Path
    accompaniment: Path
    method: str


def demucs_available() -> bool:
    return importlib.util.find_spec("demucs") is not None


def separate(audio_wav: Path, out_dir: Path, *, allow_fallback: bool = True) -> Stems:
    out_dir.mkdir(parents=True, exist_ok=True)
    if demucs_available():
        return _separate_demucs(audio_wav, out_dir)
    if not allow_fallback:
        raise RuntimeError("demucs oʻrnatilmagan (requirements-gpu.txt)")
    log.warning("demucs topilmadi — karaoke zaxira usuli ishlatilmoqda (past sifat)")
    return _separate_center_cancel(audio_wav, out_dir)


def _separate_demucs(audio_wav: Path, out_dir: Path) -> Stems:
    s = get_settings()
    device = "cuda" if s.whisper_device == "cuda" else "cpu"
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "--two-stems", "vocals",
        "-n", s.demucs_model,
        "-d", device,
        "--float32",
        "-o", str(out_dir),
        str(audio_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=6 * 3600)
    if proc.returncode != 0:
        raise RuntimeError(f"Demucs xatosi: {proc.stderr.decode(errors='replace')[-800:]}")
    stem_dir = out_dir / s.demucs_model / audio_wav.stem
    vocals = stem_dir / "vocals.wav"
    no_vocals = stem_dir / "no_vocals.wav"
    if not vocals.exists() or not no_vocals.exists():
        raise RuntimeError(f"Demucs natijasi topilmadi: {stem_dir}")
    final_vocals = out_dir / "vocals.wav"
    final_acc = out_dir / "accompaniment.wav"
    # 16-bit PCM 44.1k ga keltirish (keyingi bosqichlar uchun)
    ffmpeg.extract_audio(vocals, final_vocals, channels=2)
    ffmpeg.extract_audio(no_vocals, final_acc, channels=2)
    return Stems(final_vocals, final_acc, "demucs")


def _separate_center_cancel(audio_wav: Path, out_dir: Path) -> Stems:
    out_dir.mkdir(parents=True, exist_ok=True)
    vocals = out_dir / "vocals.wav"
    acc = out_dir / "accompaniment.wav"
    # Vokal odatda markazda: M = (L+R)/2 → vokal + markazdagi boshqa tovushlar
    ffmpeg.run(["-i", str(audio_wav), "-af", "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,highpass=f=120,lowpass=f=7000",
                "-c:a", "pcm_s16le", str(vocals)])
    # S = L−R → markaziy vokal yoʻqoladi
    ffmpeg.run(["-i", str(audio_wav), "-af", "pan=stereo|c0=c0-c1|c1=c1-c0", "-c:a", "pcm_s16le", str(acc)])
    return Stems(vocals, acc, "center-cancel")
