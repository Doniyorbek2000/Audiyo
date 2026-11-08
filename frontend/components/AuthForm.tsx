"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Logo } from "@/components/Logo";
import { Field, Spinner } from "@/components/ui";
import { api, auth } from "@/lib/api";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ access_token: string }>(`/auth/${mode}`, {
        method: "POST",
        json: Object.fromEntries(form.entries()),
      });
      auth.set(res.access_token);
      router.replace("/dashboard");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const isLogin = mode === "login";
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 flex justify-center"><Logo className="text-2xl" /></Link>
        <form onSubmit={submit} className="card space-y-5 p-6 sm:p-8" noValidate={false}>
          <div>
            <h1 className="text-2xl font-bold">{isLogin ? "Hisobga kirish" : "Roʻyxatdan oʻtish"}</h1>
            <p className="mt-1 text-sm text-muted">
              {isLogin ? "Loyihalaringizni davom ettiring." : "Roʻyxatdan oʻtganingizda $2 bonus kredit beriladi."}
            </p>
          </div>
          {!isLogin && (
            <Field label="Ism" htmlFor="full_name">
              <input id="full_name" name="full_name" className="input" autoComplete="name" />
            </Field>
          )}
          <Field label="Email" htmlFor="email">
            <input id="email" name="email" type="email" required className="input" autoComplete="email" />
          </Field>
          <Field label="Parol" htmlFor="password" hint={isLogin ? undefined : "Kamida 8 belgi"}>
            <input id="password" name="password" type="password" required minLength={8} className="input"
                   autoComplete={isLogin ? "current-password" : "new-password"} />
          </Field>
          {error && <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy && <Spinner />}
            {isLogin ? "Kirish" : "Hisob yaratish"}
          </button>
          <p className="text-center text-sm text-muted">
            {isLogin ? "Hisobingiz yoʻqmi? " : "Hisobingiz bormi? "}
            <Link href={isLogin ? "/register" : "/login"} className="font-semibold text-info hover:underline">
              {isLogin ? "Roʻyxatdan oʻting" : "Kiring"}
            </Link>
          </p>
        </form>
      </div>
    </main>
  );
}
