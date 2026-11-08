"use client";

import { Pause, Play, SkipBack, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import { formatTime, SPEAKER_COLORS } from "@/lib/format";
import type { Segment, Speaker, Timeline } from "@/lib/types";

type SourceKey = "original" | "dubbed_mix" | "vocals" | "bgm" | "dubbed_dialogue";

const SOURCES: { key: SourceKey; label: string }[] = [
  { key: "dubbed_mix", label: "Dublyaj (yakuniy)" },
  { key: "original", label: "Asl audio" },
  { key: "vocals", label: "Vokal" },
  { key: "bgm", label: "Fon + effektlar" },
  { key: "dubbed_dialogue", label: "Faqat dublyaj dialogi" },
];

const TRACKS: { key: "original" | "vocals" | "bgm" | "dubbed"; label: string; color: string }[] = [
  { key: "original", label: "Asl", color: "#475569" },
  { key: "vocals", label: "Vokal", color: "#6366f1" },
  { key: "bgm", label: "Fon", color: "#0d9488" },
  { key: "dubbed", label: "Dublyaj", color: "#e11d48" },
];

export interface MultiTrackProps {
  timeline: Timeline;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRetime: (id: string, start: number, end: number) => void;
  seekTo?: { t: number; nonce: number } | null;
  videoRef?: React.RefObject<HTMLVideoElement | null>;
}

export function MultiTrack({ timeline, selectedId, onSelect, onRetime, seekTo, videoRef }: MultiTrackProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const containers = useRef<Record<string, HTMLDivElement | null>>({});
  const segLane = useRef<HTMLDivElement | null>(null);
  const instances = useRef<WaveSurfer[]>([]);
  const regionsRef = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [zoom, setZoom] = useState(40);
  const [laneReady, setLaneReady] = useState(0);
  const [source, setSource] = useState<SourceKey>(timeline.stems.dubbed_mix ? "dubbed_mix" : "original");

  const duration = timeline.duration ?? timeline.peaks?.duration ?? 0;
  const speakerColor = useMemo(() => {
    const m: Record<string, string> = {};
    timeline.speakers.forEach((s, i) => (m[s.id] = SPEAKER_COLORS[i % SPEAKER_COLORS.length]));
    return m;
  }, [timeline.speakers]);

  // Umumiy audio element (barcha yoʻlakchalar bir kursor bilan)
  if (typeof window !== "undefined" && !audioRef.current) {
    audioRef.current = new Audio();
    audioRef.current.preload = "metadata";
    audioRef.current.crossOrigin = "anonymous";
  }

  // Manba almashtirish: vaqt saqlanadi
  useEffect(() => {
    const audio = audioRef.current;
    const url = timeline.stems[source];
    if (!audio || !url) return;
    const t = audio.currentTime;
    const wasPlaying = !audio.paused;
    audio.src = url;
    audio.currentTime = t;
    if (wasPlaying) void audio.play().catch(() => setPlaying(false));
  }, [source, timeline.stems]);

  // WaveSurfer yoʻlakchalari (precomputed peaks — audio yuklab olinmaydi)
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !duration) return;
    const created: WaveSurfer[] = [];
    for (const track of TRACKS) {
      const el = containers.current[track.key];
      const peaks = timeline.peaks?.[track.key];
      if (!el || !peaks?.length) continue;
      created.push(WaveSurfer.create({
        container: el, height: 44, media: audio, peaks: [peaks], duration, normalize: true,
        waveColor: track.color, progressColor: track.color + "cc", cursorColor: "#f8fafc", cursorWidth: 1,
        barWidth: 2, barGap: 1, barRadius: 2, minPxPerSec: zoom, hideScrollbar: true, autoScroll: true,
        autoCenter: false, dragToSeek: true,
      }));
    }
    // Segmentlar yoʻlakchasi: boʻsh toʻlqin + regionlar
    if (segLane.current) {
      const flat = new Array(Math.max(2, Math.ceil(duration))).fill(0);
      const ws = WaveSurfer.create({
        container: segLane.current, height: 56, media: audio, peaks: [flat], duration,
        waveColor: "transparent", progressColor: "transparent", cursorColor: "#f8fafc", cursorWidth: 1,
        minPxPerSec: zoom, hideScrollbar: false, autoScroll: true, interact: true,
      });
      const regions = ws.registerPlugin(RegionsPlugin.create());
      regionsRef.current = regions;
      // Regionlar faqat yoʻlakcha chizilgandan keyin qoʻshiladi (aks holda pozitsiya 0 boʻladi)
      ws.on("ready", () => setLaneReady((n) => n + 1));
      created.push(ws);
    }
    instances.current = created;

    // Gorizontal scroll sinxronizatsiyasi
    const wrappers = created.map((w) => w.getWrapper().parentElement as HTMLElement | null);
    const onScroll = (e: Event) => {
      const left = (e.target as HTMLElement).scrollLeft;
      wrappers.forEach((w) => w && w !== e.target && Math.abs(w.scrollLeft - left) > 1 && (w.scrollLeft = left));
    };
    wrappers.forEach((w) => w?.addEventListener("scroll", onScroll));

    const onTime = () => setTime(audio.currentTime);
    const onPlay = () => { setPlaying(true); void videoRef?.current?.play().catch(() => {}); };
    const onPause = () => { setPlaying(false); videoRef?.current?.pause(); };
    const onSeek = () => { if (videoRef?.current) videoRef.current.currentTime = audio.currentTime; };
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("seeked", onSeek);
    return () => {
      wrappers.forEach((w) => w?.removeEventListener("scroll", onScroll));
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("seeked", onSeek);
      created.forEach((w) => w.destroy());
      regionsRef.current = null;
    };
    // zoom alohida effektda qoʻllanadi
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeline.peaks, duration]);

  // Video ↔ audio dreyf tuzatish
  useEffect(() => {
    const v = videoRef?.current;
    if (!v || !playing) return;
    const id = setInterval(() => {
      const a = audioRef.current;
      if (a && Math.abs(v.currentTime - a.currentTime) > 0.15) v.currentTime = a.currentTime;
    }, 500);
    return () => clearInterval(id);
  }, [playing, videoRef]);

  useEffect(() => {
    instances.current.forEach((w) => {
      try { w.zoom(zoom); } catch { /* hali chizilmagan */ }
    });
  }, [zoom]);

  // Segment regionlari
  useEffect(() => {
    const regions = regionsRef.current;
    if (!regions || !laneReady) return;
    regions.clearRegions();
    for (const s of timeline.segments) {
      const sp = timeline.speakers.find((x) => x.id === s.speaker_id);
      const color = s.speaker_id ? speakerColor[s.speaker_id] : "#64748b";
      // WaveSurfer Shadow DOM ichida chiziladi — Tailwind klasslari ishlamaydi, inline uslub
      const label = document.createElement("div");
      Object.assign(label.style, {
        padding: "4px 6px 0", fontSize: "11px", fontWeight: "600", lineHeight: "1.3", color: "rgba(255,255,255,.95)",
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontFamily: "Plus Jakarta Sans, sans-serif",
        borderLeft: `2px solid ${color}`, height: "100%", boxSizing: "border-box",
      });
      label.textContent = `${sp?.display_name ?? "?"}: ${s.translated_text_uz ?? s.original_text}`;
      regions.addRegion({
        id: s.id, start: Number(s.start_time), end: Number(s.end_time), drag: true, resize: true, minLength: 0.2,
        color: `${color}${s.id === selectedId ? "88" : "40"}`, content: label,
      });
    }
    const onUpdate = (r: Region) => onRetime(r.id, Math.round(r.start * 1000) / 1000, Math.round(r.end * 1000) / 1000);
    const onClick = (r: Region, e: MouseEvent) => { e.stopPropagation(); onSelect(r.id); };
    const un1 = regions.on("region-updated", onUpdate);
    const un2 = regions.on("region-clicked", onClick);
    return () => { un1(); un2(); };
  }, [timeline.segments, timeline.speakers, selectedId, speakerColor, onRetime, onSelect, laneReady]);

  // Tashqaridan kursorni oʻtkazish (segment roʻyxatidan)
  useEffect(() => {
    if (seekTo && audioRef.current) audioRef.current.currentTime = seekTo.t;
  }, [seekTo]);

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) void a.play().catch(() => setPlaying(false));
    else a.pause();
  };

  // Probel — ijro/pauza (matn maydonlaridan tashqarida)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (e.code === "Space" && !["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag)) {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
        <button type="button" onClick={toggle} className="btn-primary size-11 rounded-full p-0" aria-label={playing ? "Pauza" : "Ijro"}>
          {playing ? <Pause className="size-5" /> : <Play className="size-5 translate-x-px" />}
        </button>
        <button type="button" className="btn-ghost size-10 p-0" aria-label="Boshiga"
                onClick={() => audioRef.current && (audioRef.current.currentTime = 0)}>
          <SkipBack className="size-4" />
        </button>
        <span className="font-mono text-sm tabular-nums">
          {formatTime(time)} <span className="text-muted">/ {formatTime(duration, false)}</span>
        </span>
        <label className="sr-only" htmlFor="mt-source">Tinglash manbasi</label>
        <select id="mt-source" className="input w-auto min-w-48 cursor-pointer py-1.5" value={source}
                onChange={(e) => setSource(e.target.value as SourceKey)}>
          {SOURCES.map((s) => (
            <option key={s.key} value={s.key} disabled={!timeline.stems[s.key]}>{s.label}</option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-2 text-muted">
          <ZoomIn aria-hidden className="size-4" />
          <label htmlFor="mt-zoom" className="sr-only">Masshtab</label>
          <input id="mt-zoom" type="range" min={10} max={300} value={zoom} onChange={(e) => setZoom(Number(e.target.value))}
                 className="w-32 cursor-pointer accent-[#818cf8]" />
        </div>
      </div>

      <div className="grid grid-cols-[72px_1fr]">
        {TRACKS.map((t) => (
          <TrackRow key={t.key} label={t.label} color={t.color}
                    empty={!timeline.peaks?.[t.key]?.length}
                    setRef={(el) => (containers.current[t.key] = el)} />
        ))}
        <div className="flex items-center border-t border-line px-3 text-xs font-semibold text-muted">Segment</div>
        <div className="border-t border-line bg-bg/40" ref={segLane} />
      </div>
      <SpeakerLegend speakers={timeline.speakers} colors={speakerColor} />
    </div>
  );
}

function TrackRow({ label, color, empty, setRef }: {
  label: string; color: string; empty: boolean; setRef: (el: HTMLDivElement | null) => void;
}) {
  return (
    <>
      <div className="flex items-center gap-2 border-t border-line px-3 text-xs font-semibold text-muted first:border-t-0">
        <span aria-hidden className="size-2 rounded-full" style={{ background: color }} />
        {label}
      </div>
      <div className="relative min-h-11 border-t border-line">
        <div ref={setRef} />
        {empty && <div className="absolute inset-0 grid place-items-center text-xs text-muted">Hali tayyor emas</div>}
      </div>
    </>
  );
}

function SpeakerLegend({ speakers, colors }: { speakers: Speaker[]; colors: Record<string, string> }) {
  if (!speakers.length) return null;
  return (
    <div className="flex flex-wrap gap-3 border-t border-line px-4 py-2.5 text-xs text-muted">
      {speakers.map((s) => (
        <span key={s.id} className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-sm" style={{ background: colors[s.id] }} />
          {s.display_name ?? s.speaker_tag}
        </span>
      ))}
      <span className="ml-auto hidden sm:inline">Probel — ijro/pauza · regionni surib vaqtni oʻzgartiring</span>
    </div>
  );
}

export type { Segment };
