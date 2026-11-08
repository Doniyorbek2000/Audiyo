"use client";

import { Copy, Play, Square } from "lucide-react";
import { useRef, useState } from "react";
import { VoiceSelect } from "@/components/VoiceSelect";
import { AGE_LABEL, GENDER_LABEL, SPEAKER_COLORS } from "@/lib/format";
import type { Speaker, Voice } from "@/lib/types";

export function SpeakerPanel({ speakers, voices, onPatch, onClone, cloningEnabled }: {
  speakers: Speaker[]; voices: Voice[];
  onPatch: (id: string, patch: Record<string, unknown>) => Promise<void>;
  onClone: (id: string) => Promise<void>;
  cloningEnabled: boolean;
}) {
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  function play(sp: Speaker) {
    audio.current?.pause();
    if (playing === sp.id || !sp.sample_url) { setPlaying(null); return; }
    audio.current = new Audio(sp.sample_url);
    audio.current.onended = () => setPlaying(null);
    void audio.current.play().then(() => setPlaying(sp.id)).catch(() => setPlaying(null));
  }

  return (
    <div className="space-y-3">
      {speakers.map((sp, i) => (
        <div key={sp.id} className="card space-y-3 p-4">
          <div className="flex items-center gap-2">
            <span aria-hidden className="size-3 shrink-0 rounded" style={{ background: SPEAKER_COLORS[i % SPEAKER_COLORS.length] }} />
            <label className="sr-only" htmlFor={`name-${sp.id}`}>Spiker nomi</label>
            <input id={`name-${sp.id}`} defaultValue={sp.display_name ?? sp.speaker_tag}
                   onBlur={(e) => e.target.value !== sp.display_name && onPatch(sp.id, { display_name: e.target.value })}
                   className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-1 py-0.5 font-semibold hover:border-field-edge focus:border-info focus:outline-none" />
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${sp.tts_tier === "TIER_1" ? "bg-accent/15 text-accent" : "bg-info/15 text-info"}`}
                  title={sp.tts_tier === "TIER_1" ? "1-daraja: ElevenLabs" : "2-daraja: Gemini"}>
              {sp.tts_tier === "TIER_1" ? "T1" : "T2"}
            </span>
          </div>
          <p className="text-xs text-muted">
            {GENDER_LABEL[sp.detected_gender]}, {AGE_LABEL[sp.detected_age_group].toLowerCase()}, {Number(sp.speech_seconds).toFixed(0)} s nutq
            {sp.words_per_second ? `, ${Number(sp.words_per_second).toFixed(1)} soʻz/s` : ""}
          </p>
          <div>
            <label className="label" htmlFor={`voice-${sp.id}`}>Ovoz aktyori</label>
            <VoiceSelect id={`voice-${sp.id}`} voices={voices} value={sp.voice_profile_id}
                         onChange={(v) => onPatch(sp.id, { voice_profile_id: v })} />
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary min-h-9 flex-1 text-xs" disabled={!sp.sample_url} onClick={() => play(sp)}>
              {playing === sp.id ? <Square className="size-3.5" /> : <Play className="size-3.5" />} Asl ovoz
            </button>
            <button type="button" className="btn-secondary min-h-9 flex-1 text-xs" disabled={!cloningEnabled || !sp.sample_url || sp.is_custom_cloned}
                    onClick={() => onClone(sp.id)} title="ElevenLabs Instant Voice Cloning: faqat huquqiga ega boʻlgan ovozlar uchun">
              <Copy className="size-3.5" /> {sp.is_custom_cloned ? "Klonlangan" : "Klonlash"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
