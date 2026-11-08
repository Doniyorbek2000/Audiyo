-- Audiyo: boshlangʻich sxema
-- Video dublyaj + kitob/uzun matn TTS moduli

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ===================== ENUM turlari =====================
CREATE TYPE project_status AS ENUM (
  'UPLOADED', 'STEM_SEPARATION', 'TRANSCRIBED', 'TRANSLATED', 'TTS_DISPATCHED',
  'TIMING_ALIGNED', 'MASTERED', 'READY_FOR_EXPORT', 'FAILED');

CREATE TYPE book_status AS ENUM (
  'UPLOADED', 'PARSED', 'NORMALIZED', 'SEGMENTED', 'ATTRIBUTED',
  'LEXICON_APPLIED', 'TTS_DISPATCHED', 'STITCHED', 'READY_FOR_EXPORT', 'FAILED');

CREATE TYPE segment_status AS ENUM ('PENDING', 'TRANSLATED', 'SYNTHESIZED', 'ALIGNED', 'FAILED');
CREATE TYPE block_type AS ENUM ('NARRATION', 'DIALOGUE', 'HEADING');
CREATE TYPE gender AS ENUM ('MALE', 'FEMALE', 'UNKNOWN');
CREATE TYPE age_group AS ENUM ('CHILD', 'YOUNG_ADULT', 'ADULT', 'ELDERLY', 'UNKNOWN');
CREATE TYPE tts_provider AS ENUM ('elevenlabs', 'gemini');
CREATE TYPE tts_tier AS ENUM ('TIER_1', 'TIER_2');
CREATE TYPE tts_mode AS ENUM ('PREMIUM', 'BALANCED', 'BUDGET');
CREATE TYPE tts_job_status AS ENUM ('SUCCEEDED', 'FAILED');
CREATE TYPE transaction_kind AS ENUM ('BONUS', 'TOPUP', 'HOLD', 'SETTLE', 'REFUND');
CREATE TYPE lexicon_source AS ENUM ('USER', 'GLOBAL', 'AUTO_SUGGESTED');

-- ===================== Foydalanuvchilar =====================
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(255),
  credit_balance_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================== Ovoz profillari reyestri =====================
CREATE TABLE voice_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,   -- NULL = tizim ovozi
  name VARCHAR(100) NOT NULL,
  provider tts_provider NOT NULL,
  provider_voice_id VARCHAR(100) NOT NULL,
  gender gender NOT NULL DEFAULT 'UNKNOWN',
  age_group age_group NOT NULL DEFAULT 'ADULT',
  is_cloned BOOLEAN NOT NULL DEFAULT FALSE,
  is_narrator BOOLEAN NOT NULL DEFAULT FALSE,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE NULLS NOT DISTINCT (provider, provider_voice_id, user_id)
);
CREATE INDEX idx_voice_profiles_lookup ON voice_profiles (provider, gender, age_group);

-- ===================== Video loyihalar =====================
CREATE TABLE media_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL,
  source_language VARCHAR(10) NOT NULL,
  target_language VARCHAR(10) NOT NULL DEFAULT 'uz',
  status project_status NOT NULL DEFAULT 'UPLOADED',
  tts_mode tts_mode NOT NULL DEFAULT 'BALANCED',
  review_before_tts BOOLEAN NOT NULL DEFAULT FALSE,
  progress NUMERIC(5, 2) NOT NULL DEFAULT 0,
  error_message TEXT,
  duration_seconds NUMERIC(10, 3),
  source_video_key TEXT NOT NULL,
  original_audio_key TEXT,
  isolated_bgm_key TEXT,
  isolated_vocal_key TEXT,
  dubbed_dialogue_key TEXT,
  dubbed_mix_key TEXT,
  dubbed_video_key TEXT,
  subtitles_srt_key TEXT,
  subtitles_vtt_key TEXT,
  waveform_peaks JSONB,
  estimated_cost_usd NUMERIC(10, 4),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_media_projects_user ON media_projects (user_id, created_at DESC);

