"""STT + diarizatsiya: WhisperX (soʻz darajasidagi vaqt belgilari) + pyannote.audio (spikerlar).

Natija: dublyaj uchun qulay segmentlar — bitta spiker, ≤ MAX_SEGMENT_S, gap/pauza chegarasida boʻlingan.
"""
from __future__ import annotations

import gc
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

MAX_SEGMENT_S = 12.0
MIN_SEGMENT_S = 0.6
PAUSE_SPLIT_S = 0.7
UNKNOWN_SPEAKER = "SPEAKER_00"


@dataclass
class Word:
    text: str
    start: float
    end: float
    speaker: str
    score: float | None = None


@dataclass
class TranscriptSegment:
    speaker: str
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class SpeakerInfo:
    tag: str
    speech_seconds: float
    words_per_second: float
    gender: str = "UNKNOWN"
    age_group: str = "UNKNOWN"
    median_f0: float | None = None


@dataclass
class Transcript:
    language: str
    segments: list[TranscriptSegment]
    speakers: dict[str, SpeakerInfo]


# ------------------------------------------------------------------ WhisperX ishga tushirish


def transcribe(vocals_wav: Path, language: str | None = None) -> Transcript:
    import whisperx  # GPU tugunida oʻrnatilgan

    s = get_settings()
    device = s.whisper_device
    compute_type = "float16" if device == "cuda" else "int8"
    audio = whisperx.load_audio(str(vocals_wav))

    model = whisperx.load_model(s.whisper_model, device, compute_type=compute_type, language=language)
    result = model.transcribe(audio, batch_size=16 if device == "cuda" else 4, language=language)
    detected = result.get("language", language or "en")
    del model
    _free_gpu()

    align_model, metadata = whisperx.load_align_model(language_code=detected, device=device)
    result = whisperx.align(result["segments"], align_model, metadata, audio, device, return_char_alignments=False)
    del align_model
    _free_gpu()

    if s.hf_token:
        try:
            from whisperx.diarize import DiarizationPipeline
        except ImportError:  # eski versiyalar
            DiarizationPipeline = whisperx.DiarizationPipeline  # type: ignore[attr-defined]
        diarize_model = DiarizationPipeline(use_auth_token=s.hf_token, device=device)
        diarize_segments = diarize_model(audio)
        result = whisperx.assign_word_speakers(diarize_segments, result)
        del diarize_model
        _free_gpu()
    else:
        log.warning("HF_TOKEN yoʻq — diarizatsiya oʻtkazib yuborildi, barcha nutq bitta spikerga")

    words = collect_words(result)
    segments = build_segments(words)
    speakers = speaker_stats(segments)
    try:
        estimate_voice_traits(vocals_wav, segments, speakers)
    except Exception as exc:  # noqa: BLE001 — jins taxmini ixtiyoriy
        log.warning("Jinsni taxmin qilib boʻlmadi: %s", exc)
    return Transcript(language=detected, segments=segments, speakers=speakers)


def _free_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


# ------------------------------------------------------------------ toza post-processing


def collect_words(result: dict[str, Any]) -> list[Word]:
    words: list[Word] = []
    for seg in result.get("segments", []):
        seg_speaker = seg.get("speaker") or UNKNOWN_SPEAKER
        seg_words = seg.get("words") or []
        if not seg_words:
            # Tekislanmagan segment — butun segmentni bitta "soʻz" sifatida olamiz
            if seg.get("text", "").strip():
                words.append(Word(seg["text"].strip(), float(seg["start"]), float(seg["end"]), seg_speaker))
            continue
        for i, w in enumerate(seg_words):
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            start = w.get("start")
            end = w.get("end")
            if start is None or end is None:
                # Raqamlar va baʼzi belgilar vaqtsiz qaytadi — qoʻshnilardan interpolyatsiya
                prev_end = words[-1].end if words else float(seg.get("start", 0))
                nxt = next((x for x in seg_words[i + 1 :] if x.get("start") is not None), None)
                start = prev_end
                end = float(nxt["start"]) if nxt else float(seg.get("end", prev_end + 0.3))
            words.append(Word(text, float(start), float(end), w.get("speaker") or seg_speaker, w.get("score")))
    words.sort(key=lambda w: w.start)
    return words


def _ends_sentence(text: str) -> bool:
    return text.rstrip("\"'»)").endswith((".", "!", "?", "…", "。", "？", "！"))


