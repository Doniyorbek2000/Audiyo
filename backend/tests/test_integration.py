"""End-to-end: API → Celery (eager) → Postgres/Redis → FFmpeg.

Tashqi xizmatlar (S3, WhisperX, LLM, TTS) soxtalashtirilgan; qolgan hammasi — haqiqiy kod.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest
import redis

from app.config import get_settings


def _services_up() -> bool:
    try:
        dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
        psycopg.connect(dsn, connect_timeout=2).close()
        redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2).ping()
        return shutil.which("ffmpeg") is not None
    except Exception:  # noqa: BLE001
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _services_up(), reason="Postgres/Redis/ffmpeg yoʻq")]


# =============================================================== soxta xizmatlar


class FakeStorage:
    def __init__(self, root: Path):
        self.root = root

    def path(self, key: str) -> Path:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def upload_file(self, path, key, content_type=None):
        shutil.copy(path, self.path(key))
        return key

    def upload_fileobj(self, fileobj, key, content_type=None):
        self.path(key).write_bytes(fileobj.read())
        return key

    def upload_bytes(self, data, key, content_type=None):
        self.path(key).write_bytes(data)
        return key

    def download_file(self, key, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.root / key, path)
        return path

    def presigned_url(self, key, download_name=None):
        return f"https://s3.test/{key}" if key else None


def fake_transcribe(vocals_wav, language=None):
    from app.services.media.transcription import SpeakerInfo, Transcript, TranscriptSegment, Word

    def seg(speaker, start, end, text):
        words = text.split()
        step = (end - start) / len(words)
        return TranscriptSegment(speaker, start, end, text,
                                 [Word(w, start + i * step, start + (i + 1) * step, speaker) for i, w in enumerate(words)])

    segments = [
        seg("SPEAKER_00", 0.5, 2.0, "Hello, my friend!"),
        seg("SPEAKER_01", 2.3, 3.8, "Where are you going?"),
        seg("SPEAKER_00", 4.0, 5.5, "I am going home."),
    ]
    return Transcript("en", segments, {
        "SPEAKER_00": SpeakerInfo("SPEAKER_00", 3.0, 2.0, "MALE", "ADULT", 120.0),
        "SPEAKER_01": SpeakerInfo("SPEAKER_01", 1.5, 2.7, "FEMALE", "ADULT", 210.0),
    })


UZ = {"Hello, my friend!": "Salom, doʻstim!", "Where are you going?": "Qayerga ketyapsiz?",
      "I am going home.": "Uyga ketyapman."}


class FakeLLM:
    def generate_json(self, system, prompt, schema, temperature=0.3):
        items = json.loads(prompt[prompt.index("Segments:\n") + len("Segments:\n"):])
        return {"segments": [
            {"segment_id": it["segment_id"], "speaker_id": it["speaker_id"], "source_text": it["source_text"],
             "target_uz_text": UZ.get(it["source_text"], "Tarjima"), "target_duration_ms": it["target_duration_ms"],
             "emotion_tag": "happy" if "!" in it["source_text"] else "neutral"} for it in items]}


class FakeTTS:
    """Matn uzunligiga mos sinus toni (≈15 belgi/soniya) qaytaradi."""

    def __init__(self, name):
        self.name = name
        self.requests = []

    def synthesize(self, request):
        from app.services.tts.base import TTSResult

        self.requests.append(request)
        seconds = max(0.4, len(request.text) / 15)
        proc = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds:.2f}",
             "-ar", "24000", "-ac", "1", "-f", "wav", "-"], capture_output=True, check=True)
        return TTSResult(audio=proc.stdout, extension="wav", characters=len(request.text), duration_seconds=seconds)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from app import migrate
    from app.workers.celery_app import celery_app

    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    migrate.migrate(dsn)

    mp = pytest.MonkeyPatch()
    store = FakeStorage(tmp_path_factory.mktemp("s3"))
    import app.storage as storage_mod

    for name in ("upload_file", "upload_fileobj", "upload_bytes", "download_file", "presigned_url"):
        mp.setattr(storage_mod, name, getattr(store, name))
    mp.setattr(storage_mod, "ensure_bucket", lambda: None)
    mp.setattr("app.services.media.transcription.transcribe", fake_transcribe)

    import app.workers.book_tasks as bt
    import app.workers.video_tasks as vt
    from app.models import TTSProvider
    from app.services.llm.client import LLMNotConfigured
    from app.services.tts.router import TTSRouter

    clients = {TTSProvider.ELEVENLABS: FakeTTS("elevenlabs"), TTSProvider.GEMINI: FakeTTS("gemini")}
    mp.setattr(vt, "get_llm", lambda: FakeLLM())
    mp.setattr(vt, "build_router", lambda: TTSRouter(clients, sleep=lambda _: None))
    mp.setattr(bt, "build_router", lambda: TTSRouter(clients, sleep=lambda _: None))

    def no_llm():
        raise LLMNotConfigured("test")

    mp.setattr(bt, "get_llm", no_llm)
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield {"store": store, "clients": clients}
    celery_app.conf.task_always_eager = False
    mp.undo()


@pytest.fixture(scope="module")
async def client(env):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=600) as c:
        r = await c.post("/auth/register", json={"email": "test@audiyo.uz", "password": "parol12345"})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c


# =============================================================== auth va billing


async def test_auth_and_balance(client):
    me = (await client.get("/auth/me")).json()
    assert me["email"] == "test@audiyo.uz" and float(me["credit_balance_usd"]) == 2.0
    r = await client.post("/auth/register", json={"email": "TEST@audiyo.uz", "password": "parol12345"})
    assert r.status_code == 409
    r = await client.post("/auth/login", json={"email": "test@audiyo.uz", "password": "notoʻgʻri-parol"})
    assert r.status_code == 401
    r = await client.post("/billing/topup/dev", json={"amount_usd": "10"})
    assert r.status_code == 200 and float(r.json()["balance_after_usd"]) == 12.0
    noauth = await client.get("/projects", headers={"Authorization": ""})
    assert noauth.status_code == 401


async def test_payment_webhook_idempotent(client):
    me = (await client.get("/auth/me")).json()
    body = json.dumps({"payment_id": "pay-1", "user_id": me["id"], "amount_usd": "5", "status": "paid"}).encode()
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    bad = await client.post("/billing/webhook", content=body, headers={"X-Signature": "00"})
    assert bad.status_code == 401
    for _ in range(2):
        r = await client.post("/billing/webhook", content=body, headers={"X-Signature": sig})
        assert r.status_code == 204
    me2 = (await client.get("/auth/me")).json()
    assert float(me2["credit_balance_usd"]) == float(me["credit_balance_usd"]) + 5


# =============================================================== video konveyeri


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "demo.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=6",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-ac", "2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


async def test_video_pipeline_end_to_end(client, env, sample_video):
    with sample_video.open("rb") as f:
        r = await client.post("/projects/upload", files={"file": ("demo.mp4", f, "video/mp4")},
                              data={"title": "Demo", "source_language": "auto", "tts_mode": "BALANCED"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    project = (await client.get(f"/projects/{pid}")).json()
    assert project["status"] == "READY_FOR_EXPORT", project["error_message"]
    assert project["source_language"] == "en" and float(project["progress"]) == 100

    tl = (await client.get(f"/projects/{pid}/timeline")).json()
    assert len(tl["segments"]) == 3 and len(tl["speakers"]) == 2
    assert [s["translated_text_uz"] for s in tl["segments"]] == list(UZ.values())
    assert all(s["status"] == "ALIGNED" for s in tl["segments"])
    assert all(0.85 <= float(s["tempo_ratio"]) <= 1.25 for s in tl["segments"])
    assert tl["stems"]["vocals"].startswith("https://s3.test/") and tl["pending_changes"] == 0
    assert tl["poster_url"].endswith("poster.jpg")
    assert {"original", "vocals", "bgm", "dubbed"} <= set(tl["peaks"])
    tiers = {sp["speaker_tag"]: sp["tts_tier"] for sp in tl["speakers"]}
    assert tiers == {"SPEAKER_00": "TIER_1", "SPEAKER_01": "TIER_1"}
    female = next(sp for sp in tl["speakers"] if sp["speaker_tag"] == "SPEAKER_01")
    assert female["voice"]["gender"] == "FEMALE"

    out = env["store"].root / f"projects/{pid}/output/dubbed.mp4"
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                                         str(out)], capture_output=True).stdout)["streams"]
    assert [s["codec_type"] for s in streams].count("audio") == 2
    srt = (env["store"].root / f"projects/{pid}/output/subtitles.uz.srt").read_text()
    assert "Qayerga ketyapsiz?" in srt

    # ---- qoʻlda tahrir + qayta render
    seg = tl["segments"][1]
    r = await client.patch(f"/projects/{pid}/segments/{seg['id']}", json={"translated_text_uz": "Qayoqqa?"})
    assert r.status_code == 200 and r.json()["status"] == "TRANSLATED" and r.json()["manual_override_flags"]
    assert r.json()["target_syllables"] == 3
    bad = await client.patch(f"/projects/{pid}/segments/{seg['id']}", json={"start_time": 5, "end_time": 4})
    assert bad.status_code == 422
    assert (await client.get(f"/projects/{pid}/timeline")).json()["pending_changes"] == 1

    # spiker ovozini almashtirish
    voices = (await client.get("/voices")).json()
    puck = next(v for v in voices if v["provider_voice_id"] == "Puck")
    sp0 = next(sp for sp in tl["speakers"] if sp["speaker_tag"] == "SPEAKER_00")
    r = await client.patch(f"/projects/{pid}/speakers/{sp0['id']}", json={"voice_profile_id": puck["id"],
                                                                         "display_name": "Ali"})
    assert r.status_code == 200 and r.json()["voice"]["provider_voice_id"] == "Puck"
    assert (await client.get(f"/projects/{pid}/timeline")).json()["pending_changes"] == 3

    gemini_before = len(env["clients"][next(iter(env["clients"]))].requests)
    r = await client.post(f"/projects/{pid}/rerender")
    assert r.status_code == 202
    tl2 = (await client.get(f"/projects/{pid}/timeline")).json()
    assert tl2["project"]["status"] == "READY_FOR_EXPORT" and tl2["pending_changes"] == 0
    assert tl2["segments"][1]["translated_text_uz"] == "Qayoqqa?"
    sp0b = next(sp for sp in tl2["speakers"] if sp["speaker_tag"] == "SPEAKER_00")
    assert sp0b["tts_tier"] == "TIER_2" and sp0b["display_name"] == "Ali"
    assert len(env["clients"][next(iter(env["clients"]))].requests) >= gemini_before

    exp = (await client.get(f"/projects/{pid}/export")).json()
    assert exp["video_mp4"].endswith("dubbed.mp4") and exp["subtitles_vtt"]

    costs = (await client.get(f"/projects/{pid}/costs")).json()
    assert costs["api_cost_usd"] > 0 and {p["provider"] for p in costs["providers"]} == {"elevenlabs", "gemini"}

    txs = (await client.get("/billing/transactions")).json()
    kinds = [t["kind"] for t in txs]
    assert kinds.count("HOLD") == 2 and "BONUS" in kinds and "TOPUP" in kinds
    usage = (await client.get("/billing/usage")).json()
    assert sum(r["jobs"] for r in usage["rows"]) == 6


async def test_video_insufficient_credits(client, env, sample_video, monkeypatch):
    # Balansni nolga tushirish
    from decimal import Decimal

    from sqlalchemy import update

    from app.db import sync_session
    from app.models import User

    with sync_session() as s:
        s.execute(update(User).values(credit_balance_usd=Decimal("0")))
    with sample_video.open("rb") as f:
        r = await client.post("/projects/upload", files={"file": ("demo.mp4", f, "video/mp4")})
    p = (await client.get(f"/projects/{r.json()['id']}")).json()
    assert p["status"] == "FAILED" and "Kredit yetarli emas" in p["error_message"]
    r = await client.post(f"/projects/{p['id']}/retry")
    assert r.status_code == 202
    await client.post("/billing/topup/dev", json={"amount_usd": "20"})
    await client.post(f"/projects/{p['id']}/retry")
    assert (await client.get(f"/projects/{p['id']}")).json()["status"] == "READY_FOR_EXPORT"


async def test_upload_validation(client):
    r = await client.post("/projects/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
    r = await client.post("/books/upload", files={"file": ("x.rtf", b"{}", "text/rtf")})
    assert r.status_code == 415
    assert (await client.get(f"/projects/{uuid.uuid4()}")).status_code == 404


# =============================================================== kitob konveyeri

BOOK = """Sehrli kun

