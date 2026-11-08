"""Kitob fayllaridan bob/paragraf tuzilmasini ajratib olish: EPUB, FB2, DOCX, PDF, TXT."""
from __future__ import annotations

import posixpath
import re
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from app.services.text.segmenter import CHAPTER_HEADING, RawChapter, split_into_chapters

SUPPORTED_FORMATS = {"epub", "fb2", "docx", "pdf", "txt"}


class UnsupportedFormat(ValueError):
    pass


def detect_format(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_FORMATS:
        raise UnsupportedFormat(f"Qoʻllab-quvvatlanmaydigan format: .{ext}")
    return ext


def parse_book(data: bytes, fmt: str) -> list[RawChapter]:
    fmt = fmt.lower()
    if fmt == "txt":
        chapters = split_into_chapters(_decode(data))
    elif fmt == "fb2":
        chapters = parse_fb2(data)
    elif fmt == "epub":
        chapters = parse_epub(data)
    elif fmt == "docx":
        chapters = parse_docx(data)
    elif fmt == "pdf":
        chapters = parse_pdf(data)
    else:
        raise UnsupportedFormat(fmt)
    return [c for c in chapters if c.paragraphs or c.title]


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- FB2


def parse_fb2(data: bytes) -> list[RawChapter]:
    root = ET.fromstring(data)
    ns = {"fb": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    q = (lambda t: f"fb:{t}") if ns else (lambda t: t)
    chapters: list[RawChapter] = []

    def text_of(el) -> str:
        return _clean("".join(el.itertext()))

    def walk(section, depth: int) -> None:
        title_el = section.find(q("title"), ns)
        title = text_of(title_el) if title_el is not None else None
        subsections = section.findall(q("section"), ns)
        paragraphs: list[str] = []
        for child in section:
            tag = child.tag.split("}")[-1]
            if tag in ("p", "v", "subtitle", "text-author"):
                t = text_of(child)
                if t:
                    paragraphs.append(t)
            elif tag == "empty-line":
                continue
            elif tag in ("poem", "cite", "epigraph"):
                for p in child.iter():
                    if p.tag.split("}")[-1] in ("p", "v") and text_of(p):
                        paragraphs.append(text_of(p))
        if paragraphs or (title and not subsections):
            chapters.append(RawChapter(title=title, paragraphs=paragraphs))
        elif title and subsections and depth == 0:
            chapters.append(RawChapter(title=title, paragraphs=[]))
        for sub in subsections:
            walk(sub, depth + 1)

    for body in root.findall(q("body"), ns):
        if body.get("name") == "notes":
            continue
        for section in body.findall(q("section"), ns):
            walk(section, 0)
    # Boʻsh sarlavhali "bob" larni keyingisi bilan birlashtirish
    merged: list[RawChapter] = []
    for ch in chapters:
        if merged and not merged[-1].paragraphs:
            prev = merged.pop()
            ch = RawChapter(
                title=" — ".join(t for t in (prev.title, ch.title) if t), paragraphs=ch.paragraphs
            )
        merged.append(ch)
    return merged


# --------------------------------------------------------------------------- EPUB


class _XHTMLExtractor(HTMLParser):
    BLOCK = {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "section"}
    HEADINGS = {"h1", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []  # (kind, text)
        self._buf: list[str] = []
        self._kind = "p"
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag in self.BLOCK:
            self._flush()
            self._kind = "h" if tag in self.HEADINGS else "p"
        elif tag == "hr":
            self._flush()
            self.items.append(("p", "* * *"))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def _flush(self):
        text = _clean("".join(self._buf))
        self._buf.clear()
        if text:
            self.items.append((self._kind, text))
        self._kind = "p"

    def close(self):
        super().close()
        self._flush()


def parse_epub(data: bytes) -> list[RawChapter]:
    zf = zipfile.ZipFile(BytesIO(data))
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = next(el for el in container.iter() if el.tag.endswith("rootfile")).get("full-path")
    opf = ET.fromstring(zf.read(rootfile))
    base = posixpath.dirname(rootfile)
    manifest = {
        it.get("id"): it.get("href")
        for it in opf.iter()
        if it.tag.endswith("item") and (it.get("media-type") or "").startswith("application/xhtml")
    }
    spine = [it.get("idref") for it in opf.iter() if it.tag.endswith("itemref")]

    chapters: list[RawChapter] = []
    for idref in spine:
        href = manifest.get(idref)
        if not href:
            continue
        path = posixpath.normpath(posixpath.join(base, href.split("#")[0]))
        try:
            html = zf.read(path).decode("utf-8", errors="replace")
        except KeyError:
            continue
        ex = _XHTMLExtractor()
        ex.feed(html)
        ex.close()
        current: RawChapter | None = None
        for kind, text in ex.items:
            if kind == "h":
                if current and current.title and not current.paragraphs:
                    current.title = f"{current.title} — {text}"  # ketma-ket sarlavhalar
                    continue
                if current and (current.paragraphs or current.title):
                    chapters.append(current)
                current = RawChapter(title=text, paragraphs=[])
            else:
                if current is None:
                    current = RawChapter(title=None, paragraphs=[])
                current.paragraphs.append(text)
        if current and (current.paragraphs or current.title):
            chapters.append(current)
    # Juda qisqa (muqova, mundarija) bob larni olib tashlash
    return [c for c in chapters if sum(len(p) for p in c.paragraphs) > 40 or (c.title and c.paragraphs)]


# --------------------------------------------------------------------------- DOCX

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def parse_docx(data: bytes) -> list[RawChapter]:
    zf = zipfile.ZipFile(BytesIO(data))
    doc = ET.fromstring(zf.read("word/document.xml"))
    chapters: list[RawChapter] = []
    current = RawChapter(title=None, paragraphs=[])
    for p in doc.iter(f"{_W}p"):
        style_el = p.find(f"{_W}pPr/{_W}pStyle")
        style = (style_el.get(f"{_W}val") or "") if style_el is not None else ""
        text = _clean("".join(t.text or "" for t in p.iter(f"{_W}t")))
        if not text:
            continue
        is_heading = style.lower().startswith(("heading1", "heading2", "title")) or style in ("1", "2")
        if is_heading or (CHAPTER_HEADING.match(text) and len(text) <= 120):
            if current.paragraphs or current.title:
                chapters.append(current)
            current = RawChapter(title=text, paragraphs=[])
        else:
            current.paragraphs.append(text)
    if current.paragraphs or current.title:
        chapters.append(current)
    return chapters


# --------------------------------------------------------------------------- PDF


def parse_pdf(data: bytes) -> list[RawChapter]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages)
    # Satr oxiridagi defis bilan boʻlingan soʻzlarni birlashtirish
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Sahifa raqamlarini olib tashlash
    text = re.sub(r"\n\s*\d{1,4}\s*\n", "\n", text)
    # PDF da paragraflar odatda bitta \n bilan; gap oxiri + yangi satr = paragraf
    text = re.sub(r"(?<=[.!?…»])\n(?=[A-ZÀ-ÝА-ЯЁЎҚҒҲ—«])", "\n\n", text)
    return split_into_chapters(text)
