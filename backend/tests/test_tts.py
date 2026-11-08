import base64
import json
from decimal import Decimal

import httpx
import pytest

from app.models import AgeGroup, Gender, TTSMode, TTSProvider, TTSTier
from app.services.tts.base import (
    ProviderTimeout,
    QuotaExceeded,
    RateLimited,
    TTSRequest,
    TTSResult,
)
from app.services.tts.cost import api_cost, customer_charge, estimate
from app.services.tts.elevenlabs import ElevenLabsClient
from app.services.tts.gemini import GeminiTTSClient
from app.services.tts.router import (
    CircuitBreaker,
    SpeakerSpec,
    SpeakerStats,
    TTSFailed,
    TTSRouter,
    VoiceAssignment,
    VoiceOption,
    assign_tiers,
    assign_voices,
)


# ------------------------------------------------------------------ provayder klientlari
def test_elevenlabs_request_and_errors():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers["xi-api-key"]
        return httpx.Response(200, content=b"ID3mp3data")

    c = ElevenLabsClient(api_key="k", transport=httpx.MockTransport(handler))
    r = c.synthesize(TTSRequest("Salom… dunyo", "voice1", emotion="angry"))
    assert r.audio == b"ID3mp3data" and r.extension == "mp3" and r.characters == 12
    assert "/v1/text-to-speech/voice1" in seen["url"] and "output_format=mp3_44100_128" in seen["url"]
    assert seen["body"]["model_id"] == "eleven_multilingual_v2"
    assert seen["body"]["voice_settings"]["style"] == 0.75
    assert "<break" in seen["body"]["text"]

    quota = ElevenLabsClient(api_key="k", transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"detail": {"status": "quota_exceeded", "message": "no credits"}})))
    with pytest.raises(QuotaExceeded):
        quota.synthesize(TTSRequest("a", "v"))
    busy = ElevenLabsClient(api_key="k", transport=httpx.MockTransport(
        lambda r: httpx.Response(429, json={"detail": {"status": "too_many_concurrent_requests"}})))
    with pytest.raises(RateLimited):
        busy.synthesize(TTSRequest("a", "v"))

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderTimeout):
        ElevenLabsClient(api_key="k", transport=httpx.MockTransport(timeout)).synthesize(TTSRequest("a", "v"))


def test_gemini_request_pcm_to_wav():
    pcm = b"\x00\x01" * 24000  # 1 soniya, 24 kHz
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]})

    c = GeminiTTSClient(api_key="g", transport=httpx.MockTransport(handler))
    r = c.synthesize(TTSRequest("Salom", "Kore", emotion="happy"))
    assert r.extension == "wav" and r.audio[:4] == b"RIFF"
    assert r.duration_seconds == pytest.approx(1.0)
    cfg = seen["body"]["generationConfig"]
    assert cfg["responseModalities"] == ["AUDIO"]
    assert cfg["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    prompt = seen["body"]["contents"][0]["parts"][0]["text"]
    assert prompt.startswith("Say cheerfully in Uzbek, as an engaging audiobook narrator")
    assert prompt.endswith(":\nSalom")
    acted = GeminiTTSClient.build_prompt(TTSRequest("Qoching!", "Kore", emotion="fearful", role="character",
                                                    style="panicked, breathless, shouting"))
    assert "acting this line as the character" in acted and "(panicked, breathless, shouting)" in acted

    def quota_error(quota_id, delay="12s"):
        msg = ("You exceeded your current quota, please check your plan and billing details. "
               "For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits.")
        return {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": msg,
                          "details": [
                              {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                               "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_requests",
                                               "quotaId": quota_id}]},
                              {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}}

    daily = GeminiTTSClient(api_key="g", transport=httpx.MockTransport(
        lambda r: httpx.Response(429, json=quota_error("GenerateRequestsPerDayPerProjectPerModel"))))
    with pytest.raises(QuotaExceeded):
        daily.synthesize(TTSRequest("a", "Kore"))
    minute = GeminiTTSClient(api_key="g", transport=httpx.MockTransport(
        lambda r: httpx.Response(429, json=quota_error("GenerateRequestsPerMinutePerProjectPerModel"))))
    with pytest.raises(RateLimited) as exc:
        minute.synthesize(TTSRequest("a", "Kore"))
    assert exc.value.retry_after == 12.0

    # Asosiy TTS modeli band (503) — zaxira modelga oʻtadi
    seen_models = []

    def busy_then_ok(request):
        seen_models.append(request.url.path.split("/")[-1])
        if len(seen_models) == 1:
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE", "message": "high demand"}})
        return handler(request)

    fb = GeminiTTSClient(api_key="g", transport=httpx.MockTransport(busy_then_ok),
                         model=None)
    fb.models = ["primary-tts", "fallback-tts"]
    assert fb.synthesize(TTSRequest("Salom", "Kore")).extension == "wav"
    assert seen_models == ["primary-tts:generateContent", "fallback-tts:generateContent"]


