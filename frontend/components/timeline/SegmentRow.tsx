"use client";

import { Languages, Play, RotateCcw, Save, Square } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import { StatusBadge, Spinner } from "@/components/ui";
import { EMOTION_LABEL, formatTime } from "@/lib/format";
import { EMOTIONS, type Segment, type Speaker } from "@/lib/types";

/** Oʻzbekcha boʻgʻin: har unli (a, e, i, o, u, oʻ) bitta boʻgʻin. Backend bilan bir xil qoida. */
export function countUzSyllables(text: string): number {
  return (text.match(/[aeiouAEIOU]/g) ?? []).length;
}

export interface SegmentRowProps {
  segment: Segment;
  speakers: Speaker[];
  color: string;
  selected: boolean;
  onSelect: (id: string) => void;
  onSave: (id: string, patch: Partial<Pick<Segment, "translated_text_uz" | "speaker_id" | "emotion_tag">>) => Promise<void>;
  onRetranslate: (id: string) => Promise<void>;
  onSeek: (t: number) => void;
}

function SegmentRowImpl({ segment: s, speakers, color, selected, onSelect, onSave, onRetranslate, onSeek }: SegmentRowProps) {
  const [text, setText] = useState(s.translated_text_uz ?? "");
  const [busy, setBusy] = useState<"save" | "retranslate" | null>(null);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => setText(s.translated_text_uz ?? ""), [s.translated_text_uz]);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);
  useEffect(() => () => audio.current?.pause(), []);

  const dirty = text.trim() !== (s.translated_text_uz ?? "").trim();
  const syl = countUzSyllables(text);
  const max = s.max_syllables ?? Infinity;
  const over = syl > max;
  const dur = Number(s.end_time) - Number(s.start_time);

  async function save() {
    if (!dirty || !text.trim()) return;
    setBusy("save");
    try { await onSave(s.id, { translated_text_uz: text.trim() }); } finally { setBusy(null); }
  }

  function preview() {
    if (!s.audio_url) return;
    if (playing) { audio.current?.pause(); setPlaying(false); return; }
    audio.current = new Audio(s.audio_url);
    audio.current.onended = () => setPlaying(false);
    void audio.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }

  return (
    <div ref={ref} onClick={() => onSelect(s.id)}
         className={`grid gap-3 border-b border-line p-4 transition-colors duration-200 md:grid-cols-[150px_1fr] ${
           selected ? "bg-surface-2/60" : "hover:bg-elevated/60"}`}>
      <div className="flex flex-row flex-wrap items-center gap-2 md:flex-col md:items-start">
        <button type="button" onClick={(e) => { e.stopPropagation(); onSeek(Number(s.start_time)); }}
                className="cursor-pointer font-mono text-xs text-info hover:underline">
          {formatTime(Number(s.start_time))}
        </button>
        <span className="text-xs text-muted">{dur.toFixed(2)} s{s.tempo_ratio ? `, tezlik ${Number(s.tempo_ratio).toFixed(2)}×` : ""}</span>
        <StatusBadge status={s.status} />
        {s.manual_override_flags && <span className="text-[11px] font-semibold text-warn">Qoʻlda tahrirlangan</span>}
      </div>

      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span aria-hidden className="size-2.5 rounded-sm" style={{ background: color }} />
          <label className="sr-only" htmlFor={`sp-${s.id}`}>Spiker</label>
          <select id={`sp-${s.id}`} value={s.speaker_id ?? ""} onClick={(e) => e.stopPropagation()}
                  onChange={(e) => onSave(s.id, { speaker_id: e.target.value || null })}
                  className="cursor-pointer rounded-lg border border-field-edge bg-bg px-2 py-1 text-xs font-semibold">
            {speakers.map((sp) => <option key={sp.id} value={sp.id}>{sp.display_name ?? sp.speaker_tag}</option>)}
          </select>
          <label className="sr-only" htmlFor={`em-${s.id}`}>Emotsiya</label>
          <select id={`em-${s.id}`} value={s.emotion_tag} onClick={(e) => e.stopPropagation()}
                  onChange={(e) => onSave(s.id, { emotion_tag: e.target.value })}
                  className="cursor-pointer rounded-lg border border-field-edge bg-bg px-2 py-1 text-xs">
            {EMOTIONS.map((em) => <option key={em} value={em}>{EMOTION_LABEL[em]}</option>)}
          </select>
          <p className="min-w-0 flex-1 truncate text-sm text-muted" title={s.original_text}>{s.original_text}</p>
        </div>

        <label className="sr-only" htmlFor={`tx-${s.id}`}>Oʻzbekcha matn</label>
        <textarea id={`tx-${s.id}`} rows={2} value={text} onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void save(); } }}
                  className={`input resize-y text-[15px] leading-relaxed ${over ? "border-warn/70" : ""}`}
                  placeholder="Tarjima kutilmoqda…" />

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`tabular-nums ${over ? "font-semibold text-warn" : "text-muted"}`}>
            {syl}/{Number.isFinite(max) ? max : "?"} boʻgʻin{over ? ", vaqtga sigʻmasligi mumkin" : ""}
          </span>
          <div className="ml-auto flex gap-1.5">
            <button type="button" className="btn-ghost min-h-9 px-2.5 text-xs" disabled={!s.audio_url}
                    onClick={(e) => { e.stopPropagation(); preview(); }} aria-label="Segment ovozini tinglash">
              {playing ? <Square className="size-3.5" /> : <Play className="size-3.5" />} Tinglash
            </button>
            <button type="button" className="btn-ghost min-h-9 px-2.5 text-xs" disabled={busy !== null}
                    onClick={async (e) => { e.stopPropagation(); setBusy("retranslate"); try { await onRetranslate(s.id); } finally { setBusy(null); } }}>
              {busy === "retranslate" ? <Spinner className="size-3.5" /> : <Languages className="size-3.5" />} Qayta tarjima
            </button>
            {dirty && (
              <>
                <button type="button" className="btn-ghost min-h-9 px-2.5 text-xs"
                        onClick={(e) => { e.stopPropagation(); setText(s.translated_text_uz ?? ""); }}>
                  <RotateCcw className="size-3.5" /> Bekor
                </button>
                <button type="button" className="btn-primary min-h-9 px-3 text-xs" disabled={busy !== null}
                        onClick={(e) => { e.stopPropagation(); void save(); }}>
                  {busy === "save" ? <Spinner className="size-3.5" /> : <Save className="size-3.5" />} Saqlash
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export const SegmentRow = memo(SegmentRowImpl);