1-bob. Uchrashuv

Kech kirdi. Otabek Washington shahridan Thompson bilan qaytdi. U 1991-yilda tugʻilgan.

— Siz meni tashlab ketmaysizmi? — soʻradi Kumush.
— Yoʻq, — dedi Otabek. — Hech qachon.
— Nega?
— Chunki sizni sevaman.
— Rostdanmi?

* * *

Ertasi kuni Google'da yangilik chiqdi…

2-bob. Xayrlashuv

— Xayr, — dedi Kumush.
Otabek jim qoldi.
"""


async def test_book_pipeline_end_to_end(client, env):
    await client.post("/billing/topup/dev", json={"amount_usd": "50"})
    r = await client.post("/books/upload", files={"file": ("kitob.txt", BOOK.encode(), "text/plain")},
                          data={"title": "Sehrli kun", "author": "Muallif", "tts_mode": "BALANCED"})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    book = (await client.get(f"/books/{bid}")).json()
    assert book["status"] == "LEXICON_APPLIED", book["error_message"]
    assert float(book["estimated_cost_usd"]) > 0

    chapters = (await client.get(f"/books/{bid}/chapters")).json()
    # Sarlavhasiz boshlangʻich matn (kitob nomi) alohida "Kirish" boʻlimi boʻladi
    assert [c["title"] for c in chapters] == [None, "1-bob. Uchrashuv", "2-bob. Xayrlashuv"]

    chars = (await client.get(f"/books/{bid}/characters")).json()
    names = {c["canonical_name"]: c for c in chars}
    assert set(names) == {"Kumush", "Otabek"}
    assert names["Otabek"]["gender"] == "MALE" and names["Otabek"]["voice"] is not None
    assert book["narrator_voice_profile_id"] not in {c["voice_profile_id"] for c in chars}

    blocks = (await client.get(f"/books/{bid}/blocks", params={"chapter": 2})).json()["items"]
    born = next(b for b in blocks if "tugʻilgan" in b["source_text"])
    assert "bir ming toʻqqiz yuz toʻqson birinchi yilda" in born["tts_text"]
    assert "Vashington" in born["tts_text"]
    news = next(b for b in blocks if "yangilik" in b["source_text"])
    assert "Guglda" in news["tts_text"]
    review = (await client.get(f"/books/{bid}/blocks", params={"needs_review": True})).json()
    assert review["total"] >= 1

    lex = (await client.get(f"/books/{bid}/lexicon")).json()
    assert any(e["term"] == "Thompson" and e["phonetic_uz"] == "Tompson" and e["source"] == "AUTO_SUGGESTED"
               for e in lex)
    assert "Tompson" in born["tts_text"]
    r = await client.post(f"/books/{bid}/lexicon", json={"term": "Washington", "phonetic_uz": "Uoshington"})
    assert r.status_code == 201 and r.json()["source"] == "USER"
    born = next(b for b in (await client.get(f"/books/{bid}/blocks", params={"chapter": 2})).json()["items"]
                if "tugʻilgan" in b["source_text"])
    assert "Uoshington" in born["tts_text"]

    # Noaniq satrni qoʻlda biriktirish
    nega = next(b for b in blocks if b["source_text"] == "Nega?")
    r = await client.patch(f"/books/{bid}/blocks/{nega['id']}", json={"character_id": names["Kumush"]["id"]})
    assert r.status_code == 200 and r.json()[0]["needs_review"] is False

    # Uzun matn bilan tahrir → avtomatik boʻlinish
    long_text = ("Bu juda uzun tahrirlangan gap boʻlib, u davom etadi. " * 50).strip()
    r = await client.patch(f"/books/{bid}/blocks/{born['id']}", json={"source_text": long_text})
    assert r.status_code == 200 and len(r.json()) == 2 and all(len(b["source_text"]) <= 2000 for b in r.json())

    est = (await client.get(f"/books/{bid}/estimate")).json()
    assert est["sufficient"] and est["total_chars"] > 0 and set(est["chars_by_provider"]) <= {"elevenlabs", "gemini"}

    r = await client.post(f"/books/{bid}/synthesize")
    assert r.status_code == 202, r.text
    book = (await client.get(f"/books/{bid}")).json()
    assert book["status"] == "READY_FOR_EXPORT", book["error_message"]

    exp = (await client.get(f"/books/{bid}/export")).json()
    assert exp["m4b"].endswith("book.m4b") and len(exp["chapters"]) == 3
    assert all(c["duration_ms"] > 2500 for c in exp["chapters"])
    m4b = env["store"].root / f"books/{bid}/output/book.m4b"
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters",
                                      str(m4b)], capture_output=True).stdout)
    assert [c["tags"]["title"] for c in info["chapters"]] == ["Kirish", "1-bob. Uchrashuv", "2-bob. Xayrlashuv"]

    # Personaj ovozini almashtirish → faqat uning bloklari PENDING
    voices = (await client.get("/voices", params={"provider": "gemini"})).json()
    leda = next(v for v in voices if v["provider_voice_id"] == "Leda")
    r = await client.patch(f"/books/{bid}/characters/{names['Kumush']['id']}", json={"voice_profile_id": leda["id"]})
    assert r.status_code == 200 and r.json()["tts_tier"] == "TIER_2"
    pending = [b for b in (await client.get(f"/books/{bid}/blocks", params={"limit": 500})).json()["items"]
               if b["status"] == "PENDING"]
    assert pending and all(b["character_id"] == names["Kumush"]["id"] for b in pending)

    # Birlashtirish
    r = await client.patch(f"/books/{bid}/characters/{names['Otabek']['id']}",
                           json={"merge_into_id": names["Kumush"]["id"]})
    assert r.status_code == 200
    chars = (await client.get(f"/books/{bid}/characters")).json()
    assert len(chars) == 1 and "Otabek" in chars[0]["aliases"]


async def test_events_pubsub_roundtrip():
    """Ishchi Redis'ga yozgan hodisa SSE obunachisiga yetib boradi.
    (httpx ASGITransport cheksiz oqimni qoʻllamagani uchun SSE generatori toʻgʻridan-toʻgʻri tekshiriladi.)"""
    import asyncio

    from app import events

    pid = str(uuid.uuid4())
    gen = events.subscribe("project", pid)
    first = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0.3)
    events.publish("project", pid, "progress", stage="TTS", progress=42.5, message="Sintez: 1/2")
    raw = await asyncio.wait_for(first, timeout=5)
    while raw is None:
        raw = await asyncio.wait_for(gen.__anext__(), timeout=5)
    event = json.loads(raw)
    assert event["type"] == "progress" and event["progress"] == 42.5 and event["stage"] == "TTS"
    await gen.aclose()