# ------------------------------------------------------------------ xarajat
def test_cost_formula():
    assert api_cost(TTSProvider.ELEVENLABS, 1000) == Decimal("0.3000")
    assert api_cost(TTSProvider.GEMINI, 1000) == Decimal("0.0200")
    assert customer_charge(Decimal("0.3")) == Decimal("0.4500")
    api, charge = estimate({TTSProvider.ELEVENLABS: 2000, TTSProvider.GEMINI: 5000})
    assert api == Decimal("0.7000") and charge == Decimal("1.0500")


# ------------------------------------------------------------------ darajalar va ovozlar
def test_assign_tiers_balanced():
    stats = [
        SpeakerStats("hero", 0.5),
        SpeakerStats("villain", 0.08, emotional_ratio=0.6),
        SpeakerStats("extra", 0.04, emotional_ratio=0.9),
        SpeakerStats("narrator", 0.3),
        SpeakerStats("cloned", 0.01, is_cloned=True),
    ]
    tiers = assign_tiers(stats, TTSMode.BALANCED)
    assert tiers == {"hero": TTSTier.TIER_1, "villain": TTSTier.TIER_1, "extra": TTSTier.TIER_2,
                     "narrator": TTSTier.TIER_1, "cloned": TTSTier.TIER_1}
    assert set(assign_tiers(stats, TTSMode.BUDGET).values()) == {TTSTier.TIER_2, TTSTier.TIER_1}
    assert assign_tiers(stats, TTSMode.BUDGET)["hero"] is TTSTier.TIER_2
    assert set(assign_tiers(stats, TTSMode.PREMIUM).values()) == {TTSTier.TIER_1}
    # Hech kim chegaradan oʻtmasa — eng koʻp gapiruvchi TIER_1
    few = assign_tiers([SpeakerStats("a", 0.04), SpeakerStats("b", 0.03)], TTSMode.BALANCED)
    assert few == {"a": TTSTier.TIER_1, "b": TTSTier.TIER_2}


CATALOG = [
    VoiceOption("e-m1", TTSProvider.ELEVENLABS, "adam", Gender.MALE, AgeGroup.ADULT),
    VoiceOption("e-m2", TTSProvider.ELEVENLABS, "josh", Gender.MALE, AgeGroup.YOUNG_ADULT),
    VoiceOption("e-f1", TTSProvider.ELEVENLABS, "rachel", Gender.FEMALE, AgeGroup.ADULT),
    VoiceOption("g-m1", TTSProvider.GEMINI, "Charon", Gender.MALE, AgeGroup.ADULT, is_narrator=True),
    VoiceOption("g-m2", TTSProvider.GEMINI, "Puck", Gender.MALE, AgeGroup.YOUNG_ADULT),
    VoiceOption("g-f1", TTSProvider.GEMINI, "Kore", Gender.FEMALE, AgeGroup.ADULT),
    VoiceOption("g-f2", TTSProvider.GEMINI, "Leda", Gender.FEMALE, AgeGroup.YOUNG_ADULT),
]


def test_assign_voices_gender_and_uniqueness():
    specs = [
        SpeakerSpec("s1", TTSTier.TIER_1, Gender.MALE, AgeGroup.ADULT),
        SpeakerSpec("s2", TTSTier.TIER_1, Gender.MALE, AgeGroup.YOUNG_ADULT),
        SpeakerSpec("s3", TTSTier.TIER_2, Gender.FEMALE, AgeGroup.YOUNG_ADULT),
        SpeakerSpec("s4", TTSTier.TIER_2, Gender.FEMALE, AgeGroup.ADULT),
    ]
    a = assign_voices(specs, CATALOG)
    assert a["s1"].primary.voice_id == "adam" and a["s2"].primary.voice_id == "josh"
    assert a["s3"].primary.voice_id == "Leda" and a["s4"].primary.voice_id == "Kore"
    assert a["s1"].fallback.provider is TTSProvider.GEMINI and a["s1"].fallback.gender is Gender.MALE
    assert a["s3"].fallback.provider is TTSProvider.ELEVENLABS and a["s3"].fallback.gender is Gender.FEMALE
    # Foydalanuvchi tanlovi ustun
    pref = assign_voices([SpeakerSpec("x", TTSTier.TIER_2, Gender.MALE, preferred_profile_id="e-f1")], CATALOG)
    assert pref["x"].primary.voice_id == "rachel"


# ------------------------------------------------------------------ marshrutlash
class FakeClient:
    def __init__(self, name, script):
        self.name = name
        self.script = list(script)
        self.calls = 0

    def synthesize(self, request):
        self.calls += 1
        item = self.script.pop(0) if self.script else "ok"
        if isinstance(item, Exception):
            raise item
        return TTSResult(audio=b"x", extension="wav", characters=len(request.text), duration_seconds=1.0)


