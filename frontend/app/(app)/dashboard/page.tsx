"use client";

import { BookOpen, Clapperboard, FileAudio, Plus, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useUser } from "@/components/UserContext";
import { EmptyState, Field, Modal, ProgressBar, Spinner, Stat, StatusBadge, useToast } from "@/components/ui";
import { uploadWithProgress } from "@/lib/api";
import { dateTime, formatTime, MODE_LABEL, usd } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Book, Project } from "@/lib/types";

const LANGS = [
  ["auto", "Avtomatik aniqlash"], ["en", "Ingliz"], ["ru", "Rus"], ["tr", "Turk"], ["ko", "Koreys"],
  ["ja", "Yapon"], ["zh", "Xitoy"], ["ar", "Arab"], ["fa", "Fors"], ["hi", "Hind"], ["de", "Nemis"],
  ["fr", "Fransuz"], ["es", "Ispan"],
];

function UploadVideo({ onDone }: { onDone: (p: Project) => void }) {
  const toast = useToast();
  const [pct, setPct] = useState<number | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    form.set("review_before_tts", form.get("review_before_tts") ? "true" : "false");
    setPct(0);
    try {
      const project = await uploadWithProgress<Project>("/projects/upload", form, setPct);
      toast("Video yuklandi — qayta ishlash boshlandi", "ok");
      onDone(project);
    } catch (err) {
      toast((err as Error).message, "danger");
      setPct(null);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Video yoki audio fayl" htmlFor="v-file" hint="MP4, MKV, MOV, WEBM, MP3, WAV…">
        <input id="v-file" name="file" type="file" required accept="video/*,audio/*" className="input cursor-pointer file:mr-3 file:rounded-lg file:border-0 file:bg-surface-2 file:px-3 file:py-1.5 file:text-fg" />
      </Field>
      <Field label="Nomi" htmlFor="v-title">
        <input id="v-title" name="title" className="input" placeholder="Masalan: Film, 1-qism" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Asl til" htmlFor="v-lang">
          <select id="v-lang" name="source_language" className="input cursor-pointer" defaultValue="auto">
            {LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="TTS rejimi" htmlFor="v-mode">
          <select id="v-mode" name="tts_mode" className="input cursor-pointer" defaultValue="BALANCED">
            {Object.entries(MODE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
      </div>
      <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line p-3 text-sm">
        <input type="checkbox" name="review_before_tts" className="mt-0.5 size-4 accent-[#e11d48]" />
        <span><span className="font-semibold">Ovozlashtirishdan oldin tekshirish</span>
          <span className="block text-muted">Tarjimadan keyin toʻxtaydi — ssenariyni tahrirlab, soʻng dublyajni boshlaysiz.</span></span>
      </label>
      {pct !== null && <ProgressBar value={pct} label="Yuklash" />}
      <button type="submit" className="btn-primary w-full" disabled={pct !== null}>
        {pct !== null ? <><Spinner /> Yuklanmoqda {pct}%</> : <><Upload aria-hidden className="size-4" /> Yuklash va boshlash</>}
      </button>
    </form>
  );
}

function UploadBook({ onDone }: { onDone: (b: Book) => void }) {
  const toast = useToast();
  const [pct, setPct] = useState<number | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPct(0);
    try {
      const book = await uploadWithProgress<Book>("/books/upload", new FormData(e.currentTarget), setPct);
      toast("Kitob yuklandi — tahlil boshlandi", "ok");
      onDone(book);
    } catch (err) {
      toast((err as Error).message, "danger");
      setPct(null);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Kitob fayli" htmlFor="b-file" hint="EPUB, FB2, DOCX, PDF yoki TXT · 50 MB gacha · oʻzbekcha (lotin/kirill)">
        <input id="b-file" name="file" type="file" required accept=".epub,.fb2,.docx,.pdf,.txt" className="input cursor-pointer file:mr-3 file:rounded-lg file:border-0 file:bg-surface-2 file:px-3 file:py-1.5 file:text-fg" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nomi" htmlFor="b-title"><input id="b-title" name="title" className="input" /></Field>
        <Field label="Muallif" htmlFor="b-author"><input id="b-author" name="author" className="input" /></Field>
      </div>
      <Field label="TTS rejimi" htmlFor="b-mode">
        <select id="b-mode" name="tts_mode" className="input cursor-pointer" defaultValue="BALANCED">
          {Object.entries(MODE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </Field>
      <p className="text-xs text-muted">Tahlildan soʻng personajlar, ovozlar va talaffuzni tekshirasiz; sintez narxi oldindan koʻrsatiladi.</p>
      {pct !== null && <ProgressBar value={pct} label="Yuklash" />}
      <button type="submit" className="btn-primary w-full" disabled={pct !== null}>
        {pct !== null ? <><Spinner /> Yuklanmoqda {pct}%</> : <><Upload aria-hidden className="size-4" /> Yuklash</>}
      </button>
    </form>
  );
}

function ItemCard({ href, title, sub, status, progress, error }: {
  href: string; title: string; sub: string; status: string; progress: number; error: string | null;
}) {
  const busy = !["READY_FOR_EXPORT", "FAILED", "LEXICON_APPLIED"].includes(status);
  return (
    <Link href={href} className="card group block cursor-pointer p-5 transition-colors duration-200 hover:border-info/60">
      <div className="flex items-start justify-between gap-3">
        <h3 className="line-clamp-2 font-semibold group-hover:text-info">{title}</h3>
        <StatusBadge status={status} />
      </div>
      <p className="mt-1 text-sm text-muted">{sub}</p>
      {busy && <div className="mt-4"><ProgressBar value={progress} /></div>}
      {error && <p className="mt-3 line-clamp-2 text-xs text-danger">{error}</p>}
    </Link>
  );
}

function Dashboard() {
  const router = useRouter();
  const params = useSearchParams();
  const tab = params.get("tab") === "books" ? "books" : params.get("tab") === "video" ? "video" : "all";
  const { user } = useUser();
  const projects = useApi<Project[]>("/projects");
  const books = useApi<Book[]>("/books");
  const [modal, setModal] = useState<"video" | "book" | null>(null);

  // Jarayondagi elementlar boʻlsa — davriy yangilash
  const busy = [...(projects.data ?? []), ...(books.data ?? [])].some(
    (x) => !["READY_FOR_EXPORT", "FAILED", "LEXICON_APPLIED"].includes(x.status));
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => { void projects.reload(); void books.reload(); }, 5000);
    return () => clearInterval(t);
  }, [busy, projects.reload, books.reload]);

  const ready = (projects.data ?? []).filter((p) => p.status === "READY_FOR_EXPORT").length;
  const minutes = (projects.data ?? []).reduce((s, p) => s + Number(p.duration_seconds ?? 0), 0) / 60;

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">Salom{user?.full_name ? `, ${user.full_name}` : ""}!</h1>
          <p className="mt-1 text-muted">Video dublyaj va audiokitob loyihalaringiz.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-secondary" onClick={() => setModal("book")}>
            <BookOpen aria-hidden className="size-4" /> Kitob
          </button>
          <button type="button" className="btn-primary" onClick={() => setModal("video")}>
            <Plus aria-hidden className="size-4" /> Yangi video
          </button>
        </div>
      </div>

      {tab === "all" && (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          <Stat label="Balans" value={usd(user?.credit_balance_usd)} />
          <Stat label="Video loyihalar" value={projects.data?.length ?? "—"} sub={`${ready} tasi tayyor`} />
          <Stat label="Dublyaj daqiqalari" value={minutes.toFixed(1)} />
          <Stat label="Audiokitoblar" value={books.data?.length ?? "—"} />
        </div>
      )}

      {tab !== "books" && (
        <section aria-labelledby="videos-h" className="space-y-4">
          <h2 id="videos-h" className="flex items-center gap-2 text-lg font-semibold">
            <Clapperboard aria-hidden className="size-5 text-info" /> Video loyihalar
          </h2>
          {projects.loading && !projects.data ? <Spinner /> : projects.data?.length ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {projects.data.map((p) => (
                <ItemCard key={p.id} href={`/projects/${p.id}`} title={p.title} status={p.status}
                          progress={Number(p.progress)} error={p.status === "FAILED" ? p.error_message : null}
                          sub={`${p.source_language.toUpperCase()} → UZ · ${p.duration_seconds ? formatTime(Number(p.duration_seconds), false) : "—"} · ${dateTime(p.created_at)}`} />
              ))}
            </div>
          ) : (
            <EmptyState icon={<FileAudio className="size-7" />} title="Hali video yoʻq">
              Birinchi videoni yuklang — Audiyo ovozni ajratadi, tarjima qiladi va oʻzbekcha dublyaj tayyorlaydi.
            </EmptyState>
          )}
        </section>
      )}

      {tab !== "video" && (
        <section aria-labelledby="books-h" className="space-y-4">
          <h2 id="books-h" className="flex items-center gap-2 text-lg font-semibold">
            <BookOpen aria-hidden className="size-5 text-info" /> Audiokitoblar
          </h2>
          {books.loading && !books.data ? <Spinner /> : books.data?.length ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {books.data.map((b) => (
                <ItemCard key={b.id} href={`/books/${b.id}`} title={b.title} status={b.status}
                          progress={Number(b.progress)} error={b.status === "FAILED" ? b.error_message : null}
                          sub={`${b.author ?? "Muallif koʻrsatilmagan"} · ${b.source_format.toUpperCase()} · ${b.total_chars?.toLocaleString("uz") ?? "—"} belgi`} />
              ))}
            </div>
          ) : (
            <EmptyState icon={<BookOpen className="size-7" />} title="Hali kitob yoʻq">
              EPUB, FB2, DOCX, PDF yoki TXT faylni yuklang — boblar, personajlar va talaffuz avtomatik tayyorlanadi.
            </EmptyState>
          )}
        </section>
      )}

      <Modal open={modal === "video"} onClose={() => setModal(null)} title="Yangi video dublyaj">
        <UploadVideo onDone={(p) => router.push(`/projects/${p.id}`)} />
      </Modal>
      <Modal open={modal === "book"} onClose={() => setModal(null)} title="Yangi audiokitob">
        <UploadBook onDone={(b) => router.push(`/books/${b.id}`)} />
      </Modal>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Dashboard />
    </Suspense>
  );
}
