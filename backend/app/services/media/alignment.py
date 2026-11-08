"""Audio vaqtini qayta moslash (pitch oʻzgarmaydi) va dialog yoʻlakchasini yigʻish."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.media import ffmpeg

MIN_GAP_S = 0.05  # keyingi segmentgacha qoldiriladigan minimal boʻshliq


@dataclass(frozen=True)
class AlignmentPlan:
    tempo_ratio: float  # >1 tezlashtirish
    window_s: float  # mavjud vaqt oynasi (qarz olingan boʻshliq bilan)
    output_s: float  # moslashtirilgandan keyingi uzunlik
    overflow_s: float  # chegaralar yetmay qolgan qism (kesiladi, fade-out bilan)
    needs_retranslation: bool  # tarjimani qisqartirish tavsiya etiladi


def plan_alignment(
    tts_duration_s: float,
    start_s: float,
    end_s: float,
    next_start_s: float | None,
    *,
    tempo_min: float = 0.85,
    tempo_max: float = 1.25,
) -> AlignmentPlan:
    """Asl segment oynasiga sigʻdirish rejasi.

    1. Maqsad — asl segment davomiyligi (lab harakati bilan mos).
    2. TTS uzun boʻlsa, tempo ≤ tempo_max gacha tezlashtiriladi.
    3. Shunda ham sigʻmasa, keyingi segmentgacha boʻlgan boʻshliqdan "qarz" olinadi.
    4. TTS juda qisqa boʻlsa, ≥ tempo_min gacha sekinlashtiriladi, qolgani jimlik.
    """
    target = max(0.05, end_s - start_s)
    if next_start_s is None:
        available = target + 2.0  # oxirgi segment — bemalol
    else:
        available = max(target, next_start_s - start_s - MIN_GAP_S)
    ratio = tts_duration_s / target
    ratio = max(tempo_min, min(tempo_max, ratio))
    output = tts_duration_s / ratio
    overflow = max(0.0, output - available)
    return AlignmentPlan(
        tempo_ratio=round(ratio, 3),
        window_s=round(available, 3),
        output_s=round(output, 3),
        overflow_s=round(overflow, 3),
        needs_retranslation=tts_duration_s / tempo_max > available,
    )


def apply_alignment(src: Path, dst: Path, plan: AlignmentPlan) -> Path:
    tmp = dst.with_suffix(".stretch.wav")
    ffmpeg.time_stretch(src, tmp, plan.tempo_ratio)
    if plan.overflow_s > 0:
        keep = plan.window_s
        fade = min(0.15, keep / 4)
        ffmpeg.run(["-i", str(tmp), "-t", f"{keep:.3f}", "-af", f"afade=t=out:st={keep - fade:.3f}:d={fade:.3f}",
                    "-c:a", "pcm_s16le", str(dst)])
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(dst)
    return dst


@dataclass(frozen=True)
class Placement:
    path: Path
    start_s: float
    duration_s: float


def build_timeline_track(placements: list[Placement], total_s: float, dst: Path, workdir: Path) -> Path:
    """Kliplarni vaqt boʻyicha jimlik bilan birlashtirib bitta mono WAV hosil qiladi.
    Ustma-ust tushgan kliplar keyingisi boshlanguncha kesiladi."""
    workdir.mkdir(parents=True, exist_ok=True)
    pieces: list[Path] = []
    cursor = 0.0
    ordered = sorted(placements, key=lambda p: p.start_s)
    for idx, p in enumerate(ordered):
        start = max(p.start_s, cursor)
        if start - cursor > 0.001:
            pieces.append(ffmpeg.make_silence(workdir / f"sil_{idx:05d}.wav", start - cursor))
        nxt = ordered[idx + 1].start_s if idx + 1 < len(ordered) else None
        dur = p.duration_s
        if nxt is not None and start + dur > nxt:
            dur = max(0.05, nxt - start)
            clipped = workdir / f"clip_{idx:05d}.wav"
            ffmpeg.run(["-i", str(p.path), "-t", f"{dur:.3f}", "-af",
                        f"afade=t=out:st={max(0, dur - 0.05):.3f}:d=0.05", "-ar", str(ffmpeg.SAMPLE_RATE),
                        "-ac", "1", "-c:a", "pcm_s16le", str(clipped)])
            pieces.append(clipped)
        else:
            norm = workdir / f"norm_{idx:05d}.wav"
            ffmpeg.to_wav(p.path, norm, channels=1)
            pieces.append(norm)
        cursor = start + dur
    if total_s - cursor > 0.001:
        pieces.append(ffmpeg.make_silence(workdir / "sil_tail.wav", total_s - cursor))
    return ffmpeg.concat_wavs(pieces, dst, workdir)
