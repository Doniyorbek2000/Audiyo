"use client";

import {
  AlertCircle, ArrowLeft, BookOpen, Check, Download, Languages, Merge, Pause, Play, Plus, RotateCcw, Sparkles, Trash2, Users,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { EmptyState, Field, Modal, ProgressBar, Spinner, Stat, StatusBadge, useToast } from "@/components/ui";
import { useUser } from "@/components/UserContext";
import { VoiceSelect } from "@/components/VoiceSelect";
import { api } from "@/lib/api";
import { AGE_LABEL, EMOTION_LABEL, formatDuration, GENDER_LABEL, MODE_LABEL, usd } from "@/lib/format";
import { useApi, usePipelineEvents } from "@/lib/hooks";
import {
  EMOTIONS, type Block, type Book, type BookExport, type Chapter, type Character, type Estimate, type LexiconEntry,
  type PipelineEvent, type Voice,
} from "@/lib/types";

type Tab = "text" | "cast" | "lexicon" | "synth";
const EDITABLE = new Set(["ATTRIBUTED", "LEXICON_APPLIED", "READY_FOR_EXPORT", "FAILED"]);

// ====================================================================== bloklar
function BlockRow({ block, characters, editable, onPatch }: {
  block: Block; characters: Character[]; editable: boolean;
  onPatch: (id: string, patch: Record<string, unknown>) => Promise<void>;
}) {
  const [text, setText] = useState(block.source_text);
  const [saving, setSaving] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(() => setText(block.source_text), [block.source_text]);
  useEffect(() => () => audio.current?.pause(), []);

  const dirty = text.trim() !== block.source_text;
  const isHeading = block.block_type === "HEADING";
  const speakerValue = block.block_type === "DIALOGUE" ? block.character_id ?? "" : "__narrator__";

  return (
    <div className={`grid gap-3 border-b border-line p-4 md:grid-cols-[180px_1fr] ${
      block.needs_review ? "bg-warn/5" : ""}`}>
      <div className="flex flex-row flex-wrap items-center gap-2 md:flex-col md:items-start">
        <label className="sr-only" htmlFor={`who-${block.id}`}>Kim oʻqiydi</label>
        <select id={`who-${block.id}`} disabled={!editable || isHeading} value={speakerValue}
                onChange={(e) => onPatch(block.id, e.target.value === "__narrator__"
                  ? { clear_character: true, block_type: "NARRATION" } : { character_id: e.target.value })}
                className="w-full cursor-pointer rounded-lg border border-field-edge bg-bg px-2 py-1 text-xs font-semibold">
          <option value="__narrator__">{isHeading ? "Sarlavha (hikoyachi)" : "Hikoyachi"}</option>
          {block.block_type === "DIALOGUE" && !block.character_id && <option value="">Nomaʼlum spiker</option>}
          {characters.map((c) => <option key={c.id} value={c.id}>{c.canonical_name}</option>)}
        </select>
        <label className="sr-only" htmlFor={`emo-${block.id}`}>Emotsiya</label>
        <select id={`emo-${block.id}`} disabled={!editable} value={block.emotion_tag}
                onChange={(e) => onPatch(block.id, { emotion_tag: e.target.value })}
                className="w-full cursor-pointer rounded-lg border border-field-edge bg-bg px-2 py-1 text-xs">
          {EMOTIONS.map((em) => <option key={em} value={em}>{EMOTION_LABEL[em]}</option>)}
        </select>
        <div className="flex items-center gap-1 text-xs text-muted">
          <label htmlFor={`pause-${block.id}`}>Pauza</label>
          <input id={`pause-${block.id}`} type="number" min={0} max={10000} step={50} disabled={!editable}
                 defaultValue={block.pause_after_ms}
                 onBlur={(e) => Number(e.target.value) !== block.pause_after_ms && onPatch(block.id, { pause_after_ms: Number(e.target.value) })}
                 className="w-20 rounded-lg border border-field-edge bg-bg px-2 py-1 tabular-nums" /> ms
        </div>
        <StatusBadge status={block.status} />
      </div>

      <div className="min-w-0 space-y-2">
        {block.needs_review && (
          <p className="flex items-center gap-1.5 text-xs font-semibold text-warn">
            <AlertCircle aria-hidden className="size-3.5" /> Spikerni tekshiring
            {block.attribution_confidence ? ` (ishonch ${Math.round(Number(block.attribution_confidence) * 100)}%)` : ""}
            <button type="button" className="ml-2 cursor-pointer text-info hover:underline"
                    onClick={() => onPatch(block.id, { needs_review: false })}>Toʻgʻri</button>
          </p>
        )}
        <label className="sr-only" htmlFor={`txt-${block.id}`}>Matn</label>
        <textarea id={`txt-${block.id}`} value={text} disabled={!editable} onChange={(e) => setText(e.target.value)}
                  rows={Math.min(8, Math.max(2, Math.ceil(text.length / 110)))}
                  className={`input resize-y leading-relaxed ${isHeading ? "font-bold" : ""} ${block.block_type === "DIALOGUE" ? "border-l-4 border-l-info" : ""}`} />
        {block.tts_text && block.tts_text !== block.source_text && (
          <p className="text-xs text-muted"><span className="font-semibold">TTS uchun:</span> {block.tts_text}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className={text.length > 2000 ? "text-warn" : ""}>{text.length}/2000{text.length > 2000 ? ", saqlanganda boʻlinadi" : ""}</span>
          {block.duration_ms ? <span>{formatDuration(block.duration_ms)}</span> : null}
          <div className="ml-auto flex gap-1.5">
            {block.audio_url && (
              <button type="button" className="btn-ghost min-h-9 px-2.5 text-xs" onClick={() => {
                if (playing) { audio.current?.pause(); setPlaying(false); return; }
                audio.current = new Audio(block.audio_url!);
                audio.current.onended = () => setPlaying(false);
                void audio.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
              }}>{playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} Tinglash</button>
            )}
            {dirty && editable && (
              <>
                <button type="button" className="btn-ghost min-h-9 px-2.5 text-xs" onClick={() => setText(block.source_text)}>
                  <RotateCcw className="size-3.5" /> Bekor
                </button>
                <button type="button" className="btn-primary min-h-9 px-3 text-xs" disabled={saving}
                        onClick={async () => { setSaving(true); try { await onPatch(block.id, { source_text: text.trim() }); } finally { setSaving(false); } }}>
                  {saving ? <Spinner className="size-3.5" /> : <Check className="size-3.5" />} Saqlash
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function TextTab({ bookId, chapters, characters, editable }: {
  bookId: string; chapters: Chapter[]; characters: Character[]; editable: boolean;
}) {
  const toast = useToast();
  const [chapter, setChapter] = useState<number | "review">(chapters[0]?.chapter_index ?? 1);
  const [page, setPage] = useState(0);
  const limit = 100;
  const query = chapter === "review" ? "needs_review=true" : `chapter=${chapter}`;
  const blocks = useApi<{ items: Block[]; total: number }>(`/books/${bookId}/blocks?${query}&offset=${page * limit}&limit=${limit}`);
  const { setData } = blocks;

  const patch = useCallback(async (blockId: string, body: Record<string, unknown>) => {
    try {
      const updated = await api<Block[]>(`/books/${bookId}/blocks/${blockId}`, { method: "PATCH", json: body });
      if (updated.length > 1) { void blocks.reload(); toast(`Blok ${updated.length} qismga boʻlindi`, "info"); return; }
      setData((cur) => cur && { ...cur, items: cur.items.map((b) => (b.id === blockId ? updated[0] : b)) });
    } catch (e) { toast((e as Error).message, "danger"); }
  }, [bookId, setData, toast, blocks]);

  const reviewTotal = chapters.reduce((s, c) => s + c.review_count, 0);
  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
      <nav aria-label="Boblar" className="card max-h-[70vh] overflow-y-auto p-2">
        {reviewTotal > 0 && (
          <button type="button" onClick={() => { setChapter("review"); setPage(0); }}
                  className={`flex w-full cursor-pointer items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm transition-colors duration-200 ${
                    chapter === "review" ? "bg-surface-2" : "hover:bg-elevated"}`}>
            <span className="flex items-center gap-2 font-semibold text-warn"><AlertCircle aria-hidden className="size-4" /> Tekshiruv</span>
            <span className="rounded-full bg-warn/15 px-2 text-xs font-bold text-warn">{reviewTotal}</span>
          </button>
        )}
        {chapters.map((c) => (
          <button key={c.id} type="button" onClick={() => { setChapter(c.chapter_index); setPage(0); }}
                  className={`w-full cursor-pointer rounded-xl px-3 py-2.5 text-left text-sm transition-colors duration-200 ${
                    chapter === c.chapter_index ? "bg-surface-2" : "hover:bg-elevated"}`}>
            <span className="line-clamp-1 font-medium">{c.title ?? (c.chapter_index === 1 ? "Kirish" : `${c.chapter_index}-qism`)}</span>
            <span className="text-xs text-muted">
              {c.block_count} blok{c.synthesized_count ? `, ${c.synthesized_count} sintez` : ""}{c.review_count ? `, ${c.review_count} tekshiruv` : ""}
            </span>
          </button>
        ))}
      </nav>
      <div className="card min-w-0 overflow-hidden">
        {blocks.loading && !blocks.data ? <div className="p-6"><Spinner /></div> : (
          <>
            <div className="max-h-[70vh] overflow-y-auto">
              {blocks.data?.items.map((b) => (
                <BlockRow key={b.id} block={b} characters={characters} editable={editable} onPatch={patch} />
              ))}
              {!blocks.data?.items.length && <p className="p-6 text-sm text-muted">Bloklar yoʻq.</p>}
            </div>
            {(blocks.data?.total ?? 0) > limit && (
              <div className="flex items-center justify-between border-t border-line px-4 py-2 text-sm">
                <button type="button" className="btn-ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Oldingi</button>
                <span className="text-muted">{page * limit + 1} dan {Math.min((page + 1) * limit, blocks.data!.total)} / {blocks.data!.total}</span>
                <button type="button" className="btn-ghost" disabled={(page + 1) * limit >= blocks.data!.total} onClick={() => setPage((p) => p + 1)}>Keyingi</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ====================================================================== personajlar
function CastTab({ bookId, characters, voices, editable, reload }: {
  bookId: string; characters: Character[]; voices: Voice[]; editable: boolean; reload: () => Promise<void>;
}) {
  const toast = useToast();
  const [merge, setMerge] = useState<Character | null>(null);
  const [adding, setAdding] = useState(false);

  async function patch(id: string, body: Record<string, unknown>) {
    try {
      await api(`/books/${bookId}/characters/${id}`, { method: "PATCH", json: body });
      await reload();
    } catch (e) { toast((e as Error).message, "danger"); }
  }

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      await api(`/books/${bookId}/characters`, { method: "POST", json: Object.fromEntries(new FormData(e.currentTarget)) });
      setAdding(false);
      await reload();
    } catch (err) { toast((err as Error).message, "danger"); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">Har personaj butun kitob davomida bir xil ovozda gapiradi. Dialog ulushi 5% va undan koʻp boʻlganlar asosiy (1-daraja).</p>
        <button type="button" className="btn-secondary shrink-0" disabled={!editable} onClick={() => setAdding(true)}>
          <Plus aria-hidden className="size-4" /> Personaj
        </button>
      </div>
      {characters.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {characters.map((c) => (
            <div key={c.id} className="card space-y-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate font-semibold">{c.canonical_name}</h3>
                  <p className="text-xs text-muted">
                    Dialog ulushi {(Number(c.dialogue_share) * 100).toFixed(1)}%
                    {c.aliases.length ? `. Taxalluslar: ${c.aliases.join(", ")}` : ""}
                  </p>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${c.tts_tier === "TIER_1" ? "bg-accent/15 text-accent" : "bg-info/15 text-info"}`}>
                  {c.tts_tier === "TIER_1" ? "Asosiy" : "Ikkilamchi"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="label" htmlFor={`g-${c.id}`}>Jinsi</label>
                  <select id={`g-${c.id}`} className="input cursor-pointer" value={c.gender} disabled={!editable}
                          onChange={(e) => patch(c.id, { gender: e.target.value })}>
                    {Object.entries(GENDER_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor={`a-${c.id}`}>Yoshi</label>
                  <select id={`a-${c.id}`} className="input cursor-pointer" value={c.age_group} disabled={!editable}
                          onChange={(e) => patch(c.id, { age_group: e.target.value })}>
                    {Object.entries(AGE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="label" htmlFor={`v-${c.id}`}>Ovoz</label>
                <VoiceSelect id={`v-${c.id}`} voices={voices} value={c.voice_profile_id} disabled={!editable}
                             onChange={(v) => patch(c.id, { voice_profile_id: v })} />
              </div>
              <button type="button" className="btn-ghost min-h-9 w-full whitespace-nowrap text-xs" disabled={!editable || characters.length < 2}
                      onClick={() => setMerge(c)}>
                <Merge aria-hidden className="size-3.5" /> Boshqa personaj bilan birlashtirish
              </button>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState icon={<Users className="size-7" />} title="Personajlar topilmadi">
          Dialoglar hikoyachi ovozida oʻqiladi. Kerak boʻlsa, personajni qoʻlda qoʻshing.
        </EmptyState>
      )}

      <Modal open={merge !== null} onClose={() => setMerge(null)} title={`«${merge?.canonical_name}» ni birlashtirish`}>
        <p className="mb-4 text-sm text-muted">Barcha replikalari tanlangan personajga oʻtadi, ismi esa taxallus sifatida saqlanadi.</p>
        <div className="space-y-2">
          {characters.filter((c) => c.id !== merge?.id).map((c) => (
            <button key={c.id} type="button" className="btn-secondary w-full justify-start"
                    onClick={async () => { await patch(merge!.id, { merge_into_id: c.id }); setMerge(null); }}>
              {c.canonical_name}
            </button>
          ))}
        </div>
      </Modal>
      <Modal open={adding} onClose={() => setAdding(false)} title="Yangi personaj">
        <form onSubmit={add} className="space-y-4">
          <Field label="Ism" htmlFor="nc-name"><input id="nc-name" name="canonical_name" required className="input" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Jinsi" htmlFor="nc-g">
              <select id="nc-g" name="gender" className="input cursor-pointer">
                {Object.entries(GENDER_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
            <Field label="Yoshi" htmlFor="nc-a">
              <select id="nc-a" name="age_group" className="input cursor-pointer" defaultValue="ADULT">
                {Object.entries(AGE_LABEL).filter(([k]) => k !== "UNKNOWN").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
          </div>
          <button type="submit" className="btn-primary w-full">Qoʻshish</button>
        </form>
      </Modal>
    </div>
  );
}

// ====================================================================== leksikon
function LexiconTab({ bookId, editable }: { bookId: string; editable: boolean }) {
  const toast = useToast();
  const lex = useApi<LexiconEntry[]>(`/books/${bookId}/lexicon?include_global=true`);
  const [filter, setFilter] = useState("");

  async function run(fn: () => Promise<unknown>) {
    try { await fn(); await lex.reload(); } catch (e) { toast((e as Error).message, "danger"); }
  }

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    await run(() => api(`/books/${bookId}/lexicon`, { method: "POST", json: Object.fromEntries(new FormData(form)) }));
    form.reset();
  }

  const items = (lex.data ?? []).filter((x) => !filter || x.term.toLowerCase().includes(filter.toLowerCase()));
  const pending = items.filter((x) => x.source === "AUTO_SUGGESTED" && !x.approved).length;
  const SRC: Record<string, string> = { USER: "Siz", GLOBAL: "Umumiy", AUTO_SUGGESTED: "Avtomatik" };

  return (
    <div className="space-y-4">
      <form onSubmit={add} className="card grid gap-3 p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Field label="Atama (asl yozuv)" htmlFor="lx-term"><input id="lx-term" name="term" required className="input" placeholder="Shakespeare" disabled={!editable} /></Field>
        <Field label="Oʻzbekcha talaffuz" htmlFor="lx-ph"><input id="lx-ph" name="phonetic_uz" required className="input" placeholder="Shekspir" disabled={!editable} /></Field>
        <button type="submit" className="btn-primary" disabled={!editable}><Plus aria-hidden className="size-4" /> Qoʻshish</button>
      </form>
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <p className="text-sm text-muted">{pending ? `${pending} ta avtomatik taklif tasdiqlanmagan (lekin qoʻllanadi).` : "Qoʻshimchalar saqlanadi: Shakespeare'ning → Shekspirning."}</p>
          <label htmlFor="lx-filter" className="sr-only">Qidirish</label>
          <input id="lx-filter" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Qidirish…" className="input ml-auto w-56" />
        </div>
        <div className="max-h-[60vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-left text-sm text-muted">
              <tr><th className="px-4 py-2">Atama</th><th className="px-4 py-2">Talaffuz</th><th className="px-4 py-2">Manba</th><th className="px-4 py-2 text-right">Amallar</th></tr>
            </thead>
            <tbody>
              {items.map((x) => (
                <tr key={x.id} className="border-t border-line">
                  <td className="px-4 py-2 font-medium">{x.term}</td>
                  <td className="px-4 py-2">
                    {x.book_id && editable ? (
                      <input aria-label={`${x.term} talaffuzi`} defaultValue={x.phonetic_uz}
                             onBlur={(e) => e.target.value !== x.phonetic_uz && run(() => api(`/books/${bookId}/lexicon/${x.id}`, { method: "PATCH", json: { phonetic_uz: e.target.value } }))}
                             className="w-full rounded-lg border border-transparent bg-transparent px-2 py-1 hover:border-field-edge focus:border-info focus:outline-none" />
                    ) : <span className="px-2">{x.phonetic_uz}</span>}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <span className={x.source === "AUTO_SUGGESTED" && !x.approved ? "text-warn" : "text-muted"}>{SRC[x.source]}</span>
                  </td>
                  <td className="px-4 py-2">
                    {x.book_id && editable && (
                      <div className="flex justify-end gap-1">
                        {!x.approved && (
                          <button type="button" aria-label="Tasdiqlash" className="btn-ghost min-h-9 px-2"
                                  onClick={() => run(() => api(`/books/${bookId}/lexicon/${x.id}`, { method: "PATCH", json: { approved: true } }))}>
                            <Check className="size-4 text-ok" />
                          </button>
                        )}
                        <button type="button" aria-label="Oʻchirish" className="btn-ghost min-h-9 px-2"
                                onClick={() => run(() => api(`/books/${bookId}/lexicon/${x.id}`, { method: "DELETE" }))}>
                          <Trash2 className="size-4" />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ====================================================================== sintez va eksport
function SynthTab({ book, voices, onChanged }: { book: Book; voices: Voice[]; onChanged: () => Promise<void> }) {
  const toast = useToast();
  const { refresh } = useUser();
  const canEstimate = EDITABLE.has(book.status) || book.status === "TTS_DISPATCHED" || book.status === "STITCHED";
  const est = useApi<Estimate>(canEstimate ? `/books/${book.id}/estimate` : null);
  const exp = useApi<BookExport>(book.status === "READY_FOR_EXPORT" ? `/books/${book.id}/export` : null);
  const [busy, setBusy] = useState(false);

  async function patchBook(body: Record<string, unknown>) {
    try {
      await api(`/books/${book.id}`, { method: "PATCH", json: body });
      await onChanged();
      await est.reload();
    } catch (e) { toast((e as Error).message, "danger"); }
  }

  async function synthesize() {
    setBusy(true);
    try {
      const r = await api<{ message: string }>(`/books/${book.id}/synthesize`, { method: "POST" });
      toast(r.message, "info");
      await onChanged();
      await refresh();
    } catch (e) { toast((e as Error).message, "danger"); } finally { setBusy(false); }
  }

  const editable = EDITABLE.has(book.status);
  const pending = est.data ? est.data.total_chars > 0 : false;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-4 p-5">
          <h3 className="font-semibold">Ovoz sozlamalari</h3>
          <Field label="Hikoyachi ovozi" htmlFor="narrator" hint="Hikoya, sarlavhalar va nomaʼlum spikerlar shu ovozda oʻqiladi.">
            <VoiceSelect id="narrator" voices={voices} value={book.narrator_voice_profile_id} disabled={!editable}
                         onChange={(v) => patchBook({ narrator_voice_profile_id: v })} />
          </Field>
          <Field label="TTS rejimi" htmlFor="mode">
            <select id="mode" className="input cursor-pointer" value={book.tts_mode} disabled={!editable}
                    onChange={(e) => patchBook({ tts_mode: e.target.value })}>
              {Object.entries(MODE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
        </div>
        <div className="card space-y-4 p-5">
          <h3 className="font-semibold">Narx</h3>
          {est.loading && !est.data ? <Spinner /> : est.data ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Sintez qilinadi" value={est.data.total_chars.toLocaleString("uz")} sub="belgi" />
                <Stat label="Taxminiy narx" value={usd(est.data.charge_usd)} sub={`Balans: ${usd(est.data.balance_usd)}`} />
              </div>
              <p className="text-xs text-muted">
                {Object.entries(est.data.chars_by_provider).map(([p, n]) => `${p === "elevenlabs" ? "ElevenLabs" : "Gemini"}: ${n.toLocaleString("uz")} belgi`).join(", ") || "Hammasi sintez qilingan"}
              </p>
              {!est.data.sufficient && (
                <p role="alert" className="text-sm text-danger">Kredit yetarli emas. <Link href="/billing" className="underline">Balansni toʻldiring</Link>.</p>
              )}
              <button type="button" className="btn-primary w-full" onClick={synthesize}
                      disabled={busy || !est.data.sufficient || !pending || !["LEXICON_APPLIED", "READY_FOR_EXPORT", "FAILED"].includes(book.status)}>
                {busy ? <Spinner /> : <Sparkles aria-hidden className="size-4" />}
                {book.status === "READY_FOR_EXPORT" ? "Oʻzgarishlarni qayta sintez qilish" : "Audiokitobni yaratish"}
              </button>
            </>
          ) : <p className="text-sm text-muted">Narx tahlildan keyin hisoblanadi.</p>}
        </div>
      </div>

      {exp.data && (
        <div className="card space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">Tayyor audiokitob</h3>
            <div className="flex gap-2">
              {exp.data.m4b && <a className="btn-primary" href={exp.data.m4b} download><Download aria-hidden className="size-4" /> M4B (boblar bilan)</a>}
              {exp.data.chapters_zip && <a className="btn-secondary" href={exp.data.chapters_zip} download><Download aria-hidden className="size-4" /> MP3 (ZIP)</a>}
            </div>
          </div>
          <ul className="divide-y divide-line">
            {exp.data.chapters.map((c) => (
              <li key={c.index} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{c.title ?? (c.index === 1 ? "Kirish" : `${c.index}-qism`)}
                  <span className="ml-2 text-xs text-muted">{formatDuration(c.duration_ms)}</span></span>
                <audio controls preload="none" src={c.mp3} className="h-9 w-full sm:w-80" aria-label={`${c.title ?? c.index} tinglash`} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ====================================================================== sahifa
export default function BookPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const book = useApi<Book>(`/books/${id}`);
  const chapters = useApi<Chapter[]>(`/books/${id}/chapters`);
  const characters = useApi<Character[]>(`/books/${id}/characters`);
  const voices = useApi<Voice[]>("/voices");
  const [tab, setTab] = useState<Tab>("text");
  const [live, setLive] = useState<{ message?: string; progress?: number; spent?: number }>({});
  const { reload: reloadBook } = book;
  const { reload: reloadChapters } = chapters;
  const { reload: reloadChars } = characters;

  const reloadAll = useCallback(async () => {
    await Promise.all([reloadBook(), reloadChapters(), reloadChars()]);
  }, [reloadBook, reloadChapters, reloadChars]);

  usePipelineEvents("books", id, (e: PipelineEvent) => {
    setLive((l) => ({
      message: e.message ?? l.message, progress: e.progress ?? l.progress,
      spent: typeof e.data?.spent_usd === "number" ? (e.data.spent_usd as number) : l.spent,
    }));
    if (e.type === "status" || e.type === "error") void reloadAll();
    if (e.type === "error") toast(e.message ?? "Xato", "danger");
    if (e.status === "READY_FOR_EXPORT") toast("Audiokitob tayyor!", "ok");
  });

  const b = book.data;
  if (book.loading && !b) return <div className="grid h-64 place-items-center"><Spinner className="size-6" /></div>;
  if (!b) return <EmptyState icon={<BookOpen className="size-7" />} title="Kitob topilmadi">{book.error}</EmptyState>;

  const editable = EDITABLE.has(b.status);
  const busy = !editable;
  const progress = live.progress ?? Number(b.progress);
  const TABS: { key: Tab; label: string; icon: typeof BookOpen }[] = [
    { key: "text", label: "Matn va bloklar", icon: BookOpen },
    { key: "cast", label: `Personajlar (${characters.data?.length ?? 0})`, icon: Users },
    { key: "lexicon", label: "Talaffuz", icon: Languages },
    { key: "synth", label: "Sintez va eksport", icon: Sparkles },
  ];

  return (
    <div className="mx-auto max-w-[1600px] space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <Link href="/dashboard?tab=books" className="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ArrowLeft aria-hidden className="size-4" /> Audiokitoblar
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="truncate text-2xl font-bold">{b.title}</h1>
            <StatusBadge status={b.status} />
          </div>
          <p className="mt-1 text-sm text-muted">
            {b.author ?? "Muallif koʻrsatilmagan"}, {b.source_format.toUpperCase()}
            {b.total_chars ? `, ${b.total_chars.toLocaleString("uz")} belgi` : ""}
            {b.estimated_cost_usd ? `. Taxminiy narx ${usd(b.estimated_cost_usd)}` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          {b.status === "FAILED" && (
            <button type="button" className="btn-secondary" onClick={async () => {
              try { await api(`/books/${id}/retry`, { method: "POST" }); await reloadAll(); } catch (e) { toast((e as Error).message, "danger"); }
            }}><RotateCcw aria-hidden className="size-4" /> Qayta urinish</button>
          )}
          {b.status === "LEXICON_APPLIED" && (
            <button type="button" className="btn-primary" onClick={() => setTab("synth")}>
              <Sparkles aria-hidden className="size-4" /> Sintezga oʻtish
            </button>
          )}
          <button type="button" className="btn-ghost px-3" aria-label="Kitobni oʻchirish" onClick={async () => {
            if (!confirm("Kitobni butunlay oʻchirasizmi?")) return;
            await api(`/books/${id}`, { method: "DELETE" });
            router.replace("/dashboard?tab=books");
          }}><Trash2 className="size-4" /></button>
        </div>
      </div>

      {busy && (
        <div className="card space-y-2 p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 font-semibold"><Spinner /> {live.message ?? "Qayta ishlanmoqda…"}</span>
            <span className="tabular-nums text-muted">{progress.toFixed(0)}%</span>
          </div>
          <ProgressBar value={progress} />
          {live.spent !== undefined && <p className="text-xs text-muted">Sarf: {usd(live.spent, 4)}</p>}
        </div>
      )}
      {b.status === "FAILED" && b.error_message && (
        <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{b.error_message}</p>
      )}
      {b.status === "LEXICON_APPLIED" && (
        <p className="rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-sm text-warn">
          Tahlil tugadi. Personajlar, ovozlar va talaffuzni tekshirib, «Sintez va eksport» boʻlimida audiokitobni yarating.
        </p>
      )}

      <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                  className={`flex min-h-11 shrink-0 cursor-pointer items-center gap-2 border-b-2 px-4 text-sm font-semibold transition-colors duration-200 ${
                    tab === key ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"}`}>
            <Icon aria-hidden className="size-4" /> {label}
          </button>
        ))}
      </div>

      {tab === "text" && (chapters.data?.length
        ? <TextTab bookId={id} chapters={chapters.data} characters={characters.data ?? []} editable={editable} />
        : <EmptyState icon={<BookOpen className="size-7" />} title="Matn tahlil qilinmoqda">Boblar tayyor boʻlgach shu yerda koʻrinadi.</EmptyState>)}
      {tab === "cast" && <CastTab bookId={id} characters={characters.data ?? []} voices={voices.data ?? []} editable={editable} reload={reloadAll} />}
      {tab === "lexicon" && <LexiconTab bookId={id} editable={editable} />}
      {tab === "synth" && <SynthTab book={b} voices={voices.data ?? []} onChanged={reloadAll} />}
    </div>
  );
}
