"""Rejissyor (ijro koʻrsatmalari, nomsiz spikerlar, sahnalar) va muhit tovushlari mikslash."""
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.llm.director import BlockIn, Scene, direct_chapter, normalize_scenes
from app.services.media import ffmpeg, soundscape


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate_json(self, system, prompt, schema, temperature=0.3):
        self.prompts.append(prompt)
        return self.responses.pop(0)


BLOCKS = [
    BlockIn(0, "HEADING", "Kirish"),
    BlockIn(1, "NARRATION", "Maktab hovlisida bolalar yugurib yurardi."),
    BlockIn(2, "NARRATION", "Toʻsatdan tayoqcha yuzimga urildi."),
    BlockIn(3, "DIALOGUE", "Hozir nechanchi yil?"),
    BlockIn(4, "DIALOGUE", "Bilmayman.", speaker="Jeyms"),
    BlockIn(5, "NARRATION", "Odatlar — bu tizim."),
]


def test_direct_chapter_parses_and_filters():
    llm = FakeLLM([{
        "blocks": [
            {"seq": 1, "emotion": "neutral", "delivery": "warm, vivid storytelling"},
            {"seq": 2, "emotion": "fearful", "delivery": "sudden, tense, faster " + "very " * 20},
            {"seq": 3, "emotion": "curious", "delivery": "calm, professional", "speaker_role": "Hamshira",
             "speaker_gender": "FEMALE", "speaker_age": "ADULT"},
            {"seq": 4, "emotion": "hesitant", "delivery": "confused, dazed", "speaker_role": "Bola"},
            {"seq": 99, "emotion": "happy", "delivery": "x"},
            {"seq": 5, "emotion": "bogus", "delivery": "reflective"},
        ],
        "scenes": [
            {"start_seq": 1, "end_seq": 3, "label": "Maktab hovlisi", "intensity": "medium",
             "ambience_prompt": "school yard at recess, distant kids playing, indistinct chatter"},
            {"start_seq": 2, "end_seq": 4, "label": "Ustma-ust", "intensity": "low", "ambience_prompt": "rain"},
            {"start_seq": 5, "end_seq": 5, "label": "Qisqa", "intensity": "low", "ambience_prompt": "wind"},
        ],
    }])
    d = direct_chapter(llm, BLOCKS, "Kirish", retry_delay_s=0)
    assert d.blocks[2].emotion == "fearful" and len(d.blocks[2].delivery.split()) <= 14
    assert d.blocks[3].speaker_role == "Hamshira" and d.blocks[3].speaker_gender == "FEMALE"
    assert d.blocks[4].speaker_role == ""  # nomi maʼlum spikerga rol berilmaydi
    assert 99 not in d.blocks and d.blocks[5].emotion == "neutral"
    assert [(s.start_seq, s.end_seq, s.label) for s in d.scenes] == [(1, 3, "Maktab hovlisi")]
    assert '"speaker": "Jeyms"' in llm.prompts[0]


def test_normalize_scenes_clamps_range():
    out = normalize_scenes([Scene(-5, 2, "A", "crowd", "loud")], [0, 1, 2, 3])
    assert out[0].start_seq == 0 and out[0].intensity == "low"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yoʻq")
def test_ambience_mix_ducks_under_voice(tmp_path: Path):
    voice = tmp_path / "voice.wav"
    # 0–2 s nutq (ton), 2–4 s pauza, 4–6 s nutq
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-f", "lavfi", "-i",
                "anullsrc=r=44100:cl=mono:d=2", "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
                "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1,aformat=sample_rates=44100:channel_layouts=mono",
                "-c:a", "pcm_s16le", str(voice)])
    sfx = tmp_path / "rain.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "anoisesrc=color=pink:duration=3:amplitude=0.5", "-ar", "44100",
                "-ac", "1", "-c:a", "pcm_s16le", str(sfx)])
    bed = soundscape.build_ambience_track([soundscape.PlacedScene(1000, 6000, sfx, "medium")], 6000,
                                          tmp_path / "bed.wav", tmp_path / "beds")
    assert ffmpeg.duration_seconds(bed) == pytest.approx(6.0, abs=0.05)
    out = soundscape.mix_voice_with_ambience(voice, bed, tmp_path / "mix.wav")
    with wave.open(str(out)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        sr = w.getframerate()
    assert len(x) / sr == pytest.approx(6.0, abs=0.05)

    def rms(a, b):
        seg = x[int(a * sr):int(b * sr)]
        return float(np.sqrt((seg ** 2).mean()))

    assert rms(0.0, 0.8) > 0.01  # sahna boshlanmagan: faqat nutq
    assert rms(2.6, 3.6) > 0.002  # pauzada fon eshitiladi
    with wave.open(str(bed)) as w:
        b = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    assert float(np.abs(b[: int(0.9 * sr)]).max()) == 0.0  # sahnadan oldin jimlik


def test_sfx_cache_key_is_stable():
    assert soundscape.cache_key(" Rain on a tin roof ") == soundscape.cache_key("rain on a tin roof")


def test_llm_schemas_are_valid_for_gemini():
    """Gemini responseSchema: enum qiymatlari boʻsh boʻlmasligi, required faqat mavjud maydonlar."""
    from app.services.llm import attribution, director, translation
    from app.workers import book_tasks

    def walk(node, path="schema"):
        if isinstance(node, dict):
            for v in node.get("enum", []) or []:
                assert v != "", f"{path}: enum da boʻsh qiymat"
            props = node.get("properties")
            if props is not None:
                for r in node.get("required", []):
                    assert r in props, f"{path}: required '{r}' properties da yoʻq"
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    for schema in (director._SCHEMA, translation._SCHEMA, attribution._REGISTRY_SCHEMA,
                   attribution._ATTR_SCHEMA, book_tasks._LEXICON_SCHEMA):
        walk(schema)


def test_roles_are_canonical_and_author_is_narrator():
    from app.services.llm.director import canonical_role

    assert canonical_role("O‘quvchi") == canonical_role("o'quvchi") == canonical_role("OʻQUVCHI") == "Oʻquvchi"
    assert canonical_role("Muallif") is None and canonical_role(" men ") is None
    assert canonical_role("") is None
    assert canonical_role("Laslo Polgar") == "Laslo Polgar" and canonical_role("neyrobiolog olim") == "Neyrobiolog olim"


def test_director_retries_window_once():
    from app.services.llm.client import LLMError

    class Flaky:
        calls = 0

        def generate_json(self, *a, **k):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise LLMError("503")
            return {"blocks": [{"seq": 1, "emotion": "happy", "delivery": "bright"}], "scenes": []}

    d = direct_chapter(Flaky(), BLOCKS[:3], retry_delay_s=0)
    assert Flaky.calls == 2 and d.blocks[1].emotion == "happy"
