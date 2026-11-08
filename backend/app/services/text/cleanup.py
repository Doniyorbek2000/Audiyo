"""PDF / OCR dan olingan "qattiq uzilgan" matnni kitob tuzilmasiga keltirish.

Skaner qilingan kitoblar matnida odatda:
- har satr sahifa kengligida uzilgan, soʻzlar tire bilan boʻlingan ("ҳа-\\nракат");
- har sahifada takrorlanuvchi sarlavha (kolontitul) va sahifa raqami bor;
- mundarija qatorlari ("Kirish ...... 9"), mualliflik sahifasi, ISBN;
- bob sarlavhasi: alohida qatordagi raqam + KATTA HARFLI nom (bir necha qator);
- yangi paragraf satr boshidagi chekinish bilan belgilanadi;
- sahifa pastidagi izohlar ("1 Ushbu fikrga ...");
- OCR xatolari: "Л" → "/1", tasodifiy belgilar.

`clean_ocr_text` shularni olib tashlab, `RawChapter` roʻyxatini qaytaradi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.services.text.segmenter import RawChapter

_UPPER = "A-ZА-ЯЁЎҚҒҲ"
_LOWER = "a-zа-яёўқғҳ"
_TERMINAL = tuple(".!?…:;»\"”)")
_BULLETS = "•»♦▪●◦■*-–—"
_JUNK_ONLY = re.compile(r"^[\W\d_]{0,6}$")
_PAGE_NO = re.compile(r"^\s*(?:\|\s*\d{1,3}|\d{1,3}\s*\||\d{1,3})\s*$")
_TOC_LINE = re.compile(r"\S.*\S\s{2,}\d{1,3}\s*$")
_FOOTNOTE = re.compile(rf"^\s*\d{{1,2}}\s+[{_UPPER}{_LOWER}\"“«]")
_FRONT_MATTER = re.compile(r"ISBN|18В\^|©|УЎК|УДК|КБК|ББК|\bМЧЖ\b|Barcha huquqlar|Ҳамма ҳуқуқлар", re.I)
_CHAPTER_NO = re.compile(r"^\s*(\d{1,2})\s*$")
_TOC_HEAD = re.compile(r"^\s*(МУНДАРИЖА|МУНДАРИЖ|ОГЛАВЛЕНИЕ|СОДЕРЖАНИЕ|MUNDARIJA|CONTENTS)\s*$", re.I)
_TOC_ENTRY = re.compile(r"^(?P<indent>\s*)(?P<title>\S.*?\S)\s{2,}(?P<page>\d{1,3})\s*$")
_NAMED = re.compile(
    r"^(КИРИШ|ХОТИМА|ИЛОВА|ТАШАККУРНОМА|МУҚАДДИМА|СЎЗБОШИ|СЎЗ БОШИ|ЭПИЛОГ|ПРОЛОГ|"
    r"KIRISH|XOTIMA|ILOVA|TASHAKKURNOMA|MUQADDIMA|SOʻZBOSHI|EPILOG|PROLOG)\b", re.I)


@dataclass
class _Line:
    text: str  # chap-oʻng boʻshliqsiz
    indent: int
    blank_before: int


def looks_hard_wrapped(text: str) -> bool:
    """Satrlar qisqa va koʻpi gap oxirisiz tugasa — PDF/OCR matni."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 200:
        return False
    avg = sum(len(ln) for ln in lines) / len(lines)
    open_ended = sum(1 for ln in lines if not ln.endswith(_TERMINAL)) / len(lines)
    return avg < 95 and open_ended > 0.45


def _fix_ocr(s: str) -> str:
    s = re.sub(rf"(?<=[{_UPPER}])/1|/1(?=[{_UPPER}])", "Л", s)
    s = re.sub(rf"(?<=[{_LOWER}])/1|/1(?=[{_LOWER}])", "л", s)
    s = s.replace("­", "").replace("�", "")
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s


def _is_caps(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) >= 0.85


def _letters_ratio(s: str) -> float:
    s = s.replace(" ", "")
    return sum(c.isalpha() for c in s) / len(s) if s else 0.0


def _is_junk(s: str) -> bool:
    if _JUNK_ONLY.match(s):
        return s not in ("* * *", "***")
    letters = sum(c.isalpha() for c in s)
    return letters < 3 or (len(s) < 25 and _letters_ratio(s) < 0.55)


def _norm_header(s: str) -> str:
    return re.sub(r"[^\w]", "", _fix_ocr(s)).upper()


