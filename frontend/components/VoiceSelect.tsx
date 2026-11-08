"use client";

import type { Voice } from "@/lib/types";
import { AGE_LABEL, GENDER_LABEL } from "@/lib/format";

export function VoiceSelect({ id, voices, value, onChange, disabled }: {
  id: string; voices: Voice[]; value: string | null; onChange: (voiceId: string) => void; disabled?: boolean;
}) {
  const groups: Record<string, Voice[]> = {};
  for (const v of voices) {
    const g = v.is_cloned ? "Klonlangan ovozlar" : v.provider === "elevenlabs" ? "ElevenLabs (1-daraja)" : "Gemini (2-daraja)";
    (groups[g] ??= []).push(v);
  }
  return (
    <select id={id} className="input cursor-pointer" value={value ?? ""} disabled={disabled}
            onChange={(e) => onChange(e.target.value)}>
      <option value="" disabled>Ovozni tanlang</option>
      {Object.entries(groups).map(([g, list]) => (
        <optgroup key={g} label={g}>
          {list.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name} ({GENDER_LABEL[v.gender].toLowerCase()}, {AGE_LABEL[v.age_group].toLowerCase()})
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
