# MODUL: Kitobni qayta ishlash va rivojlantirilgan TTS

## Asl talablar (foydalanuvchidan)
- **Matnni segmentlash:** roman yoki katta hajmli matnlarni mantiqiy boblar, fasllar yoki dialog bloklariga ajratish (maksimal uzunlik: 2000 belgi/segment).
- **Spiker izchilligi:** butun kitob davomida asosiy personajlar uchun ovoz profilini saqlash, hikoyachi (boshlovchi) uchun alohida neytral ovoz.
- **Intonatsiya va pauza:** tinish belgilariga (vergul, nuqta, dialog chiziqlari) qarab tabiiy pauza va intonatsiya.
- **Xorijiy soʻzlar va nomlar:** oʻzbekcha matndagi chet atamalari va nomlarni toʻgʻri talaffuz qilish uchun fonetik qoidalar.

---

## 1. Konveyer

```
UPLOADED (EPUB/FB2/DOCX/PDF/TXT)
  → PARSED          matnni ajratib olish, boblar daraxti (TOC)
  → NORMALIZED      raqamlar, qisqartmalar, tirnoq/tire unifikatsiyasi, ʻ/ʼ belgilari
  → SEGMENTED       bob → fasl → paragraf → blok (≤ 2000 belgi)
  → ATTRIBUTED      har blok: NARRATOR yoki CHARACTER(x) + emotion_tag (LLM)
  → LEXICON_APPLIED xorijiy soʻz/nomlar uchun talaffuz almashtirish
  → TTS_DISPATCHED  provayder marshrutlash (asosiy video modul bilan umumiy router)
  → STITCHED        bloklar + pauzalar → bob audiosi (loudness −18 LUFS, audiokitob)
  → READY_FOR_EXPORT  M4B (bob belgilari bilan) / MP3 boʻyicha boblar
```

GPU kerak emas — barcha bosqichlar I/O navbatida (`io_queue`) ishlaydi.

## 2. Segmentlash algoritmi

Ierarxik, “eng katta mantiqiy birlikdan pastga” tamoyili:

1. **Bob** — EPUB/FB2 TOC yoki sarlavha regexlari: `^(\d+[-‑]?\s*bob|BOB\s+[IVXLC\d]+|Chapter\s+\d+)`, `^\*\s*\*\s*\*$` (fasl ajratgich).
2. **Paragraf** — boʻsh qator.
3. **Dialog bloki** — satr boshidagi `—`/`–`/`-` yoki `«…»` / `"…"` ichidagi matn alohida blok; muallif izohi (`— dedi Anvar.`) hikoyachi blokiga ajratiladi.
4. **Uzun paragraf** > 2000 belgi boʻlsa: gap chegarasi (`. ! ? …` + katta harf) boʻyicha boʻlinadi; gap ham uzun boʻlsa — `; :` keyin `,` boʻyicha. Hech qachon soʻz oʻrtasida kesilmaydi.
5. **Birlashtirish** — bir paragraf ichidagi hikoya gaplari bitta blokda qoladi (≤ 2000 belgi). Paragraflar orasida birlashtirilmaydi: har blok alohida tahrirlanadi va faqat oʻzgargani qayta sintez qilinadi.
6. **Sarlavhasiz boshlangʻich matn** (masalan, kitob nomi) alohida «Kirish» boʻlimi boʻladi.

> Amalga oshirilgan: `backend/app/services/text/segmenter.py`, `parsers.py`, `pauses.py`, `lexicon.py`, `backend/app/services/llm/attribution.py`, `backend/app/workers/book_tasks.py`.

Natija sxemasi (JSON, har bir blok):

```json
{
  "block_id": "ch03-p012-b02",
  "chapter_index": 3,
  "sequence_order": 412,
  "block_type": "DIALOGUE",          // NARRATION | DIALOGUE | HEADING
  "speaker": "CHAR:Kumush",          // yoki "NARRATOR"
  "text": "Siz meni tashlab ketmaysizmi?",
  "char_count": 29,
  "emotion_tag": "anxious",
  "pause_after_ms": 600
}
```

## 3. Spiker izchilligi