def _running_header_keys(stripped: list[str]) -> dict[str, str]:
    """normallashgan qator → guruh vakili (faqat 4+ martalik guruhlar)."""
    reps: list[list[str]] = []  # [vakil, ...aʼzolar]
    for s in stripped:
        if not (0 < len(s) <= 70 and _is_caps(s)):
            continue
        n = _norm_header(s)
        if len(n) < 6:
            continue
        for group in reps:
            rep = group[0]
            if abs(len(rep) - len(n)) <= max(3, len(rep) // 5) and SequenceMatcher(None, rep, n).ratio() >= 0.8:
                group.append(n)
                break
        else:
            reps.append([n])
    out: dict[str, str] = {}
    for group in reps:
        if len(group) >= 4:
            for n in group:
                out[n] = group[0]
    return out


def _prepare(text: str) -> list[_Line]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").split("\n")
    stripped = [ln.strip() for ln in raw]
    # Kolontitullar: 4+ marta takrorlangan qisqa qatorlar (birinchisi sarlavha boʻlishi mumkin)
    # Kolontitullar: OCR har sahifada biroz boshqacha buzadi, shuning uchun butun qator
    # oʻxshashligi (≥ 0.8) boʻyicha guruhlanadi; 4+ martalik guruh — kolontitul
    running = _running_header_keys(stripped)

    out: list[_Line] = []
    blanks = 0
    for ln, s in zip(raw, stripped, strict=True):
        if not s:
            blanks += 1
            continue
        if _is_caps(s) and len(s) <= 70 and _norm_header(s) in running:
            continue  # kolontitul (haqiqiy sarlavhalar mundarija orqali topiladi)
        if _PAGE_NO.match(s) and not _CHAPTER_NO.match(s):
            continue
        if _TOC_LINE.match(s) and len(s) < 120:
            continue
        if _is_junk(s) and not _CHAPTER_NO.match(s):
            continue
        out.append(_Line(_fix_ocr(s), len(ln) - len(ln.lstrip()), blanks))
        blanks = 0
    return out


def _heading_at(lines: list[_Line], i: int, require_blank: bool = True) -> tuple[str | None, str, int]:
    """(raqam, sarlavha, keyingi indeks) — i da sarlavha boʻlmasa ("", "", i)."""
    number = None
    j = i
    m = _CHAPTER_NO.match(lines[j].text)
    if m and j + 1 < len(lines) and _is_caps(lines[j + 1].text):
        number, j = m.group(1), j + 1
    parts: list[str] = []
    while j < len(lines) and _is_caps(lines[j].text) and len(lines[j].text) <= 70 and len(parts) < 4:
        parts.append(lines[j].text)
        j += 1
    if not parts:
        return None, "", i
    title = " ".join(parts)
    # Bitta qisqa katta harfli qator matn ichida ham uchraydi: sarlavha deb faqat
    # oldida boʻsh qator boʻlsa yoki raqam bilan kelsa hisoblaymiz
    if require_blank and number is None and lines[i].blank_before == 0 and i > 0:
        return None, "", i
    return number, title, j


def _title_case(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .:")
    return s[:1].upper() + s[1:].lower() if _is_caps(s) else s


def _paragraphs(lines: list[_Line]) -> list[str]:
    paras: list[str] = []
    cur = ""
    skip_footnote = False
    for k, ln in enumerate(lines):
        s = ln.text
        nxt = lines[k + 1] if k + 1 < len(lines) else None
        prev_done = not cur or cur.rstrip().endswith(_TERMINAL)

        if skip_footnote:
            if ln.blank_before == 0 and not _FOOTNOTE.match(s):
                continue
            skip_footnote = False
        if _FOOTNOTE.match(s) and prev_done and ln.blank_before == 0 and k > 0:
            skip_footnote = True
            continue

        # OCR dialog tiresini boʻshliqsiz oʻqiydi: "-Hozir nechanchi yil?" → "— Hozir ..."
        dialogue = re.match(rf"^[-–—]\s*(?=[{_UPPER}{_LOWER}\d«\"])", s) is not None
        if dialogue:
            s = re.sub(r"^[-–—]\s*", "— ", s)
        bullet = not dialogue and s[0] in _BULLETS and len(s) > 2 and s[1] in " \t"
        indented = nxt is not None and ln.indent > nxt.indent
        new_para = prev_done and (bullet or dialogue or indented or ln.blank_before >= 2)
        if new_para and cur:
            paras.append(cur.strip())
            cur = ""
        if bullet:
            s = s[1:].strip()
        if not cur:
            cur = s
        elif re.search(rf"[{_LOWER}{_UPPER}]-$", cur) and s[:1].islower():
            cur = cur[:-1] + s  # soʻz ichidagi bogʻlovchi tire
        else:
            cur = f"{cur} {s}"
    if cur.strip():
        paras.append(cur.strip())
    return [re.sub(r"\s{2,}", " ", p) for p in paras if _letters_ratio(p) > 0.5]


@dataclass
class TocEntry:
    title: str
    indent: int
    is_part: bool = False
    number: int | None = None


def _norm_letters(s: str) -> str:
    return re.sub(r"[^\w]|\d|_", "", _fix_ocr(s)).lower()


def extract_toc(text: str) -> tuple[list[TocEntry], range | None]:
    """Mundarijani oʻqiydi: (yozuvlar, matndagi satrlar oraligʻi)."""
    lines = text.replace("\r", "").split("\n")
    start = next((i for i, ln in enumerate(lines) if _TOC_HEAD.match(ln)), None)
    if start is None:
        return [], None
    entries: list[TocEntry] = []
    buf: list[str] = []
    buf_indent: int | None = None
    last = start
    for i in range(start + 1, min(len(lines), start + 600)):
        raw = lines[i].rstrip()
        st = raw.strip()
        if not st:
            continue
        m = _TOC_ENTRY.match(raw)
        if m:
            indent = buf_indent if buf_indent is not None else len(m.group("indent"))
            title = re.sub(r"\s+", " ", " ".join([*buf, m.group("title")])).strip()
            entries.append(TocEntry(_fix_ocr(title), indent))
            buf, buf_indent, last = [], None, i
        elif i - last <= 6 and len(st) <= 90:
            if not _is_junk(st):
                if not buf:
                    buf_indent = len(raw) - len(raw.lstrip())
                buf.append(st)
        else:
            break
    if len(entries) < 3:
        return [], None
    # Boʻlim (part): keyingi yozuv undan chuqurroq chekinishda boʻlsa
    for k, e in enumerate(entries[:-1]):
        e.is_part = entries[k + 1].indent > e.indent + 1
    # Bob raqamlari: oddiy boʻlim (part) ichidagi yozuvlar ketma-ket raqamlanadi.
    # Kirish/Xotima/Ilova/Tashakkurnoma va ularning bolalari raqamsiz (chekinish sahifadan
    # sahifaga oʻzgargani uchun tuzilma boʻyicha aniqlanadi)
    n, in_part = 0, False
    for e in entries:
        if _NAMED.match(e.title):
            in_part = False
        elif e.is_part:
            in_part = True
        elif in_part:
            n += 1
            e.number = n
    return entries, range(start, last + 1)


def _toc_title(e: TocEntry) -> str:
    words = e.title.split()
    k = 0
    while k < len(words) and len(re.sub(r"\W", "", words[k])) >= 2 and _is_caps(words[k]):
        k += 1
    if k == 0:
        title = e.title
    elif k == len(words):
        title = _title_case(e.title)
    else:
        head = _title_case(" ".join(words[:k]).rstrip("."))
        title = f"{head}. {' '.join(words[k:])}"
    return f"{e.number}-bob. {title}" if e.number else title


def _similar(a: str, b: str) -> float:
    a, b = _norm_letters(a), _norm_letters(b)
    if not a or not b:
        return 0.0
    if len(a) > len(b) * 1.6:  # sarlavha + tasodifiy qoʻshimcha qatorlar
        a = a[: int(len(b) * 1.3)]
    return SequenceMatcher(None, a, b).ratio()


def _is_label_noise(s: str) -> bool:
    words = s.split()
    if len(words) < 2:
        return True
    short = sum(1 for w in words if len(re.sub(r"\W", "", w)) <= 1)
    avg = sum(len(w) for w in words) / len(words)
    return short > 0 or avg < 4


def clean_ocr_text(text: str) -> list[RawChapter]:
    toc, toc_range = extract_toc(text)
    if toc_range is not None:
        lines_raw = text.replace("\r", "").split("\n")
        text = "\n".join("" if i in toc_range else ln for i, ln in enumerate(lines_raw))
    lines = _prepare(text)
    return _split_with_toc(lines, toc) if toc else _split_numbered(lines)


def _split_with_toc(lines: list[_Line], toc: list[TocEntry]) -> list[RawChapter]:
    chapters: list[RawChapter] = []
    title: str | None = None
    body: list[_Line] = []
    pending_part: str | None = None
    ptr = 0

    def flush() -> None:
        nonlocal body, title, pending_part
        paras = _paragraphs(body)
        if title is None and pending_part and sum(len(p) for p in paras) > 300:
            title, pending_part = pending_part, None
        if title or paras:
            chapters.append(RawChapter(title=title, paragraphs=paras))
        body, title = [], None

    i = 0
    while i < len(lines):
        number, head, j = _heading_at(lines, i, require_blank=False)
        if head:
            cand = head
            best, best_k = 0.0, -1
            for k in range(ptr, min(len(toc), ptr + 4)):
                score = _similar(cand, toc[k].title)
                # Sarlavha mundarijadagi nomning faqat bir qismi boʻlishi mumkin (part: "BIRINCHI QOIDA")
                if toc[k].is_part:
                    head_only = toc[k].title.split(".")[0]
                    score = max(score, _similar(cand, head_only) - 0.05)
                # Boʻlim sarlavhalari bir-biriga oʻxshash ("... QOIDA. Odat ... boʻlishi kerak"):
                # ularga qattiqroq chegara; mundarijada oldinroq turgan yozuv afzal
                score -= 0.04 * (k - ptr) + (0.08 if toc[k].is_part else 0.0)
                if score > best:
                    best, best_k = score, k
            if best >= 0.72:
                flush()
                entry = toc[best_k]
                ptr = best_k + 1
                if entry.is_part:
                    pending_part = _toc_title(entry)
                    # Boʻlim va birinchi bob sarlavhasi bitta blokda boʻlishi mumkin
                    if ptr < len(toc) and not toc[ptr].is_part:
                        both = f"{entry.title} {toc[ptr].title}"
                        if _similar(cand, both) >= 0.72 and len(_norm_letters(cand)) > len(_norm_letters(entry.title)) * 1.3:
                            title = f"{pending_part}. {_toc_title(toc[ptr])}"
                            pending_part = None
                            ptr += 1
                else:
                    t = _toc_title(entry)
                    title = f"{pending_part}. {t}" if pending_part else t
                    pending_part = None
                i = j
                continue
            # Mundarijada yoʻq katta harfli qator: ichki sarlavha yoki rasm yozuvi
            if not _is_label_noise(head):
                body.append(_Line(_title_case(head) + ".", 8, 2))
            i = j
            continue
        body.append(lines[i])
        i += 1
    flush()
    return _finalize(chapters)


def _split_numbered(lines: list[_Line]) -> list[RawChapter]:
    """Mundarija boʻlmasa: raqamli sarlavhalar (va KIRISH/XOTIMA kabi nomli boʻlimlar) boʻyicha."""
    chapters: list[RawChapter] = []
    title: str | None = None
    body: list[_Line] = []
    last_no = 0

    def flush() -> None:
        nonlocal body, title
        paras = _paragraphs(body)
        if title or paras:
            chapters.append(RawChapter(title=title, paragraphs=paras))
        body, title = [], None

    i = 0
    while i < len(lines):
        number, head, j = _heading_at(lines, i)
        if head and ((number and last_no < int(number) <= last_no + 3) or _NAMED.match(head)):
            flush()
            if number and not _NAMED.match(head):
                last_no = int(number)
                title = f"{number}-bob. {_title_case(head)}"
            else:
                title = _title_case(head)
            i = j
            continue
        if head:
            if not _is_label_noise(head):
                body.append(_Line(_title_case(head) + ".", 8, 2))
            i = j
            continue
        body.append(lines[i])
        i += 1
    flush()
    return _finalize(chapters)


def _finalize(chapters: list[RawChapter]) -> list[RawChapter]:
    # Boshidagi mualliflik sahifasi va juda qisqa boʻlimlarni olib tashlash
    while chapters and (
        chapters[0].title is None
        and (_FRONT_MATTER.search(" ".join(chapters[0].paragraphs)) or sum(len(p) for p in chapters[0].paragraphs) < 200)
    ):
        chapters.pop(0)
    merged: list[RawChapter] = []
    for ch in chapters:
        if merged and not merged[-1].paragraphs:
            prev = merged.pop()
            ch = RawChapter(title=". ".join(t for t in (prev.title, ch.title) if t), paragraphs=ch.paragraphs)
        merged.append(ch)
    return merged
