"""FFmpeg / ffprobe yordamchilari."""
from __future__ import annotations

import json
import shutil
from array import array
import subprocess
from functools import lru_cache
from pathlib import Path

SAMPLE_RATE = 44100


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], timeout: float | None = 3600) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg xatosi ({' '.join(args[:6])}…): {proc.stderr.decode(errors='replace')[-800:]}")
    return proc


def probe(path: str | Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe xatosi: {proc.stderr.decode(errors='replace')[-500:]}")
    return json.loads(proc.stdout)


def duration_seconds(path: str | Path) -> float:
    info = probe(path)
    dur = info.get("format", {}).get("duration")
    if dur is None:
        streams = [s for s in info.get("streams", []) if s.get("duration")]
        dur = streams[0]["duration"] if streams else 0
    return float(dur)


def has_stream(path: str | Path, kind: str) -> bool:
    return any(s.get("codec_type") == kind for s in probe(path).get("streams", []))


@lru_cache
def has_filter(name: str) -> bool:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, timeout=30)
    return any(line.split()[1:2] == [name] for line in proc.stdout.decode().splitlines() if line.strip())


def extract_audio(src: str | Path, dst: str | Path, *, channels: int = 2, sample_rate: int = SAMPLE_RATE) -> Path:
    run(["-i", str(src), "-vn", "-ac", str(channels), "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)])
    return Path(dst)


def to_wav(src: str | Path, dst: str | Path, *, channels: int = 1, sample_rate: int = SAMPLE_RATE) -> Path:
    return extract_audio(src, dst, channels=channels, sample_rate=sample_rate)


def cut(src: str | Path, dst: str | Path, start: float, end: float) -> Path:
    run(["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src), "-c:a", "pcm_s16le", str(dst)])
    return Path(dst)


def waveform_peaks(src: str | Path, points_per_second: int = 50, max_points: int = 20000) -> list[float]:
    """Toʻlqin choʻqqilari (0..1) — WaveSurfer.js `peaks` uchun."""
    dur = duration_seconds(src)
    pps = max(1, min(points_per_second, int(max_points / max(dur, 1))))
    rate = min(8000, max(400, pps * 40))
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(rate),
         "-f", "s16le", "-"],
        capture_output=True,
        timeout=1800,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.decode(errors="replace")[-500:])
    raw = proc.stdout
    n = len(raw) // 2
    if n == 0:
        return []
    samples = array("h")
    samples.frombytes(raw[: n * 2])
    window = max(1, rate // pps)
    peaks = [max(abs(s) for s in samples[i : i + window]) / 32768 for i in range(0, n, window)]
    return [round(p, 3) for p in peaks]


def time_stretch(src: str | Path, dst: str | Path, ratio: float) -> Path:
    """ratio > 1 — tezlashtirish (qisqartirish), ratio < 1 — sekinlashtirish. Ohang (pitch) oʻzgarmaydi.
    rubberband mavjud boʻlsa — yuqori sifat, aks holda atempo."""
    if abs(ratio - 1.0) < 0.005:
        run(["-i", str(src), "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
        return Path(dst)
    if has_filter("rubberband"):
        flt = f"rubberband=tempo={ratio:.4f}:pitch=1:transients=crisp:formant=preserved"
    else:
        flt = atempo_chain(ratio)
    run(["-i", str(src), "-filter:a", flt, "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return Path(dst)


def atempo_chain(ratio: float) -> str:
    """atempo 0.5..2.0 oraligʻida ishlaydi; tashqarisi uchun zanjir quriladi."""
    parts: list[str] = []
    r = ratio
    while r > 2.0:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append(f"atempo={r:.4f}")
    return ",".join(parts)


def make_silence(dst: str | Path, seconds: float, *, channels: int = 1, sample_rate: int = SAMPLE_RATE) -> Path:
    layout = "mono" if channels == 1 else "stereo"
    run(["-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl={layout}", "-t", f"{max(seconds, 0.001):.3f}",
         "-c:a", "pcm_s16le", str(dst)])
    return Path(dst)


def concat_wavs(paths: list[Path], dst: str | Path, workdir: Path) -> Path:
    """Bir xil formatdagi WAV larni ketma-ket birlashtirish (concat demuxer)."""
    if not paths:
        raise FFmpegError("Birlashtirish uchun fayl yoʻq")
    lst = workdir / f"concat_{Path(dst).stem}.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in paths), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", str(dst)])
    return Path(dst)


def loudnorm(src: str | Path, dst: str | Path, *, integrated: float = -16.0, true_peak: float = -1.5,
             lra: float = 11.0, codec: list[str] | None = None) -> Path:
    run(["-i", str(src), "-af", f"loudnorm=I={integrated}:TP={true_peak}:LRA={lra}",
         "-ar", str(SAMPLE_RATE), *(codec or ["-c:a", "pcm_s16le"]), str(dst)])
    return Path(dst)


def which(binary: str) -> bool:
    return shutil.which(binary) is not None