-- ===================== Spikerlar =====================
CREATE TABLE speakers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES media_projects(id) ON DELETE CASCADE,
  speaker_tag VARCHAR(50) NOT NULL,
  display_name VARCHAR(100),
  detected_gender gender NOT NULL DEFAULT 'UNKNOWN',
  detected_age_group age_group NOT NULL DEFAULT 'UNKNOWN',
  speech_seconds NUMERIC(10, 3) NOT NULL DEFAULT 0,
  words_per_second NUMERIC(6, 3),
  sample_audio_key TEXT,
  tts_tier tts_tier NOT NULL DEFAULT 'TIER_2',
  voice_profile_id UUID REFERENCES voice_profiles(id) ON DELETE SET NULL,
  elevenlabs_voice_id VARCHAR(100),
  is_custom_cloned BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (project_id, speaker_tag)
);

-- ===================== Dialog segmentlari =====================
CREATE TABLE dialogue_segments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES media_projects(id) ON DELETE CASCADE,
  speaker_id UUID REFERENCES speakers(id) ON DELETE SET NULL,
  sequence_order INT NOT NULL,
  start_time NUMERIC(10, 3) NOT NULL,
  end_time NUMERIC(10, 3) NOT NULL,
  original_text TEXT NOT NULL,
  translated_text_uz TEXT,
  emotion_tag VARCHAR(30) NOT NULL DEFAULT 'neutral',
  source_syllables INT,
  target_syllables INT,
  words JSONB,
  tts_audio_key TEXT,
  tts_duration_ms INT,
  tempo_ratio NUMERIC(5, 3),
  aligned_audio_key TEXT,
  status segment_status NOT NULL DEFAULT 'PENDING',
  manual_override_flags BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (end_time > start_time),
  UNIQUE (project_id, sequence_order)
);
CREATE INDEX idx_segments_project ON dialogue_segments (project_id, start_time);
CREATE INDEX idx_segments_speaker ON dialogue_segments (speaker_id);

-- ===================== Kitob loyihalari =====================
CREATE TABLE book_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL,
  author VARCHAR(255),
  source_file_key TEXT NOT NULL,
  source_format VARCHAR(10) NOT NULL,
  status book_status NOT NULL DEFAULT 'UPLOADED',
  tts_mode tts_mode NOT NULL DEFAULT 'BALANCED',
  progress NUMERIC(5, 2) NOT NULL DEFAULT 0,
  error_message TEXT,
  narrator_voice_profile_id UUID REFERENCES voice_profiles(id) ON DELETE SET NULL,
  total_chars INT,
  estimated_cost_usd NUMERIC(10, 4),
  output_m4b_key TEXT,
  output_zip_key TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_book_projects_user ON book_projects (user_id, created_at DESC);

CREATE TABLE book_chapters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id UUID NOT NULL REFERENCES book_projects(id) ON DELETE CASCADE,
  chapter_index INT NOT NULL,
  title TEXT,
  audio_key TEXT,
  duration_ms INT,
  UNIQUE (book_id, chapter_index)
);

CREATE TABLE book_characters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id UUID NOT NULL REFERENCES book_projects(id) ON DELETE CASCADE,
  canonical_name VARCHAR(255) NOT NULL,
  aliases TEXT[] NOT NULL DEFAULT '{}',
  gender gender NOT NULL DEFAULT 'UNKNOWN',
  age_group age_group NOT NULL DEFAULT 'UNKNOWN',
  dialogue_share NUMERIC(5, 4) NOT NULL DEFAULT 0,
  tts_tier tts_tier NOT NULL DEFAULT 'TIER_2',
  voice_profile_id UUID REFERENCES voice_profiles(id) ON DELETE SET NULL,
  UNIQUE (book_id, canonical_name)
);

