"""Haqiqiy FFmpeg bilan media testlari."""
import shutil
import wave
from pathlib import Path

import pytest

from app.services.media import alignment, ffmpeg, mixing, separation

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yoʻq")


def tone(path: Path, seconds: float, freq: int = 440, channels: int = 1) -> Path:
    ffmpeg.run(["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-ac", str(channels),
                "-ar", "44100", "-c:a", "pcm_s16le", str(path)])
    return path


def test_time_stretch_preserves_target_duration(tmp_path):
    src = tone(tmp_path / "a.wav", 2.5)
    plan = alignment.plan_alignment(2.5, 0, 2.0, 4.0)
    out = alignment.apply_alignment(src, tmp_path / "b.wav", plan)
    assert ffmpeg.duration_seconds(out) == pytest.approx(2.0, abs=0.05)
    assert ffmpeg.atempo_chain(3.0) == "atempo=2.0,atempo=1.5000"


def test_overflow_is_trimmed(tmp_path):
    src = tone(tmp_path / "a.wav", 4.0)
    plan = alignment.plan_alignment(4.0, 0, 2.0, 2.2)
    out = alignment.apply_alignment(src, tmp_path / "b.wav", plan)
    assert ffmpeg.duration_seconds(out) == pytest.approx(plan.window_s, abs=0.05)


def test_timeline_mix_mux_and_peaks(tmp_path):
    clip1 = tone(tmp_path / "c1.wav", 1.0, 300)
    clip2 = tone(tmp_path / "c2.wav", 1.5, 500)
    track = alignment.build_timeline_track(
        [alignment.Placement(clip1, 0.5, 1.0), alignment.Placement(clip2, 1.2, 1.5)],  # ustma-ust → kesiladi
        5.0, tmp_path / "dialogue.wav", tmp_path / "tl")
    assert ffmpeg.duration_seconds(track) == pytest.approx(5.0, abs=0.05)
    with wave.open(str(track)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 44100

    bgm = tone(tmp_path / "bgm.wav", 5.0, 120, channels=2)
    mix = mixing.mix_with_ducking(track, bgm, tmp_path / "mix.wav")
    assert ffmpeg.duration_seconds(mix) == pytest.approx(5.0, abs=0.1)

    video = tmp_path / "v.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=5", "-f", "lavfi",
                "-i", "sine=frequency=200:duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(video)])
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nSalom\n", encoding="utf-8")
    out = mixing.mux_video(video, mix, tmp_path / "out.mp4", subtitles_srt=srt, original_language="eng")
    streams = ffmpeg.probe(out)["streams"]
    kinds = [s["codec_type"] for s in streams]
    assert kinds.count("audio") == 2 and "subtitle" in kinds and "video" in kinds
    assert streams[1]["tags"]["language"] == "uzb"

    peaks = ffmpeg.waveform_peaks(mix, points_per_second=20)
    assert 90 <= len(peaks) <= 110 and max(peaks) <= 1.0


def test_fallback_separation(tmp_path):
    src = tone(tmp_path / "s.wav", 1.0, channels=2)
    stems = separation._separate_center_cancel(src, tmp_path / "stems")
    assert stems.vocals.exists() and stems.accompaniment.exists()


def test_m4b_export_with_chapters(tmp_path):
    c1, c2 = tone(tmp_path / "1.wav", 1.0), tone(tmp_path / "2.wav", 1.5)
    marks = [mixing.ChapterMark("1-bob", 0, 1000), mixing.ChapterMark("2-bob; oxiri", 1000, 2500)]
    out = mixing.export_m4b([c1, c2], marks, "Kitob", "Muallif", tmp_path / "b.m4b", tmp_path)
    import json
    import subprocess

    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters",
                                      "-show_format", str(out)], capture_output=True).stdout)
    assert [c["tags"]["title"] for c in info["chapters"]] == ["1-bob", "2-bob; oxiri"]
    assert info["format"]["tags"]["title"] == "Kitob"
