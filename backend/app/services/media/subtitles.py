"""SRT / VTT subtitrlar."""
from __future__ import annotations

import textwrap
from collections.abc import Iterable
from dataclasses import dataclass

MAX_LINE = 42


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _ts(seconds: float, sep: str) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _wrap(text: str) -> str:
    text = " ".join(text.split())
    lines = textwrap.wrap(text, MAX_LINE)
    if len(lines) > 2:  # 2 qatordan oshmasin: teng uzunlikdagi ikki qatorga boʻlish
        width = len(text) // 2 + 1
        while len(lines := textwrap.wrap(text, width)) > 2:
            width += 2
    return "\n".join(lines)


def to_srt(cues: Iterable[Cue]) -> str:
    out = []
    for i, c in enumerate(cues, 1):
        out.append(f"{i}\n{_ts(c.start, ',')} --> {_ts(c.end, ',')}\n{_wrap(c.text)}\n")
    return "\n".join(out)


def to_vtt(cues: Iterable[Cue]) -> str:
    body = "\n".join(f"{_ts(c.start, '.')} --> {_ts(c.end, '.')}\n{_wrap(c.text)}\n" for c in cues)
    return "WEBVTT\n\n" + body
