export type ProjectStatus =
  | "UPLOADED" | "STEM_SEPARATION" | "TRANSCRIBED" | "TRANSLATED" | "TTS_DISPATCHED"
  | "TIMING_ALIGNED" | "MASTERED" | "READY_FOR_EXPORT" | "FAILED";
export type BookStatus =
  | "UPLOADED" | "PARSED" | "NORMALIZED" | "SEGMENTED" | "ATTRIBUTED" | "LEXICON_APPLIED"
  | "TTS_DISPATCHED" | "STITCHED" | "READY_FOR_EXPORT" | "FAILED";
export type SegmentStatus = "PENDING" | "TRANSLATED" | "SYNTHESIZED" | "ALIGNED" | "FAILED";
export type Gender = "MALE" | "FEMALE" | "UNKNOWN";
export type AgeGroup = "CHILD" | "YOUNG_ADULT" | "ADULT" | "ELDERLY" | "UNKNOWN";
export type Provider = "elevenlabs" | "gemini";
export type Tier = "TIER_1" | "TIER_2";
export type TTSMode = "PREMIUM" | "BALANCED" | "BUDGET";

export interface User { id: string; email: string; full_name: string | null; credit_balance_usd: string; created_at: string }

export interface Voice {
  id: string; name: string; provider: Provider; provider_voice_id: string; gender: Gender; age_group: AgeGroup;
  is_cloned: boolean; is_narrator: boolean; description: string | null; is_system: boolean;
}

export interface Project {
  id: string; title: string; source_language: string; target_language: string; status: ProjectStatus;
  tts_mode: TTSMode; review_before_tts: boolean; progress: string; error_message: string | null;
  duration_seconds: string | null; estimated_cost_usd: string | null; created_at: string; updated_at: string;
}

export interface Speaker {
  id: string; speaker_tag: string; display_name: string | null; detected_gender: Gender; detected_age_group: AgeGroup;
  speech_seconds: string; words_per_second: string | null; tts_tier: Tier; voice_profile_id: string | null;
  is_custom_cloned: boolean; sample_url: string | null; voice: Voice | null;
}

export interface Segment {
  id: string; speaker_id: string | null; sequence_order: number; start_time: string; end_time: string;
  original_text: string; translated_text_uz: string | null; emotion_tag: string; source_syllables: number | null;
  target_syllables: number | null; max_syllables: number | null; tts_duration_ms: number | null;
  tempo_ratio: string | null; status: SegmentStatus; manual_override_flags: boolean; audio_url: string | null;
}

export interface Timeline {
  project: Project; duration: number | null;
  stems: { original: string | null; vocals: string | null; bgm: string | null; dubbed_dialogue: string | null; dubbed_mix: string | null };
  peaks: { duration?: number; original?: number[]; vocals?: number[]; bgm?: number[]; dubbed?: number[] } | null;
  speakers: Speaker[]; segments: Segment[]; pending_changes: number; video_url: string | null; poster_url: string | null;
}

export interface ProjectExport {
  video_mp4: string | null; dubbed_audio: string | null; dialogue_only: string | null;
  subtitles_srt: string | null; subtitles_vtt: string | null;
}

export interface Book {
  id: string; title: string; author: string | null; source_format: string; status: BookStatus; tts_mode: TTSMode;
  progress: string; error_message: string | null; narrator_voice_profile_id: string | null; total_chars: number | null;
  estimated_cost_usd: string | null; created_at: string; updated_at: string;
}

export interface Chapter {
  id: string; chapter_index: number; title: string | null; duration_ms: number | null; block_count: number;
  review_count: number; synthesized_count: number; audio_url: string | null;
}

export interface Character {
  id: string; canonical_name: string; aliases: string[]; gender: Gender; age_group: AgeGroup; dialogue_share: string;
  tts_tier: Tier; voice_profile_id: string | null; voice: Voice | null;
}

export interface Block {
  id: string; chapter_id: string; sequence_order: number; block_type: "NARRATION" | "DIALOGUE" | "HEADING";
  character_id: string | null; source_text: string; tts_text: string | null; emotion_tag: string; pause_after_ms: number;
  attribution_confidence: string | null; needs_review: boolean; duration_ms: number | null; status: SegmentStatus;
  audio_url: string | null;
}

export interface LexiconEntry {
  id: string; book_id: string | null; term: string; phonetic_uz: string;
  source: "USER" | "GLOBAL" | "AUTO_SUGGESTED"; approved: boolean;
}

export interface Estimate {
  total_chars: number; chars_by_provider: Record<string, number>; api_cost_usd: string; charge_usd: string;
  balance_usd: string; sufficient: boolean;
}

export interface BookExport {
  m4b: string | null; chapters_zip: string | null;
  chapters: { index: number; title: string | null; duration_ms: number; mp3: string }[];
}

export interface Transaction {
  id: string; kind: "BONUS" | "TOPUP" | "HOLD" | "SETTLE" | "REFUND"; amount_usd: string; balance_after_usd: string;
  media_project_id: string | null; book_project_id: string | null; payment_id: string | null;
  description: string | null; created_at: string;
}

export interface Usage {
  rows: { provider: Provider; jobs: number; failed: number; characters: number; audio_seconds: number;
    api_cost_usd: string; avg_latency_ms: number; fallbacks: number }[];
  total_api_cost_usd: string; total_charge_usd: string;
}

export interface PipelineEvent {
  type: "snapshot" | "status" | "progress" | "segment" | "block" | "cost" | "error";
  entity: "project" | "book"; id: string; status: string | null; stage: string | null; progress: number | null;
  message: string | null; data: Record<string, unknown>; ts: string;
}

export const EMOTIONS = [
  "neutral", "happy", "sad", "angry", "excited", "fearful", "surprised",
  "whisper", "tender", "sarcastic", "serious", "curious", "hesitant", "anxious",
] as const;