CREATE TABLE text_blocks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id UUID NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
  sequence_order INT NOT NULL,
  block_type block_type NOT NULL,
  character_id UUID REFERENCES book_characters(id) ON DELETE SET NULL,  -- NULL = hikoyachi
  source_text TEXT NOT NULL CHECK (char_length(source_text) <= 2000),
  tts_text TEXT,
  emotion_tag VARCHAR(30) NOT NULL DEFAULT 'neutral',
  pause_after_ms INT NOT NULL DEFAULT 500,
  attribution_confidence NUMERIC(3, 2),
  needs_review BOOLEAN NOT NULL DEFAULT FALSE,
  tts_audio_key TEXT,
  duration_ms INT,
  status segment_status NOT NULL DEFAULT 'PENDING',
  UNIQUE (chapter_id, sequence_order)
);
CREATE INDEX idx_text_blocks_review ON text_blocks (chapter_id) WHERE needs_review;

CREATE TABLE pronunciation_lexicon (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id UUID REFERENCES book_projects(id) ON DELETE CASCADE,  -- NULL = global
  term VARCHAR(255) NOT NULL,
  phonetic_uz VARCHAR(255) NOT NULL,
  source lexicon_source NOT NULL DEFAULT 'USER',
  approved BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX uq_lexicon_term ON pronunciation_lexicon
  (COALESCE(book_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(term));

-- ===================== TTS ishlari =====================
CREATE TABLE tts_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  segment_id UUID REFERENCES dialogue_segments(id) ON DELETE CASCADE,
  text_block_id UUID REFERENCES text_blocks(id) ON DELETE CASCADE,
  provider_name tts_provider NOT NULL,
  fallback_from tts_provider,
  status tts_job_status NOT NULL,
  token_character_count INT NOT NULL,
  audio_seconds NUMERIC(10, 3) NOT NULL DEFAULT 0,
  api_cost_usd NUMERIC(10, 4) NOT NULL DEFAULT 0,
  execution_latency_ms INT NOT NULL DEFAULT 0,
  retry_count INT NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((segment_id IS NOT NULL)::int + (text_block_id IS NOT NULL)::int = 1)
);
CREATE INDEX idx_tts_jobs_segment ON tts_jobs (segment_id);
CREATE INDEX idx_tts_jobs_block ON tts_jobs (text_block_id);
CREATE INDEX idx_tts_jobs_user_time ON tts_jobs (user_id, created_at DESC);

-- ===================== Tranzaksiyalar =====================
CREATE TABLE transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind transaction_kind NOT NULL,
  amount_usd NUMERIC(12, 4) NOT NULL,            -- musbat = kirim, manfiy = yechim
  balance_after_usd NUMERIC(12, 4) NOT NULL,
  media_project_id UUID REFERENCES media_projects(id) ON DELETE SET NULL,
  book_project_id UUID REFERENCES book_projects(id) ON DELETE SET NULL,
  payment_id VARCHAR(100),
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_transactions_user ON transactions (user_id, created_at DESC);
CREATE UNIQUE INDEX uq_transactions_payment ON transactions (payment_id) WHERE payment_id IS NOT NULL;

-- ===================== Global talaffuz leksikoni (boshlangʻich) =====================
INSERT INTO pronunciation_lexicon (book_id, term, phonetic_uz, source) VALUES
  (NULL, 'iPhone', 'ayfon', 'GLOBAL'),
  (NULL, 'Google', 'gugl', 'GLOBAL'),
  (NULL, 'YouTube', 'yutub', 'GLOBAL'),
  (NULL, 'Facebook', 'feysbuk', 'GLOBAL'),
  (NULL, 'Microsoft', 'maykrosoft', 'GLOBAL'),
  (NULL, 'Shakespeare', 'Shekspir', 'GLOBAL'),
  (NULL, 'Washington', 'Vashington', 'GLOBAL'),
  (NULL, 'New York', 'Nyu-York', 'GLOBAL'),
  (NULL, 'Hollywood', 'Gollivud', 'GLOBAL'),
  (NULL, 'Harry', 'Garri', 'GLOBAL'),
  (NULL, 'Sherlock', 'Sherlok', 'GLOBAL'),
  (NULL, 'Holmes', 'Xolms', 'GLOBAL'),
  (NULL, 'WiFi', 'vay-fay', 'GLOBAL'),
  (NULL, 'email', 'imeyl', 'GLOBAL');
