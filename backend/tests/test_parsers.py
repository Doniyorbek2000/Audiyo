import io
import zipfile

from app.services.text.parsers import detect_format, parse_book

FB2 = """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"><body>
<section><title><p>1-bob</p></title><p>Matn bir.</p><p>— Salom, — dedi Ali.</p></section>
<section><title><p>2-bob</p></title><p>Ikkinchi.</p></section>
</body><body name="notes"><section><p>Izoh</p></section></body></FictionBook>""".encode()


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_fb2_chapters_and_notes_skipped():
    chapters = parse_book(FB2, "fb2")
    assert [c.title for c in chapters] == ["1-bob", "2-bob"]
    assert chapters[0].paragraphs == ["Matn bir.", "— Salom, — dedi Ali."]


def test_epub_headings_merge_and_scene_break():
    data = _zip(
        {
            "META-INF/container.xml": '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>',
            "OEBPS/c.opf": '<package><manifest><item id="a" href="t/a.xhtml" media-type="application/xhtml+xml"/>'
            '</manifest><spine><itemref idref="a"/></spine></package>',
            "OEBPS/t/a.xhtml": "<html><head><title>x</title></head><body><h1>Birinchi bob</h1><h2>Boshlanish</h2>"
            "<p>Bu juda uzun birinchi paragraf matni, qirq belgidan oshadi albatta.</p><hr/><p>Yana.</p></body></html>",
        }
    )
    chapters = parse_book(data, "epub")
    assert len(chapters) == 1
    assert chapters[0].title == "Birinchi bob — Boshlanish"
    assert chapters[0].paragraphs[1] == "* * *"


def test_docx_heading_style():
    data = _zip(
        {
            "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Muqaddima</w:t></w:r></w:p>'
            "<w:p><w:r><w:t>Salom </w:t></w:r><w:r><w:t>dunyo.</w:t></w:r></w:p></w:body></w:document>"
        }
    )
    chapters = parse_book(data, "docx")
    assert chapters[0].title == "Muqaddima"
    assert chapters[0].paragraphs == ["Salom dunyo."]


def test_txt_cp1251_and_detect_format():
    data = "1-bob\n\nПривет мир.".encode("cp1251")
    chapters = parse_book(data, "txt")
    assert chapters[0].title == "1-bob"
    assert detect_format("Kitob.EPUB") == "epub"