- **Personajlar reyestri** — LLM butun kitob boʻyicha bir marta oʻtib, ism va laqablarni bitta personajga bogʻlaydi (`Otabek`, `Otabekbek`, `bek` → `CHAR:Otabek`), jinsi va yoshini taxmin qiladi.
- **Atributsiya** — har dialog bloki uchun kontekst oynasi (oldingi 3 blok + muallif izohi) bilan LLM “kim gapiryapti?” savoliga javob beradi; ishonch < 0.7 boʻlsa — UI da qoʻlda tasdiqlash uchun belgilanadi.
- **Ovoz tayinlash** — `NARRATOR` uchun bitta neytral ovoz (butun kitob). Asosiy personajlar (dialog ulushi ≥ 5%) → 1-daraja (ElevenLabs), qolganlari → 2-daraja (Gemini) jins/yosh boʻyicha ovozlar havzasidan.
- Bir xil ovoz ikki asosiy personajga berilmaydi; bitta sahnada ishtirok etgan ikkinchi darajali personajlar ham farqli ovoz oladi.

## 4. Pauza va intonatsiya qoidalari

| Belgi / kontekst | Pauza | Intonatsiya |
|---|---|---|
| `,` | 200–250 ms | tekis, davom etuvchi |
| `;` `:` | 350 ms | yarim tushish |
| `.` | 500 ms | pasayuvchi |
| `?` | 500 ms | koʻtariluvchi (soʻroq yuklamasi `-mi`, `-chi` bilan) |
| `!` | 500 ms | kuchaytirilgan, emotion=excited |
| `…` | 700 ms | sekinlashgan, soʻnuvchi |
| `—` dialog boshi | 400 ms oldin | spiker almashadi |
| Paragraf oxiri | 800 ms | — |
| Fasl (`* * *`) | 1500 ms | — |
| Bob oxiri | 2500 ms + bob sarlavhasi hikoyachi ovozida | — |

Amalga oshirish: provayder SSML (`<break time="…"/>`) qoʻllasa — inline; qoʻllamasa — pauza stitching bosqichida jimlik sifatida qoʻshiladi (FFmpeg `anullsrc`). Emotion teglari ElevenLabs uchun `stability/style` parametrlariga, Gemini uchun uslub koʻrsatmasiga (prompt) xaritalanadi.

## 5. Xorijiy soʻzlar va nomlar (talaffuz leksikoni)

Ustuvorlik tartibi:
1. **Loyiha leksikoni** (foydalanuvchi qoʻlda kiritgan) — eng yuqori.
2. **Global leksikon** — keng tarqalgan atamalar (`iPhone → ayfon`, `Google → gugl`, `Shakespeare → Shekspir`, `Washington → Vashington`).
3. **Avtomatik transliteratsiya** — kirill matn/qoʻshimchalar lotinga; lotin yozuvidagi xorijiy soʻz LLM tomonidan aniqlanib, oʻzbekcha fonetik yozuvga oʻgiriladi (`th→s/z`, `w→v`, `ph→f`, `c→k/s`, `x→ks`), natija leksikonga “taklif” sifatida yoziladi.
4. **Qisqartmalar** — `BMT → be-em-te`, `AQSh → a-qu-sha`; raqamlar soʻz bilan (`1991-yil → bir ming toʻqqiz yuz toʻqson birinchi yil`).

Almashtirish faqat TTS ga yuboriladigan matnda bajariladi; asl matn va subtitrlar oʻzgarmaydi. Oʻzbek qoʻshimchalari saqlanadi: `Shakespeare'ning → Shekspirning`.

## 6. PostgreSQL DDL (qoʻshimcha)

