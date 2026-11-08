"use client";

import { BookOpen, Clapperboard, CreditCard, LayoutDashboard, LogOut, Menu, Mic2, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Logo } from "@/components/Logo";
import { Spinner } from "@/components/ui";
import { UserCtx } from "@/components/UserContext";
import { api, auth } from "@/lib/api";
import { usd } from "@/lib/format";
import type { User } from "@/lib/types";

const NAV = [
  { href: "/dashboard", label: "Boshqaruv paneli", icon: LayoutDashboard },
  { href: "/dashboard?tab=video", label: "Video dublyaj", icon: Clapperboard },
  { href: "/dashboard?tab=books", label: "Audiokitoblar", icon: BookOpen },
  { href: "/voices", label: "Ovozlar", icon: Mic2 },
  { href: "/billing", label: "Hisob-kitob", icon: CreditCard },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const refresh = async () => setUser(await api<User>("/auth/me"));

  useEffect(() => {
    if (!auth.token) {
      router.replace("/login");
      return;
    }
    refresh().catch(() => router.replace("/login"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => setMenuOpen(false), [pathname]);

  if (!user) {
    return (
      <div className="grid min-h-dvh place-items-center text-muted">
        <Spinner className="size-6" />
      </div>
    );
  }

  const nav = (
    <nav aria-label="Asosiy menyu" className="flex flex-1 flex-col gap-1">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href.split("?")[0] && (href === "/dashboard" || !href.includes("?"));
        return (
          <Link key={href} href={href}
                className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors duration-200 ${
                  active ? "bg-surface-2 text-fg" : "text-muted hover:bg-elevated hover:text-fg"}`}>
            <Icon aria-hidden className="size-5" />
            {label}
          </Link>
        );
      })}
    </nav>
  );

  const footer = (
    <div className="mt-6 space-y-3 border-t border-line pt-4">
      <Link href="/billing" className="block rounded-xl bg-elevated p-3 transition-colors duration-200 hover:bg-surface-2">
        <div className="text-xs text-muted">Balans</div>
        <div className="text-lg font-bold tabular-nums">{usd(user.credit_balance_usd)}</div>
      </Link>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm text-muted" title={user.email}>{user.email}</span>
        <button type="button" aria-label="Chiqish" className="btn-ghost min-h-9 px-2"
                onClick={() => { auth.clear(); router.replace("/login"); }}>
          <LogOut className="size-4" />
        </button>
      </div>
    </div>
  );

  return (
    <UserCtx.Provider value={{ user, refresh }}>
      <div className="min-h-dvh lg:grid lg:grid-cols-[260px_1fr]">
        <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line bg-surface p-4 lg:flex">
          <Link href="/dashboard" className="mb-6 px-2"><Logo className="text-xl" /></Link>
          {nav}
          {footer}
        </aside>

        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface/95 px-4 py-3 backdrop-blur lg:hidden">
          <Link href="/dashboard"><Logo /></Link>
          <button type="button" className="btn-ghost px-2" aria-label="Menyu" aria-expanded={menuOpen}
                  onClick={() => setMenuOpen((v) => !v)}>
            {menuOpen ? <X className="size-6" /> : <Menu className="size-6" />}
          </button>
        </header>
        {menuOpen && (
          <div className="fixed inset-x-0 top-[61px] bottom-0 z-20 flex flex-col overflow-y-auto bg-surface p-4 lg:hidden">
            {nav}
            {footer}
          </div>
        )}

        <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">{children}</main>
      </div>
    </UserCtx.Provider>
  );
}
