"""Muhit tovushlari (soundscape): sahnalar uchun fon tovushini yaratish va nutq ostiga mikslash.

1. SFX provayderi (ElevenLabs Sound Effects) sahna tavsifidan ~20 s lik fon tovushi yaratadi
   (S3 da kesh: bir xil tavsif qayta yaratilmaydi).
2. Fon sahna uzunligiga yetguncha takrorlanadi, kirish/chiqishda ohista paydo boʻlib yoʻqoladi.
3. Bob uzunligidagi fon yoʻlakchasi yigʻiladi va nutq bilan sidechain ducking orqali mikslanadi:
   gap paytida fon pasayadi, pauzalarda biroz koʻtariladi — tinglovchi sahna ichida boʻladi,
   lekin nutq hech qachon koʻmilib qolmaydi.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from app.config import get_settings
from app.services.media import ffmpeg

log = logging.getLogger(__name__)

SFX_SECONDS = 20.0
FADE_IN_S = 2.0
FADE_OUT_S = 2.5
# Fon balandligi (normallashtirilgan SFX ga nisbatan, dB). Nutq −18 LUFS atrofida.
INTENSITY_GAIN_DB = {"low": -17.0, "medium": -12.0}


class SFXUnavailable(RuntimeError):
    pass


class SFXProvider(Protocol):
    def generate(self, prompt: str, seconds: float) -> bytes: ...


class ElevenLabsSFX:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.api_key = api_key or s.elevenlabs_api_key
        self.base_url = (base_url or s.elevenlabs_base_url).rstrip("/")
        self._http = httpx.Client(timeout=120, transport=transport)

    def generate(self, prompt: str, seconds: float = SFX_SECONDS) -> bytes:
        if not self.api_key:
            raise SFXUnavailable("ELEVENLABS_API_KEY sozlanmagan")
        resp = self._http.post(
            f"{self.base_url}/v1/sound-generation",
            json={"text": prompt, "duration_seconds": max(0.5, min(30.0, seconds)), "prompt_influence": 0.45},
            headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
        )
        if resp.status_code in (401, 402, 403):
            raise SFXUnavailable(f"ElevenLabs sound_generation: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise RuntimeError(f"ElevenLabs SFX {resp.status_code}: {resp.text[:200]}")
        return resp.content


def get_sfx_provider() -> SFXProvider | None:
    return ElevenLabsSFX() if get_settings().elevenlabs_api_key else None


def cache_key(prompt: str) -> str:
    return "sfx/" + hashlib.sha256(prompt.strip().lower().encode()).hexdigest()[:24] + ".mp3"


@dataclass(frozen=True)
class PlacedScene:
    start_ms: int
    end_ms: int
    source: Path  # yaratilgan fon (mp3/wav)
    intensity: str = "low"


def _scene_bed(scene: PlacedScene, dst: Path) -> Path:
    """Fonni sahna uzunligiga yetguncha takrorlab, fade bilan tayyorlaydi (mono 44.1k)."""
    dur = max(0.5, (scene.end_ms - scene.start_ms) / 1000)
    fade_in = min(FADE_IN_S, dur / 3)
    fade_out = min(FADE_OUT_S, dur / 3)
    gain = INTENSITY_GAIN_DB.get(scene.intensity, INTENSITY_GAIN_DB["low"])
    ffmpeg.run([
        "-stream_loop", "-1", "-i", str(scene.source), "-t", f"{dur:.3f}",
        "-af", (f"aformat=sample_rates={ffmpeg.SAMPLE_RATE}:channel_layouts=mono,"
                f"loudnorm=I=-20:TP=-2:LRA=7,volume={gain}dB,"
                f"afade=t=in:st=0:d={fade_in:.2f},afade=t=out:st={max(0, dur - fade_out):.2f}:d={fade_out:.2f}"),
        "-ar", str(ffmpeg.SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
    ])
    return dst


def build_ambience_track(scenes: list[PlacedScene], total_ms: int, dst: Path, workdir: Path) -> Path | None:
    """Bob uzunligidagi fon yoʻlakchasi (sahnalar oraligʻida jimlik)."""
    if not scenes:
        return None
    workdir.mkdir(parents=True, exist_ok=True)
    beds = [_scene_bed(sc, workdir / f"bed_{i}.wav") for i, sc in enumerate(scenes)]
    args: list[str] = ["-f", "lavfi", "-t", f"{total_ms / 1000:.3f}", "-i",
                       f"anullsrc=r={ffmpeg.SAMPLE_RATE}:cl=mono"]
    for bed in beds:
        args += ["-i", str(bed)]
    chains = [f"[{i + 1}:a]adelay={sc.start_ms}|{sc.start_ms}[d{i}]" for i, sc in enumerate(scenes)]
    inputs = "[0:a]" + "".join(f"[d{i}]" for i in range(len(scenes)))
    graph = ";".join(chains) + f";{inputs}amix=inputs={len(scenes) + 1}:duration=first:normalize=0[out]"
    ffmpeg.run([*args, "-filter_complex", graph, "-map", "[out]", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return dst


def mix_voice_with_ambience(voice_wav: Path, ambience_wav: Path, dst: Path, loudness: float = -18.0) -> Path:
    """Nutq + fon: fon nutq paytida pasayadi (yumshoq sidechain), soʻng umumiy normallash."""
    graph = (
        "[0:a]aformat=channel_layouts=mono,asplit=2[v][sc];"
        "[1:a]aformat=channel_layouts=mono[bg];"
        "[bg][sc]sidechaincompress=threshold=0.02:ratio=4:attack=40:release=600:makeup=1[duck];"
        "[v][duck]amix=inputs=2:duration=first:normalize=0[mix];"
        f"[mix]loudnorm=I={loudness}:TP=-1.5:LRA=11[out]"
    )
    ffmpeg.run(["-i", str(voice_wav), "-i", str(ambience_wav), "-filter_complex", graph, "-map", "[out]",
                "-ar", str(ffmpeg.SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return dst
