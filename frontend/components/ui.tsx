"use client";

import { AlertTriangle, CheckCircle2, Loader2, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// ------------------------------------------------------------------ holat nishonlari
const STATUS_META: Record<string, { label: string; tone: "ok" | "warn" | "danger" | "info" | "muted" }> = {
  UPLOADED: { label: "Yuklandi", tone: "muted" },
  STEM_SEPARATION: { label: "Ovoz ajratildi", tone: "info" },
  TRANSCRIBED: { label: "Transkripsiya", tone: "info" },
  TRANSLATED: { label: "Tarjima qilindi", tone: "info" },
  TTS_DISPATCHED: { label: "Ovozlashtirildi", tone: "info" },
  TIMING_ALIGNED: { label: "Vaqt moslandi", tone: "info" },
  MASTERED: { label: "Mastering", tone: "info" },
  READY_FOR_EXPORT: { label: "Tayyor", tone: "ok" },
  FAILED: { label: "Xato", tone: "danger" },
  PARSED: { label: "Oʻqildi", tone: "info" },
  NORMALIZED: { label: "Normallashtirildi", tone: "info" },
  SEGMENTED: { label: "Segmentlandi", tone: "info" },
  ATTRIBUTED: { label: "Personajlar", tone: "info" },
  LEXICON_APPLIED: { label: "Tekshiruvga tayyor", tone: "warn" },
  STITCHED: { label: "Birlashtirildi", tone: "info" },
  PENDING: { label: "Kutilmoqda", tone: "muted" },
  SYNTHESIZED: { label: "Sintez qilindi", tone: "info" },
  ALIGNED: { label: "Moslandi", tone: "ok" },
};
const TONE: Record<string, string> = {
  ok: "bg-ok/15 text-ok border-ok/30",
  warn: "bg-warn/15 text-warn border-warn/30",
  danger: "bg-danger/15 text-danger border-danger/30",
  info: "bg-info/15 text-info border-info/30",
  muted: "bg-elevated text-muted border-line",
};

export function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, tone: "muted" as const };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE[meta.tone]}`}>
      {meta.tone === "ok" && <CheckCircle2 aria-hidden className="size-3.5" />}
      {meta.tone === "danger" && <AlertTriangle aria-hidden className="size-3.5" />}
      {meta.label}
    </span>
  );
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div role="progressbar" aria-valuenow={Math.round(v)} aria-valuemin={0} aria-valuemax={100} aria-label={label ?? "Jarayon"}
         className="h-2 w-full overflow-hidden rounded-full bg-elevated">
      <div className="h-full rounded-full bg-gradient-to-r from-info to-accent transition-[width] duration-500"
           style={{ width: `${v}%` }} />
    </div>
  );
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  return <Loader2 aria-hidden className={`${className} animate-spin`} />;
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center gap-3 px-6 py-14 text-center">
      <div className="rounded-2xl bg-elevated p-4 text-info">{icon}</div>
      <h3 className="text-lg font-semibold">{title}</h3>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ modal
export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose}
            className={`m-auto w-[calc(100%-2rem)] ${wide ? "max-w-3xl" : "max-w-lg"} rounded-2xl border border-line bg-surface p-0 text-fg backdrop:bg-black/70`}>
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 className="text-lg font-semibold">{title}</h2>
        <button type="button" onClick={onClose} aria-label="Yopish" className="btn-ghost min-h-9 px-2">
          <X className="size-5" />
        </button>
      </div>
      <div className="max-h-[75vh] overflow-y-auto p-5">{open && children}</div>
    </dialog>
  );
}

// ------------------------------------------------------------------ toast
type Toast = { id: number; text: string; tone: "ok" | "danger" | "info" };
const ToastCtx = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(24rem,calc(100%-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className={`pointer-events-auto rounded-xl border px-4 py-3 text-sm shadow-2xl shadow-black/50 ${TONE[t.tone]} bg-surface`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

// ------------------------------------------------------------------ boshqalar
export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="label">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card p-5">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-2 text-2xl font-bold tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}