def _assignment():
    return VoiceAssignment(CATALOG[0], CATALOG[3])


def test_router_retries_then_succeeds():
    el = FakeClient("elevenlabs", [ProviderTimeout("t"), RateLimited("r"), "ok"])
    sleeps = []
    router = TTSRouter({TTSProvider.ELEVENLABS: el, TTSProvider.GEMINI: FakeClient("gemini", [])},
                       max_retries=3, sleep=sleeps.append)
    r = router.synthesize(TTSRequest("Salom", ""), _assignment(), "spk")
    assert r.provider is TTSProvider.ELEVENLABS and r.retry_count == 2 and r.fallback_from is None
    assert sleeps == [1.0, 2.0]
    assert r.api_cost_usd == api_cost(TTSProvider.ELEVENLABS, 5, 1.0)


def test_router_quota_fallback_is_sticky():
    el = FakeClient("elevenlabs", [QuotaExceeded("q")])
    gm = FakeClient("gemini", [])
    router = TTSRouter({TTSProvider.ELEVENLABS: el, TTSProvider.GEMINI: gm}, sleep=lambda _: None)
    r1 = router.synthesize(TTSRequest("Bir", ""), _assignment(), "spk")
    assert r1.provider is TTSProvider.GEMINI and r1.fallback_from is TTSProvider.ELEVENLABS
    r2 = router.synthesize(TTSRequest("Ikki", ""), _assignment(), "spk")
    assert r2.provider is TTSProvider.GEMINI and el.calls == 1  # ElevenLabs boshqa chaqirilmaydi


def test_router_waits_on_rate_limit_without_opening_breaker():
    gm = FakeClient("gemini", [RateLimited("rpm", retry_after=30.0), RateLimited("rpm", retry_after=500.0), "ok"])
    sleeps = []
    router = TTSRouter({TTSProvider.GEMINI: gm}, sleep=sleeps.append, max_wait_s=90)
    r = router.synthesize(TTSRequest("Salom", ""), VoiceAssignment(CATALOG[3], None), "spk")
    assert r.provider is TTSProvider.GEMINI and sleeps == [30.0, 90]
    assert router.breakers[TTSProvider.GEMINI].allow()


def test_router_all_failed():
    router = TTSRouter({TTSProvider.ELEVENLABS: FakeClient("e", [QuotaExceeded("q")]),
                        TTSProvider.GEMINI: FakeClient("g", [ProviderTimeout("t")] * 10)},
                       max_retries=1, sleep=lambda _: None)
    with pytest.raises(TTSFailed) as exc:
        router.synthesize(TTSRequest("x", ""), _assignment(), "k")
    assert len(exc.value.attempts) == 2


def test_circuit_breaker():
    now = [0.0]
    cb = CircuitBreaker(threshold=2, cooldown_s=10, clock=lambda: now[0])
    cb.failure()
    assert cb.allow()
    cb.failure()
    assert not cb.allow()
    now[0] = 11
    assert cb.allow()
    cb.failure(permanent=True)
    assert not cb.allow()


def test_gemini_wav_payload_is_not_double_wrapped():
    """gemini-3.8-flash-tts mimeType ni audio/L16 deb koʻrsatib, RIFF sarlavhali WAV qaytaradi.
    Sarlavha ovozga aylanmasligi kerak (aks holda har gap boshida "chirsillash" eshitiladi)."""
    from app.services.tts.gemini import decode_audio_payload, pcm_to_wav

    pcm = b"\x10\x00\xf0\xff" * 12000  # 1 soniya, 24 kHz
    inner = pcm_to_wav(pcm, 24000)
    out_pcm, rate, ch = decode_audio_payload(inner, 24000)
    assert out_pcm == pcm and rate == 24000 and ch == 1
    raw_pcm, _, _ = decode_audio_payload(pcm, 24000)
    assert raw_pcm == pcm

    def handler(request):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(inner).decode()}}]}}]})

    r = GeminiTTSClient(api_key="g", transport=httpx.MockTransport(handler)).synthesize(TTSRequest("Salom", "Kore"))
    assert r.audio[44:] == pcm  # bitta sarlavha, keyin toza ovoz
    assert r.duration_seconds == pytest.approx(1.0)


def test_repair_double_wrapped_wav():
    from app.services.tts.gemini import pcm_to_wav
    from app.tools.repair_tts_wav import repair_bytes

    pcm = b"\x01\x02" * 2400
    broken = pcm_to_wav(pcm_to_wav(pcm, 24000), 24000)
    assert repair_bytes(broken)[44:] == pcm
    assert repair_bytes(pcm_to_wav(pcm, 24000)) is None  # sogʻlom fayl oʻzgarmaydi
