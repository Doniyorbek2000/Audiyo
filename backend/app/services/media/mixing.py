"""Yakuniy mikslash, sidechain ducking, video bilan qayta muxlash va audiokitob eksporti."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.media import ffmpeg

VIDEO_LOUDNESS_LUFS = -16.0
BOOK_LOUDNESS_LUFS = -18.0


def mix_with_ducking(dialogue_wav: Path, bgm_wav: Path, dst: Path, *, bgm_gain_db: float = 0.0) -> Path:
    """Fon (BGM+SFX) dialog ostida avtomatik pasayadi (sidechain compressor), soʻng EBU R128 normallash."""
    graph = (
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[dlg][sc];"
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={bgm_gain_db}dB[bgm];"
        "[bgm][sc]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350:makeup=1[ducked];"
        "[ducked][dlg]amix=inputs=2:duration=longest:normalize=0[mix];"
        f"[mix]loudnorm=I={VIDEO_LOUDNESS_LUFS}:TP=-1.5:LRA=11[out]"
    )
    ffmpeg.run(["-i", str(dialogue_wav), "-i", str(bgm_wav), "-filter_complex", graph, "-map", "[out]",
                "-ar", "44100", "-c:a", "pcm_s16le", str(dst)])
    return dst


def mux_video(
    video: Path,
    dubbed_audio: Path,
    dst: Path,
    *,
    subtitles_srt: Path | None = None,
    keep_original_audio: bool = True,
    original_language: str = "und",
) -> Path:
    """Video oqimi koʻchiriladi (qayta kodlanmaydi), dublyaj audio — asosiy, asl audio — ikkinchi yoʻlakcha."""
    is_mkv = dst.suffix.lower() == ".mkv"
    args = ["-i", str(video), "-i", str(dubbed_audio)]
    if subtitles_srt:
        args += ["-i", str(subtitles_srt)]
    args += ["-map", "0:v:0", "-map", "1:a:0"]
    has_original = keep_original_audio and ffmpeg.has_stream(video, "audio")
    if has_original:
        args += ["-map", "0:a:0"]
    if subtitles_srt:
        args += ["-map", "2:s:0"]
    args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    if subtitles_srt:
        args += ["-c:s", "srt" if is_mkv else "mov_text"]
    args += ["-metadata:s:a:0", "language=uzb", "-metadata:s:a:0", "title=Oʻzbekcha dublyaj",
             "-disposition:a:0", "default"]
    if has_original:
        args += ["-metadata:s:a:1", f"language={original_language}", "-metadata:s:a:1", "title=Original",
                 "-disposition:a:1", "0"]
    if subtitles_srt:
        args += ["-metadata:s:s:0", "language=uzb", "-metadata:s:s:0", "title=Oʻzbekcha"]
    if not is_mkv:
        args += ["-movflags", "+faststart"]
    args += ["-shortest", str(dst)]
    ffmpeg.run(args)
    return dst


@dataclass(frozen=True)
class ChapterMark:
    title: str
    start_ms: int
    end_ms: int


def _ffmeta_escape(text: str) -> str:
    for ch in ("\\", "=", ";", "#", "\n"):
        text = text.replace(ch, "\\" + ch)
    return text


def ffmetadata(title: str, author: str | None, chapters: list[ChapterMark]) -> str:
    lines = [";FFMETADATA1", f"title={_ffmeta_escape(title)}"]
    if author:
        lines += [f"artist={_ffmeta_escape(author)}", f"album_artist={_ffmeta_escape(author)}"]
    lines += [f"album={_ffmeta_escape(title)}", "genre=Audiobook"]
    for ch in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={ch.start_ms}", f"END={ch.end_ms}",
                  f"title={_ffmeta_escape(ch.title)}"]
    return "\n".join(lines) + "\n"


def export_m4b(chapter_wavs: list[Path], chapters: list[ChapterMark], title: str, author: str | None,
               dst: Path, workdir: Path) -> Path:
    joined = ffmpeg.concat_wavs(chapter_wavs, workdir / "book_full.wav", workdir)
    meta = workdir / "metadata.txt"
    meta.write_text(ffmetadata(title, author, chapters), encoding="utf-8")
    ffmpeg.run(["-i", str(joined), "-i", str(meta), "-map_metadata", "1", "-map_chapters", "1",
                "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-f", "mp4", str(dst)])
    return dst


def export_mp3(src_wav: Path, dst: Path, title: str, track: int | None = None, album: str | None = None) -> Path:
    args = ["-i", str(src_wav), "-c:a", "libmp3lame", "-b:a", "128k", "-metadata", f"title={title}"]
    if track is not None:
        args += ["-metadata", f"track={track}"]
    if album:
        args += ["-metadata", f"album={album}"]
    ffmpeg.run([*args, str(dst)])
    return dst
