import httpx
import pytest

from app.models import BookStatus, ProjectStatus
from app.services.llm.client import GeminiLLM, LLMError
from app.services.llm.translation import SourceSegment, syllable_budget, translate_segments
from app.services.media.alignment import plan_alignment
from app.services.media.subtitles import Cue, to_srt, to_vtt
from app.state_machine import can_transition_book, can_transition_project


class FakeLLM:
    def __init__(self, fn):
        self.fn = fn
        self.calls = 0

    def generate_json(self, system, prompt, schema, temperature=0.3):
        self.calls += 1
        return self.fn(self.calls, prompt)


def test_syllable_budget():
    assert syllable_budget(2000) == (11, 13)
    assert syllable_budget(100) == (1, 2)


def test_translation_shortens_over_budget():
    segs = [SourceSegment("s1", "SPEAKER_00", "Hi there!", 0, 1000),
            SourceSegment("s2", "SPEAKER_01", "Where are you going?", 1000, 3000)]

    def fn(call, prompt):
        if call == 1:
            return {"segments": [
                {"segment_id": "s1", "speaker_id": "SPEAKER_00", "source_text": "Hi there!",
                 "target_uz_text": "Assalomu alaykum, qadrli doʻstim, qalaysiz", "target_duration_ms": 1000,
                 "emotion_tag": "happy"},
                {"segment_id": "s2", "speaker_id": "SPEAKER_01", "source_text": "Where are you going?",
                 "target_uz_text": "Qayerga ketyapsiz?", "target_duration_ms": 2000, "emotion_tag": "curious"},
            ], "glossary": [{"source": "John", "uz": "Jon"}]}
        assert "TOO LONG" in prompt and '"s1"' in prompt and '"s2"' not in prompt
        return {"segments": [{"segment_id": "s1", "speaker_id": "SPEAKER_00", "source_text": "Hi there!",
                              "target_uz_text": "Salom!", "target_duration_ms": 1000, "emotion_tag": "happy"}]}

    llm = FakeLLM(fn)
    res = translate_segments(llm, segs, "en")
    assert [s.target_uz_text for s in res.segments] == ["Salom!", "Qayerga ketyapsiz?"]
    assert res.segments[0].target_syllables == 2 and not res.segments[0].over_budget
    assert res.segments[1].emotion_tag == "curious"
    assert res.glossary == {"John": "Jon"}
    assert llm.calls == 2


def test_gemini_llm_json_and_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]})

    llm = GeminiLLM(api_key="x", transport=httpx.MockTransport(handler), max_retries=2)
    import app.services.llm.client as client_mod

    orig = client_mod.time.sleep
    client_mod.time.sleep = lambda _: None
    try:
        assert llm.generate_json("s", "p", {"type": "OBJECT"}) == {"ok": True}
        bad = GeminiLLM(api_key="x", transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad")))
        with pytest.raises(LLMError):
            bad.generate_json("s", "p", {})
    finally:
        client_mod.time.sleep = orig


def test_alignment_plans():
    # TTS biroz uzun → tezlashtirish
    p = plan_alignment(2.2, 0.0, 2.0, 5.0)
    assert p.tempo_ratio == 1.1 and p.overflow_s == 0 and not p.needs_retranslation
    # Juda uzun → 1.25x, keyingi segmentgacha boʻshliqdan qarz
    p = plan_alignment(3.0, 0.0, 2.0, 2.5)
    assert p.tempo_ratio == 1.25 and p.output_s == 2.4 and p.overflow_s == 0
    # Sigʻmaydi → kesiladi va qayta tarjima tavsiya etiladi
    p = plan_alignment(4.0, 0.0, 2.0, 2.2)
    assert p.overflow_s > 0 and p.needs_retranslation
    # Qisqa → sekinlashtirish ≥ 0.85
    p = plan_alignment(1.0, 0.0, 2.0, None)
    assert p.tempo_ratio == 0.85


def test_subtitles():
    cues = [Cue(1.5, 3.25, "Salom, dunyo!"), Cue(3661.0, 3662.5, "Ikkinchi " * 12)]
    srt = to_srt(cues)
    assert srt.startswith("1\n00:00:01,500 --> 00:00:03,250\nSalom, dunyo!\n")
    assert "01:01:01,000 --> 01:01:02,500" in srt
    assert all(len(line) <= 60 for line in srt.splitlines())
    assert to_vtt(cues).startswith("WEBVTT\n\n00:00:01.500 --> 00:00:03.250")


def test_state_machines():
    assert can_transition_project(ProjectStatus.UPLOADED, ProjectStatus.STEM_SEPARATION)
    assert not can_transition_project(ProjectStatus.UPLOADED, ProjectStatus.TRANSLATED)
    assert can_transition_project(ProjectStatus.READY_FOR_EXPORT, ProjectStatus.TRANSLATED)  # qayta render
    assert can_transition_project(ProjectStatus.FAILED, ProjectStatus.TTS_DISPATCHED)
    assert can_transition_book(BookStatus.LEXICON_APPLIED, BookStatus.TTS_DISPATCHED)
    assert not can_transition_book(BookStatus.PARSED, BookStatus.STITCHED)
