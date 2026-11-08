"use client";

import { Mic2, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { EmptyState, Spinner, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { AGE_LABEL, GENDER_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Voice } from "@/lib/types";

export default function VoicesPage() {
  const toast = useToast();
  const voices = useApi<Voice[]>("/voices");
  const [syncing, setSyncing] = useState(false);
  const [filter, setFilter] = useState<"all" | "elevenlabs" | "gemini">("all");

  async function sync() {
    setSyncing(true);
    try {
      const added = await api<Voice[]>("/voices/sync", { method: "POST" });
      toast(added.length ? `${added.length} ta ovoz qoʻshildi` : "Yangi ovoz yoʻq", "ok");
      await voices.reload();
    } catch (e) { toast((e as Error).message, "danger"); } finally { setSyncing(false); }
  }

  const list = (voices.data ?? []).filter((v) => filter === "all" || v.provider === filter);
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">Ovozlar reyestri</h1>
          <p className="mt-1 text-muted">1-daraja — ElevenLabs (asosiy qahramonlar), 2-daraja — Gemini (ikkilamchi va budjet).</p>
        </div>
        <div className="flex gap-2">
          <label htmlFor="vf" className="sr-only">Provayder</label>
          <select id="vf" className="input w-auto cursor-pointer" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="all">Barchasi</option><option value="elevenlabs">ElevenLabs</option><option value="gemini">Gemini</option>
          </select>
          <button type="button" className="btn-secondary" onClick={sync} disabled={syncing}>
            {syncing ? <Spinner /> : <RefreshCw aria-hidden className="size-4" />} ElevenLabs bilan sinxronlash
          </button>
        </div>
      </div>
      {voices.loading && !voices.data ? <Spinner /> : list.length ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((v) => (
            <div key={v.id} className="card flex items-start gap-3 p-4">
              <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${v.provider === "elevenlabs" ? "bg-accent/15 text-accent" : "bg-info/15 text-info"}`}>
                <Mic2 aria-hidden className="size-5" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="truncate font-semibold">{v.name}</h3>
                  {v.is_cloned && <span className="rounded-full bg-warn/15 px-2 text-[11px] font-bold text-warn">Klon</span>}
                  {v.is_narrator && <span className="rounded-full bg-elevated px-2 text-[11px] font-bold text-muted">Hikoyachi</span>}
                </div>
                <p className="text-xs text-muted">
                  {v.provider === "elevenlabs" ? "ElevenLabs" : "Gemini"} · {GENDER_LABEL[v.gender]} · {AGE_LABEL[v.age_group]}
                </p>
                {v.description && <p className="mt-1 line-clamp-2 text-xs text-muted">{v.description}</p>}
              </div>
              {!v.is_system && (
                <button type="button" aria-label={`${v.name} ovozini oʻchirish`} className="btn-ghost min-h-9 px-2" onClick={async () => {
                  if (!confirm(`«${v.name}» oʻchirilsinmi?`)) return;
                  try { await api(`/voices/${v.id}`, { method: "DELETE" }); await voices.reload(); } catch (e) { toast((e as Error).message, "danger"); }
                }}><Trash2 className="size-4" /></button>
              )}
            </div>
          ))}
        </div>
      ) : <EmptyState icon={<Mic2 className="size-7" />} title="Ovozlar topilmadi">TTS provayderlari kalitlarini sozlang.</EmptyState>}
    </div>
  );
}