def build_segments(words: list[Word]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    cur: list[Word] = []

    def flush() -> None:
        if cur:
            segments.append(
                TranscriptSegment(
                    speaker=cur[0].speaker,
                    start=round(cur[0].start, 3),
                    end=round(max(w.end for w in cur), 3),
                    text=" ".join(w.text for w in cur).strip(),
                    words=list(cur),
                )
            )
            cur.clear()

    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            duration = w.end - cur[0].start
            speaker_change = w.speaker != cur[-1].speaker
            sentence_break = _ends_sentence(cur[-1].text) and (duration > MAX_SEGMENT_S * 0.5 or gap > 0.3)
            if speaker_change or gap > PAUSE_SPLIT_S or duration > MAX_SEGMENT_S or sentence_break:
                flush()
        cur.append(w)
    flush()

    # Juda qisqa segmentlarni bir xil spikerning qoʻshni segmentiga qoʻshish
    merged: list[TranscriptSegment] = []
    for seg in segments:
        if (
            merged
            and seg.duration < MIN_SEGMENT_S
            and merged[-1].speaker == seg.speaker
            and seg.start - merged[-1].end < PAUSE_SPLIT_S
        ):
            prev = merged[-1]
            prev.end = seg.end
            prev.text = f"{prev.text} {seg.text}"
            prev.words.extend(seg.words)
        else:
            merged.append(seg)
    return merged


def speaker_stats(segments: list[TranscriptSegment]) -> dict[str, SpeakerInfo]:
    stats: dict[str, SpeakerInfo] = {}
    words_count: dict[str, int] = {}
    for seg in segments:
        info = stats.setdefault(seg.speaker, SpeakerInfo(seg.speaker, 0.0, 0.0))
        info.speech_seconds += seg.duration
        words_count[seg.speaker] = words_count.get(seg.speaker, 0) + len(seg.words)
    for tag, info in stats.items():
        info.speech_seconds = round(info.speech_seconds, 3)
        info.words_per_second = round(words_count[tag] / info.speech_seconds, 3) if info.speech_seconds else 0.0
    return stats


# ------------------------------------------------------------------ jins / yosh taxmini (F0)


def classify_f0(median_f0: float | None) -> tuple[str, str]:
    """Asosiy ton chastotasi boʻyicha taxmin: erkak ~85–165 Hz, ayol ~165–255 Hz, bola > 260 Hz."""
    if median_f0 is None:
        return "UNKNOWN", "UNKNOWN"
    if median_f0 >= 260:
        return "UNKNOWN", "CHILD"
    if median_f0 >= 165:
        return "FEMALE", "ADULT"
    return "MALE", "ADULT"


def estimate_voice_traits(vocals_wav: Path, segments: list[TranscriptSegment], speakers: dict[str, SpeakerInfo]) -> None:
    import numpy as np
    import whisperx

    audio = whisperx.load_audio(str(vocals_wav))  # 16 kHz mono float32
    sr = 16000
    per_speaker: dict[str, list[float]] = {}
    for seg in sorted(segments, key=lambda s: -s.duration)[:400]:
        chunk = audio[int(seg.start * sr) : int(seg.end * sr)]
        f0 = _autocorr_f0(np, chunk, sr)
        if f0:
            per_speaker.setdefault(seg.speaker, []).extend(f0)
    for tag, values in per_speaker.items():
        if len(values) >= 5 and tag in speakers:
            med = float(np.median(values))
            speakers[tag].median_f0 = round(med, 1)
            speakers[tag].gender, speakers[tag].age_group = classify_f0(med)


def _autocorr_f0(np, signal, sr: int, frame: float = 0.04) -> list[float]:
    n = int(frame * sr)
    out: list[float] = []
    min_lag, max_lag = int(sr / 400), int(sr / 70)
    for i in range(0, len(signal) - n, n):
        x = signal[i : i + n]
        if np.sqrt(np.mean(x**2)) < 0.02:
            continue
        x = x - x.mean()
        corr = np.correlate(x, x, mode="full")[n - 1 :]
        if corr[0] <= 0:
            continue
        seg = corr[min_lag:max_lag]
        lag = int(np.argmax(seg)) + min_lag
        if seg.max() / corr[0] > 0.3:
            out.append(sr / lag)
    return out