```sql
CREATE TYPE book_status AS ENUM (
  'UPLOADED','PARSED','NORMALIZED','SEGMENTED','ATTRIBUTED',
  'LEXICON_APPLIED','TTS_DISPATCHED','STITCHED','READY_FOR_EXPORT','FAILED');
CREATE TYPE block_type AS ENUM ('NARRATION','DIALOGUE','HEADING');

CREATE TABLE book_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  title VARCHAR(255) NOT NULL,
  author VARCHAR(255),
  source_file_url TEXT NOT NULL,
  source_format VARCHAR(10) NOT NULL,          -- epub, fb2, docx, pdf, txt
  status book_status NOT NULL DEFAULT 'UPLOADED',
  narrator_voice_id VARCHAR(100),
  total_chars INT,
  output_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE book_chapters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id UUID NOT NULL REFERENCES book_projects(id) ON DELETE CASCADE,
  chapter_index INT NOT NULL,
  title TEXT,
  audio_url TEXT,
  duration_ms INT,
  UNIQUE (book_id, chapter_index)
);

CREATE TABLE book_characters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id UUID NOT NULL REFERENCES book_projects(id) ON DELETE CASCADE,
  canonical_name VARCHAR(255) NOT NULL,
  aliases TEXT[] DEFAULT '{}',
  gender VARCHAR(20),
  age_group VARCHAR(20),
  dialogue_share NUMERIC(5,4),
  provider_name VARCHAR(50),                   -- elevenlabs | gemini
  voice_id VARCHAR(100),
  UNIQUE (book_id, canonical_name)
);

CREATE TABLE text_blocks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id UUID NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
  sequence_order INT NOT NULL,
  block_type block_type NOT NULL,
  character_id UUID REFERENCES book_characters(id),   -- NULL = hikoyachi
  source_text TEXT NOT NULL CHECK (char_length(source_text) <= 2000),
  tts_text TEXT,                                       -- leksikon qoʻllangan
  emotion_tag VARCHAR(30),
  pause_after_ms INT NOT NULL DEFAULT 500,
  attribution_confidence NUMERIC(3,2),
  needs_review BOOLEAN DEFAULT FALSE,
  tts_audio_url TEXT,
  status VARCHAR(30) DEFAULT 'PENDING',
  UNIQUE (chapter_id, sequence_order)
);
CREATE INDEX idx_text_blocks_review ON text_blocks (chapter_id) WHERE needs_review;

CREATE TABLE pronunciation_lexicon (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id UUID REFERENCES book_projects(id) ON DELETE CASCADE,  -- NULL = global
  term VARCHAR(255) NOT NULL,
  phonetic_uz VARCHAR(255) NOT NULL,
  source VARCHAR(20) NOT NULL DEFAULT 'USER',  -- USER | GLOBAL | AUTO_SUGGESTED
  approved BOOLEAN DEFAULT TRUE
);
CREATE UNIQUE INDEX uq_lexicon_term ON pronunciation_lexicon
  (COALESCE(book_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(term));
```

`tts_jobs` jadvali umumiy qoladi; unga `text_block_id UUID REFERENCES text_blocks(id)` ustuni qoʻshiladi (`segment_id` yoki `text_block_id` — bittasi toʻldirilgan boʻlishi kerak, `CHECK` bilan).

## 7. API

- `POST /api/v1/books/upload` — fayl yuklash, `book_id` qaytaradi.
- `GET /api/v1/books/{id}/chapters` — boblar va holati.
- `GET /api/v1/books/{id}/characters` · `PATCH .../characters/{cid}` — ovozni qayta tayinlash, aliaslarni birlashtirish.
- `GET /api/v1/books/{id}/blocks?chapter=3&needs_review=true` · `PATCH .../blocks/{bid}` — matn, spiker, pauza, emotsiyani tahrirlash → faqat shu blok qayta sintezlanadi.
- `GET/POST/DELETE /api/v1/books/{id}/lexicon` — talaffuz leksikoni.
- `POST /api/v1/books/{id}/export?format=m4b|mp3` — yakuniy eksport.
- SSE: `/api/v1/books/{id}/events` — `{stage, chapter_index, blocks_done, blocks_total, cost_usd}`.

## 8. Xarajat
Kitob uchun oldindan hisob: `total_chars × (ulush_1 × narx_ElevenLabs + ulush_2 × narx_Gemini)` — foydalanuvchiga TTS boshlanishidan oldin koʻrsatiladi va kredit rezerv qilinadi; haqiqiy sarf `tts_jobs` dan yakunda hisoblanadi.
