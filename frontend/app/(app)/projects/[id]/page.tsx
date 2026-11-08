"use client";

import { ArrowLeft, Download, FileText, Play, RefreshCw, RotateCcw, Trash2, Users, Wand2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useMemo, useRef, useState } from "react";
import { MultiTrack } from "@/components/timeline/MultiTrack";
import { SegmentRow } from "@/components/timeline/SegmentRow";
import { SpeakerPanel } from "@/components/timeline/SpeakerPanel";
import { EmptyState, Modal, ProgressBar, Spinner, StatusBadge, useToast } from "@/components/ui";
import { useUser } from "@/components/UserContext";
import { api } from "@/lib/api";
import { MODE_LABEL, SPEAKER_COLORS, usd } from "@/lib/format";
import { useApi, usePipelineEvents } from "@/lib/hooks";
import type { PipelineEvent, ProjectExport, Segment, Timeline, Voice } from "@/lib/types";

const STAGE_LABEL: Record<string, string> = {
  STEM_SEPARATION: "Ovoz ajratilmoqda", TRANSCRIBING: "Transkripsiya", TRANSLATING: "Tarjima", TTS: "Ovozlashtirish",
  ALIGNING: "Vaqt moslash", MASTERING: "Mastering", CLONING: "Ovoz klonlash", RERENDER: "Qayta render",
  AWAITING_REVIEW: "Tekshiruv kutilmoqda",
};
const IDLE = new Set(["TRANSLATED", "READY_FOR_EXPORT", "FAILED"]);

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { refresh: refreshUser } = useUser();
  const tl = useApi<Timeline>(`/projects/${id}/timeline`);
  const { reload, setData } = tl;
  const voices = useApi<Voice[]>("/voices");
  const [selected, setSelected] = useState<string | null>(null);
  const [seek, setSeek] = useState<{ t: number; nonce: number } | null>(null);
  const [live, setLive] = useState<{ stage?: string; message?: string; progress?: number; spent?: number }>({});
  const [exportData, setExportData] = useState<ProjectExport | null>(null);
  const [tab, setTab] = useState<"segments" | "speakers">("segments");
  const [filter, setFilter] = useState("");
  const [acting, setActing] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleReload = useCallback(() => {
    if (reloadTimer.current) clearTimeout(reloadTimer.current);
    reloadTimer.current = setTimeout(() => void reload(), 600);
  }, [reload]);

  const connected = usePipelineEvents("projects", id, (e: PipelineEvent) => {
    if (e.type === "progress" || e.type === "segment" || e.type === "status") {
      setLive((l) => ({
        stage: e.stage ?? l.stage, message: e.message ?? l.message,
        progress: e.progress ?? l.progress,
        spent: typeof e.data?.spent_usd === "number" ? (e.data.spent_usd as number) : l.spent,
      }));
    }
    if (e.type === "status" || e.type === "error") {
      scheduleReload();
      if (e.status === "READY_FOR_EXPORT") { toast("Dublyaj tayyor!", "ok"); void refreshUser(); }
      if (e.type === "error") toast(e.message ?? "Xato yuz berdi", "danger");
    }
    if (e.type === "cost" && typeof e.data?.charged_usd === "number") void refreshUser();
  });

  const t = tl.data;
  const speakerColor = useMemo(() => {
    const m: Record<string, string> = {};
    t?.speakers.forEach((s, i) => (m[s.id] = SPEAKER_COLORS[i % SPEAKER_COLORS.length]));
    return m;
  }, [t?.speakers]);

  const updateSegment = useCallback((seg: Segment) => {
    setData((cur) => cur && {
      ...cur,
      segments: cur.segments.map((s) => (s.id === seg.id ? seg : s)),
      pending_changes: cur.pending_changes + (seg.status !== "ALIGNED" ? 1 : 0),
    });
  }, [setData]);

  const saveSegment = useCallback(async (segId: string, patch: Record<string, unknown>) => {
    try {
      updateSegment(await api<Segment>(`/projects/${id}/segments/${segId}`, { method: "PATCH", json: patch }));
    } catch (e) {
      toast((e as Error).message, "danger");
    }
  }, [id, toast, updateSegment]);

  const retime = useCallback((segId: string, start: number, end: number) => {
    void saveSegment(segId, { start_time: start, end_time: end });
  }, [saveSegment]);

  const retranslate = useCallback(async (segId: string) => {
    try {
      const r = await api<{ message: string }>(`/projects/${id}/segments/${segId}/retranslate`, { method: "POST" });
      toast(r.message, "info");
      scheduleReload();
    } catch (e) { toast((e as Error).message, "danger"); }
  }, [id, toast, scheduleReload]);

  async function action(path: string, okMsg?: string) {
    setActing(true);
    try {
      const r = await api<{ message: string }>(`/projects/${id}/${path}`, { method: "POST" });
      toast(okMsg ?? r.message, "info");
      scheduleReload();
    } catch (e) { toast((e as Error).message, "danger"); } finally { setActing(false); }
  }

  async function openExport() {
    try { setExportData(await api<ProjectExport>(`/projects/${id}/export`)); } catch (e) { toast((e as Error).message, "danger"); }
  }

  async function remove() {
    if (!confirm("Loyihani butunlay oʻchirasizmi?")) return;
    await api(`/projects/${id}`, { method: "DELETE" });
    router.replace("/dashboard");
  }

  if (tl.loading && !t) return <div className="grid h-64 place-items-center"><Spinner className="size-6" /></div>;
  if (tl.error || !t) return <EmptyState icon={<FileText className="size-7" />} title="Loyiha topilmadi">{tl.error}</EmptyState>;

  const p = t.project;
  const idle = IDLE.has(p.status);
  const progress = live.progress ?? Number(p.progress);
  const segments = filter
    ? t.segments.filter((s) => `${s.original_text} ${s.translated_text_uz ?? ""}`.toLowerCase().includes(filter.toLowerCase()))
    : t.segments;

  return (
    <div className="mx-auto max-w-[1600px] space-y-5">
      {/* Sarlavha */}
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <Link href="/dashboard" className="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ArrowLeft aria-hidden className="size-4" /> Loyihalar
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="truncate text-2xl font-bold">{p.title}</h1>
            <StatusBadge status={p.status} />
            <span className="text-xs text-muted" title={connected ? "Real vaqt ulanishi faol" : "Ulanmoqda…"}>
              <span aria-hidden className={`mr-1 inline-block size-2 rounded-full ${connected ? "bg-ok" : "bg-muted"}`} />
              {connected ? "Jonli" : "Oflayn"}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted">
            {p.source_language.toUpperCase()} → UZ · {MODE_LABEL[p.tts_mode]}
            {p.estimated_cost_usd ? ` · Narx: ${usd(p.estimated_cost_usd, 4)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {p.status === "FAILED" && (
            <button type="button" className="btn-secondary" disabled={acting} onClick={() => action("retry")}>
              <RotateCcw aria-hidden className="size-4" /> Qayta urinish
            </button>
          )}
          {p.status === "TRANSLATED" && p.review_before_tts && (
            <button type="button" className="btn-primary" disabled={acting} onClick={() => action("start-tts")}>
              <Play aria-hidden className="size-4" /> Dublyajni boshlash
            </button>
          )}
          <button type="button" className={t.pending_changes ? "btn-primary" : "btn-secondary"}
                  disabled={acting || !idle || !t.pending_changes} onClick={() => action("rerender")}>
            <RefreshCw aria-hidden className="size-4" /> Qayta render{t.pending_changes ? ` (${t.pending_changes})` : ""}
          </button>
          <button type="button" className="btn-secondary" disabled={p.status !== "READY_FOR_EXPORT"} onClick={openExport}>
            <Download aria-hidden className="size-4" /> Eksport
          </button>
          <button type="button" className="btn-ghost px-3" aria-label="Loyihani oʻchirish" onClick={remove}>
            <Trash2 className="size-4" />
          </button>
        </div>
      </div>

      {/* Jarayon */}
      {!idle && (
        <div className="card space-y-2 p-4">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="flex items-center gap-2 font-semibold"><Spinner /> {STAGE_LABEL[live.stage ?? ""] ?? "Qayta ishlanmoqda"}</span>
            <span className="tabular-nums text-muted">{progress.toFixed(0)}%</span>
          </div>
          <ProgressBar value={progress} />
          <p className="text-xs text-muted">
            {live.message ?? "Navbatda…"}{live.spent !== undefined ? ` · Sarf: ${usd(live.spent, 4)}` : ""}
          </p>
        </div>
      )}
      {p.status === "FAILED" && p.error_message && (
        <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{p.error_message}</p>
      )}

      {/* Video + vaqt jadvali */}
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-5">
          {t.duration ? (
            <MultiTrack timeline={t} selectedId={selected} onSelect={setSelected} onRetime={retime} seekTo={seek} videoRef={videoRef} />
          ) : (
            <EmptyState icon={<Wand2 className="size-7" />} title="Vaqt jadvali tayyorlanmoqda">
              Ovoz ajratilgandan soʻng toʻlqin shakllari shu yerda paydo boʻladi.
            </EmptyState>
          )}
        </div>
        <div className="card mx-auto w-full max-w-2xl overflow-hidden bg-black xl:max-w-none">
          {t.video_url ? (
            <video ref={videoRef} src={t.video_url} muted playsInline className="aspect-video w-full" preload="metadata">
              <track kind="subtitles" />
            </video>
          ) : <div className="aspect-video" />}
          <p className="border-t border-line bg-surface px-4 py-2 text-xs text-muted">
            Video ovozsiz; tinglash manbasini vaqt jadvalidan tanlang.
          </p>
        </div>
      </div>

      {/* Segmentlar / spikerlar */}
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3" role="tablist">
          {(["segments", "speakers"] as const).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                    className={`btn min-h-9 ${tab === k ? "bg-surface-2 text-fg" : "text-muted hover:text-fg"}`}>
              {k === "segments" ? <><FileText aria-hidden className="size-4" /> Ssenariy ({t.segments.length})</>
                : <><Users aria-hidden className="size-4" /> Spikerlar ({t.speakers.length})</>}
            </button>
          ))}
          {tab === "segments" && (
            <>
              <label htmlFor="seg-filter" className="sr-only">Qidirish</label>
              <input id="seg-filter" type="search" placeholder="Matn boʻyicha qidirish…" value={filter}
                     onChange={(e) => setFilter(e.target.value)} className="input ml-auto w-full sm:w-72" />
            </>
          )}
        </div>
        {tab === "segments" ? (
          segments.length ? (
            <div className="max-h-[70vh] overflow-y-auto">
              {segments.map((s) => (
                <SegmentRow key={s.id} segment={s} speakers={t.speakers}
                            color={s.speaker_id ? speakerColor[s.speaker_id] : "#64748b"}
                            selected={selected === s.id} onSelect={setSelected} onSave={saveSegment}
                            onRetranslate={retranslate}
                            onSeek={(time) => setSeek({ t: time, nonce: Date.now() })} />
              ))}
            </div>
          ) : <p className="p-6 text-sm text-muted">Segmentlar hali yoʻq.</p>
        ) : (
          <div className="p-4">
            <SpeakerPanel speakers={t.speakers} voices={voices.data ?? []}
                          cloningEnabled={(voices.data ?? []).some((v) => v.provider === "elevenlabs")}
                          onPatch={async (spId, patch) => {
                            try {
                              await api(`/projects/${id}/speakers/${spId}`, { method: "PATCH", json: patch });
                              await tl.reload();
                              if ("voice_profile_id" in patch) toast("Ovoz almashtirildi — «Qayta render» tugmasini bosing", "info");
                            } catch (e) { toast((e as Error).message, "danger"); }
                          }}
                          onClone={async (spId) => {
                            if (!confirm("Ushbu ovozdan foydalanish huquqingiz borligini tasdiqlaysizmi?")) return;
                            try {
                              const r = await api<{ message: string }>(`/projects/${id}/speakers/${spId}/clone`, { method: "POST" });
                              toast(r.message, "info");
                            } catch (e) { toast((e as Error).message, "danger"); }
                          }} />
          </div>
        )}
      </div>

      <Modal open={exportData !== null} onClose={() => setExportData(null)} title="Eksport">
        {exportData && (
          <ul className="space-y-2">
            {([
              ["video_mp4", "Dublyaj qilingan video (MP4, 2 audio yoʻlakcha + subtitr)"],
              ["dubbed_audio", "Yakuniy audio (M4A)"],
              ["dialogue_only", "Faqat dublyaj dialogi (FLAC)"],
              ["subtitles_srt", "Subtitrlar (SRT)"],
              ["subtitles_vtt", "Subtitrlar (VTT)"],
            ] as const).map(([k, label]) => exportData[k] && (
              <li key={k}>
                <a href={exportData[k]!} className="btn-secondary w-full justify-between" download>
                  {label} <Download aria-hidden className="size-4" />
                </a>
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </div>
  );
}
