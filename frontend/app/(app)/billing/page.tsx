"use client";

import { CreditCard, Receipt } from "lucide-react";
import { useState, type FormEvent } from "react";
import { EmptyState, Field, Spinner, Stat, useToast } from "@/components/ui";
import { useUser } from "@/components/UserContext";
import { api } from "@/lib/api";
import { dateTime, usd } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Transaction, Usage } from "@/lib/types";

const KIND: Record<string, { label: string; cls: string }> = {
  BONUS: { label: "Bonus", cls: "text-ok" },
  TOPUP: { label: "Toʻldirish", cls: "text-ok" },
  HOLD: { label: "Rezerv", cls: "text-warn" },
  SETTLE: { label: "Yakuniy hisob", cls: "text-info" },
  REFUND: { label: "Qaytarish", cls: "text-ok" },
};

export default function BillingPage() {
  const { user, refresh } = useUser();
  const toast = useToast();
  const txs = useApi<Transaction[]>("/billing/transactions?limit=100");
  const usage = useApi<Usage>("/billing/usage?days=30");
  const [busy, setBusy] = useState(false);

  async function topup(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/billing/topup/dev", { method: "POST", json: { amount_usd: new FormData(e.currentTarget).get("amount") } });
      toast("Balans toʻldirildi", "ok");
      await Promise.all([refresh(), txs.reload()]);
    } catch (err) {
      toast((err as { status?: number }).status === 404 ? "Toʻlov tizimi orqali toʻldiring (test rejimi oʻchirilgan)" : (err as Error).message, "danger");
    } finally { setBusy(false); }
  }

  const u = usage.data;
  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold sm:text-3xl">Hisob-kitob</h1>
        <p className="mt-1 text-muted">Kreditlar har bir TTS soʻrovi boʻyicha real vaqtda hisoblanadi: oldindan rezerv, yakunda haqiqiy sarf.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Joriy balans" value={usd(user?.credit_balance_usd)} />
        <Stat label="30 kunlik sarf" value={u ? usd(u.total_charge_usd) : "—"} sub={u ? `API narxi: ${usd(u.total_api_cost_usd, 4)}` : undefined} />
        <Stat label="TTS soʻrovlar" value={u ? u.rows.reduce((s, r) => s + r.jobs, 0) : "—"}
              sub={u ? `${u.rows.reduce((s, r) => s + r.fallbacks, 0)} ta zaxira provayderga oʻtdi` : undefined} />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section className="card overflow-hidden" aria-labelledby="usage-h">
          <h2 id="usage-h" className="border-b border-line px-5 py-4 font-semibold">Provayderlar boʻyicha (30 kun)</h2>
          {usage.loading && !u ? <div className="p-5"><Spinner /></div> : u?.rows.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted">
                  <tr><th className="px-5 py-2">Provayder</th><th className="px-5 py-2 text-right">Soʻrov</th><th className="px-5 py-2 text-right">Belgi</th>
                    <th className="px-5 py-2 text-right">Audio</th><th className="px-5 py-2 text-right">Kechikish</th><th className="px-5 py-2 text-right">Narx</th></tr>
                </thead>
                <tbody>
                  {u.rows.map((r) => (
                    <tr key={r.provider} className="border-t border-line tabular-nums">
                      <td className="px-5 py-3 font-semibold">{r.provider === "elevenlabs" ? "ElevenLabs" : "Google Gemini"}</td>
                      <td className="px-5 py-3 text-right">{r.jobs}{r.failed ? <span className="text-danger"> ({r.failed} xato)</span> : null}</td>
                      <td className="px-5 py-3 text-right">{r.characters.toLocaleString("uz")}</td>
                      <td className="px-5 py-3 text-right">{(r.audio_seconds / 60).toFixed(1)} daq</td>
                      <td className="px-5 py-3 text-right">{Math.round(r.avg_latency_ms)} ms</td>
                      <td className="px-5 py-3 text-right">{usd(r.api_cost_usd, 4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="p-5 text-sm text-muted">Hali TTS sarfi yoʻq.</p>}
        </section>

        <form onSubmit={topup} className="card space-y-4 p-5">
          <h2 className="flex items-center gap-2 font-semibold"><CreditCard aria-hidden className="size-5 text-info" /> Balansni toʻldirish</h2>
          <Field label="Summa (USD)" htmlFor="amount">
            <input id="amount" name="amount" type="number" min={1} max={10000} step={1} defaultValue={10} required className="input" />
          </Field>
          <button type="submit" className="btn-primary w-full" disabled={busy}>{busy && <Spinner />} Toʻldirish</button>
          <p className="text-xs text-muted">Payme / Click integratsiyasi <code>/billing/webhook</code> orqali ulanadi.</p>
        </form>
      </div>

      <section aria-labelledby="tx-h" className="card overflow-hidden">
        <h2 id="tx-h" className="border-b border-line px-5 py-4 font-semibold">Tranzaksiyalar</h2>
        {txs.loading && !txs.data ? <div className="p-5"><Spinner /></div> : txs.data?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-5 py-2">Sana</th><th className="px-5 py-2">Turi</th><th className="px-5 py-2">Izoh</th>
                  <th className="px-5 py-2 text-right">Summa</th><th className="px-5 py-2 text-right">Balans</th></tr>
              </thead>
              <tbody>
                {txs.data.map((t) => (
                  <tr key={t.id} className="border-t border-line tabular-nums">
                    <td className="whitespace-nowrap px-5 py-3 text-muted">{dateTime(t.created_at)}</td>
                    <td className={`px-5 py-3 font-semibold ${KIND[t.kind].cls}`}>{KIND[t.kind].label}</td>
                    <td className="px-5 py-3 text-muted">{t.description}</td>
                    <td className={`px-5 py-3 text-right font-semibold ${Number(t.amount_usd) >= 0 ? "text-ok" : "text-fg"}`}>
                      {Number(t.amount_usd) >= 0 ? "+" : "−"}{usd(Math.abs(Number(t.amount_usd)), 4)}
                    </td>
                    <td className="px-5 py-3 text-right">{usd(t.balance_after_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon={<Receipt className="size-7" />} title="Tranzaksiyalar yoʻq" />}
      </section>
    </div>
  );
}
