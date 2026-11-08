# AI Video Dublyaj SaaS — Texnik topshiriq (manba matn)

> Foydalanuvchi tomonidan berilgan asl texnik topshiriq. Keyingi arxitektura va kod ishlari shu hujjatga asoslanadi.

## Rol
Ekspert tizimlar arxitektori, media qayta ishlash muhandisi va full-stack texnik rahbar. Vazifa: oʻzbekcha lokalizatsiyaga qaratilgan avtomatlashtirilgan AI video dublyaj SaaS platformasi uchun toʻliq ishlab chiqarish arxitekturasi, PostgreSQL sxemasi, audio/video konveyeri, koʻp provayderli TTS yoʻnaltirish va tizim spetsifikatsiyalari.

## Asosiy modullar
1. Ovozni ajratish (vokal va fon musiqasi/effektlar).
2. STT + spikerni aniqlash (jins, yosh guruhi, vaqt belgilari).
3. LLM asosida tarjima va oʻzbek tili uchun boʻgʻin/davomiylik moslashuvi.
4. Dinamik TTS marshrutlash (ElevenLabs ↔ Google Gemini TTS, xarajatni optimallashtirib).
5. Pitch-shiftingsiz davomiylikni meʼyorlash.
6. Yakuniy mikslash (dublyaj + asl fon/effektlar).
7. Veb UI: vaqt jadvali, ssenariyni tahrirlash, ovozni qayta tayinlash, hisob-kitob.

## Talab etiladigan spetsifikatsiyalar

### 1. Tizim arxitekturasi
Veb-frontend → API shlyuzi (Nginx/Traefik) → FastAPI servislar (Auth, Projects, Billing) → Orkestrator (Temporal.io yoki Celery/Redis) → GPU ishchilar (Demucs, WhisperX, FFmpeg) → Saqlash (S3/MinIO, PostgreSQL, Redis).

### 2. Media konveyeri
- FFmpeg demux → Demucs v4 (Hybrid Transformer): `vocals.wav`, `accompaniment.wav`.
- WhisperX / pyannote.audio: soʻz darajasidagi vaqt belgilari, `Speaker_0..N`, jins taxmini, nutq tezligi.
- LLM tarjima (oʻzbek, lotin): agglyutinativ kengayishni kompensatsiya qilish uchun boʻgʻin cheklovlari. JSON: `segment_id, speaker_id, source_text, target_uz_text, target_duration_ms, emotion_tag`.
- Vaqt moslash: rubberband / sox / FFmpeg `atempo` (0.85x–1.25x); sidechain ducking; MP4/MKV ga SRT/VTT bilan muxlash.

### 3. TTS marshrutlash
- 1-daraja: ElevenLabs Multilingual v2 — asosiy qahramonlar, emotsional diapazon, ovoz klonlash.
- 2-daraja: Google Gemini TTS — ikkilamchi spikerlar, monologlar, budjet rejimi.
- Xatolar: timeout, kvota tugashi, fallback.
- Xarajat formulasi: provayder boʻyicha belgi/sekund asosida real vaqt kredit hisobi.
- Spiker–ovoz profili reyestri: butun film davomida ovoz izchilligi.

### 4. PostgreSQL DDL (dastlabki)
```sql
CREATE TABLE media_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  title VARCHAR(255) NOT NULL,
  source_language VARCHAR(10) NOT NULL,
  target_language VARCHAR(10) DEFAULT 'uz',
  status VARCHAR(50) NOT NULL, -- UPLOADED, SEPARATING, TRANSCRIBING, TRANSLATING, DUBBING, MASTERING, COMPLETED, FAILED
  source_video_url TEXT NOT NULL,
  isolated_bgm_url TEXT,
  isolated_vocal_url TEXT,
  dubbed_video_url TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE speakers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES media_projects(id) ON DELETE CASCADE,
  speaker_tag VARCHAR(50) NOT NULL,
  detected_gender VARCHAR(20),     -- MALE, FEMALE, UNKNOWN
  detected_age_group VARCHAR(20),  -- CHILD, YOUNG_ADULT, ADULT, ELDERLY
  sample_audio_url TEXT,
  elevenlabs_voice_id VARCHAR(100),
  is_custom_cloned BOOLEAN DEFAULT FALSE
);

CREATE TABLE dialogue_segments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES media_projects(id) ON DELETE CASCADE,
  speaker_id UUID REFERENCES speakers(id),
  sequence_order INT NOT NULL,
  start_time NUMERIC(10, 3) NOT NULL,
  end_time NUMERIC(10, 3) NOT NULL,
  original_text TEXT NOT NULL,
  translated_text_uz TEXT,
  tts_audio_url TEXT,
  status VARCHAR(50) DEFAULT 'PENDING', -- TRANSLATED, SYNTHESIZED, ALIGNED
  manual_override_flags BOOLEAN DEFAULT FALSE
);

CREATE TABLE tts_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  segment_id UUID REFERENCES dialogue_segments(id) ON DELETE CASCADE,
  provider_name VARCHAR(50) NOT NULL, -- gemini | elevenlabs
  token_character_count INT NOT NULL,
  api_cost_usd NUMERIC(10, 4) NOT NULL,
  execution_latency_ms INT NOT NULL,
  retry_count INT DEFAULT 0
);

CREATE TABLE transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  credit_deduction_usd NUMERIC(10, 4) NOT NULL,
  payment_id VARCHAR(100) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 5. Holat mashinasi va navbatlar
- `UPLOADED → STEM_SEPARATION → TRANSCRIBED → TRANSLATED → TTS_DISPATCHED → TIMING_ALIGNED → MASTERED → READY_FOR_EXPORT`
- GPU ishlari (Demucs, Whisper) va I/O ishlari (TTS API, S3 yuklash) uchun alohida ishchi navbatlari.
- Real vaqt progress uchun WebSocket / SSE hodisa sxemasi.

### 6. Stek va API
- Backend: FastAPI (async, Pydantic v2) + Celery/Temporal + FFmpeg.
- Frontend: Next.js (App Router), Tailwind CSS, WaveSurfer.js (koʻp yoʻlakli toʻlqin), subtitr vaqt sozlagich.
- Endpointlar:
  - `POST /api/v1/projects/upload`
  - `GET /api/v1/projects/{id}/timeline`
  - `PATCH /api/v1/projects/{id}/segments/{segment_id}` (matnni tahrirlash, ovozni qayta generatsiya, remiks)
  - Segmentlarni hisoblash, tranzaksiyalar va yakuniy eksport.

> Eslatma: asl matn shu joyda uzilgan edi (oxirgi boʻlim toʻliq emas).

---

Qoʻshimcha modul: [Kitob va uzun matnlarni qayta ishlash](BOOK_TTS_MODULE.md)
