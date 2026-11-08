from app.services.llm.attribution import attribute, build_registry, dialogue_shares, guess_gender
from app.services.text.pauses import CHAPTER_END_MS, SCENE_BREAK_MS
from app.services.text.segmenter import (
    parse_dialogue_line,
    parse_quoted_paragraph,
    segment_book,
    split_into_chapters,
    split_long_text,
)

BOOK = """1-bob. Uchrashuv

Kech kirdi. Otabek hovliga chiqdi.
U uzoq oʻyladi.

— Siz meni tashlab ketmaysizmi? — soʻradi Kumush.
— Yoʻq, — dedi Otabek. — Hech qachon.
— Nega?
— Chunki sizni sevaman.
— Rostdanmi?

Kumush pichirladi: «Rahmat sizga.»

* * *

Ertasi kuni hamma narsa oʻzgardi…

2-bob

Yangi kun."""


def test_chapters_and_blocks():
    chapters = segment_book(split_into_chapters(BOOK))
    assert [c.title for c in chapters] == ["1-bob. Uchrashuv", "2-bob"]
    blocks = chapters[0].blocks
    assert blocks[0].block_type == "HEADING"
    assert blocks[1].text == "Kech kirdi. Otabek hovliga chiqdi. U uzoq oʻyladi."
    dialogue = [b for b in blocks if b.block_type == "DIALOGUE"]
    assert dialogue[0].text == "Siz meni tashlab ketmaysizmi?"
    assert dialogue[0].speaker_hint == "Kumush"
    assert dialogue[1].text == "Yoʻq." and dialogue[1].speaker_hint == "Otabek"
    whisper = next(b for b in blocks if b.text == "Rahmat sizga.")
    assert whisper.emotion == "whisper" and whisper.pause_after_ms == SCENE_BREAK_MS
    assert blocks[-1].pause_after_ms == CHAPTER_END_MS


def test_dash_inside_speech_is_not_a_remark():
    assert parse_dialogue_line("— Bu — mening uyim.") == [("DIALOGUE", "Bu — mening uyim.")]


def test_quoted_speech():
    assert parse_quoted_paragraph("Kumush dedi: «Ketaman.»") == [("NARRATION", "Kumush dedi:"), ("DIALOGUE", "Ketaman.")]
    assert parse_quoted_paragraph("U «Oʻtkan kunlar» romanini oʻqidi.") is None


def test_split_long_text_never_cuts_words():
    text = ("Bu juda uzun gap, unda koʻp vergul bor, va u davom etadi; " * 60).strip()
    parts = split_long_text(text, 2000)
    assert all(len(p) <= 2000 for p in parts)
    assert " ".join(parts).split() == text.split()
    giant = "soʻz " * 1000
    assert all(len(p) <= 300 for p in split_long_text(giant, 300))


def test_attribution_heuristics():
    chapters = segment_book(split_into_chapters(BOOK))
    registry = build_registry(chapters, None)
    result = attribute(chapters, registry, None)
    by_text = {chapters[0].blocks[pos].text: a for (_, pos), a in result.items() if _ == 1}
    assert by_text["Siz meni tashlab ketmaysizmi?"].character == "Kumush"
    assert by_text["Nega?"].character == "Kumush"  # navbatlashish
    assert by_text["Chunki sizni sevaman."].character == "Otabek"
    assert by_text["Nega?"].confidence < 0.7
    shares = dialogue_shares(chapters, result)
    assert abs(sum(shares.values()) - 1) < 0.01
    assert guess_gender("Kumushoy") == "FEMALE" and guess_gender("Otabek") == "MALE"


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, system, prompt, schema, temperature=0.3):
        self.calls.append(prompt)
        return self.responses.pop(0)


def test_attribution_with_llm():
    text = "1-bob\n\n— Salom!\n\nU javob bermadi.\n\n— Xayr."
    chapters = segment_book(split_into_chapters(text))
    llm = FakeLLM([
        {"characters": [{"canonical_name": "Anvar", "aliases": ["Anvarjon"], "gender": "MALE", "age_group": "ADULT"}]},
        {"attributions": [{"block_ref": "1:1", "speaker": "Anvarjon", "confidence": 0.9},
                          {"block_ref": "1:3", "speaker": "UNKNOWN", "confidence": 0.2}]},
    ])
    registry = build_registry(chapters, llm)
    result = attribute(chapters, registry, llm)
    assert result[(1, 1)].character == "Anvar" and result[(1, 1)].confidence == 0.9
    assert result[(1, 3)].character is None
