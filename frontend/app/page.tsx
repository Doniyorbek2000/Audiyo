import { ArrowRight, AudioLines, BookOpen, Captions, Clapperboard, Languages, Sparkles, Wand2 } from "lucide-react";
import Link from "next/link";
import { Logo } from "@/components/Logo";

const STEPS = [
  { icon: AudioLines, title: "Ovozni ajratish", text: "Demucs vokalni fon musiqasi va effektlardan ajratadi — fon saqlanib qoladi." },
  { icon: Captions, title: "Nutqni aniqlash", text: "WhisperX soʻz darajasidagi vaqt belgilari, spikerlar va jinsini aniqlaydi." },
  { icon: Languages, title: "Moslashgan tarjima", text: "LLM boʻgʻin byudjeti bilan tarjima qiladi — oʻzbekcha matn vaqtga sigʻadi." },
  { icon: Sparkles, title: "Aqlli TTS", text: "Asosiy qahramonlar ElevenLabs, qolganlar Gemini — sifat va narx muvozanati." },
  { icon: Wand2, title: "Vaqt va mikslash", text: "Ohangni buzmasdan tezlikni moslash, fon musiqasini avtomatik pasaytirish." },
  { icon: BookOpen, title: "Audiokitoblar", text: "Romanlarni boblarga ajratib, har personajga alohida ovoz bilan M4B yaratadi." },
];

export default function Landing() {
  return (
    <div className="min-h-dvh">
      <header className="fixed inset-x-4 top-4 z-30 mx-auto flex max-w-6xl items-center justify-between rounded-2xl border border-line bg-surface/85 px-4 py-3 backdrop-blur">
        <Logo className="text-lg" />
        <nav className="flex items-center gap-2">
          <Link href="/login" className="btn-ghost">Kirish</Link>
          <Link href="/register" className="btn-primary">Bepul boshlash</Link>
        </nav>
      </header>

      <section className="relative overflow-hidden px-4 pb-20 pt-36 sm:pt-44">
        <div aria-hidden className="pointer-events-none absolute inset-0 opacity-60">
          <svg className="absolute bottom-0 left-1/2 h-64 w-[1400px] -translate-x-1/2" viewBox="0 0 1400 256" preserveAspectRatio="none">
            {Array.from({ length: 140 }, (_, i) => {
              const h = 20 + Math.abs(Math.sin(i * 0.37) * Math.cos(i * 0.11)) * 200;
              return <rect key={i} x={i * 10} y={256 - h} width="5" height={h} rx="2.5"
                           fill={i % 7 === 0 ? "#e11d48" : "#1e1b4b"} />;
            })}
          </svg>
        </div>
        <div className="relative mx-auto max-w-4xl text-center">
          <p className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-elevated px-3 py-1 text-xs font-semibold text-muted">
            <Clapperboard aria-hidden className="size-4 text-accent" /> Oʻzbek tili uchun yaratilgan
          </p>
          <h1 className="text-4xl font-extrabold leading-tight tracking-tight sm:text-6xl">
            Har qanday videoni <span className="text-accent">oʻzbekcha</span> gapirting
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted">
            Audiyo chet tilidagi film, dars va kitoblarni tabiiy oʻzbekcha dublyajga aylantiradi: asl fon musiqasi,
            personaj ovozlari va lab harakati bilan mos vaqt saqlanadi.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/register" className="btn-primary min-h-12 px-6 text-base">
              Birinchi videoni dublyaj qilish <ArrowRight aria-hidden className="size-5" />
            </Link>
            <Link href="/login" className="btn-secondary min-h-12 px-6 text-base">Hisobga kirish</Link>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-24">
        <h2 className="mb-8 text-center text-2xl font-bold sm:text-3xl">Toʻliq avtomatik konveyer</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, text }, i) => (
            <div key={title} className="card p-6 transition-colors duration-200 hover:border-info/50">
              <div className="mb-4 flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-xl bg-surface-2 text-info"><Icon aria-hidden className="size-5" /></span>
                <span className="text-xs font-semibold text-muted">0{i + 1}</span>
              </div>
              <h3 className="font-semibold">{title}</h3>
              <p className="mt-2 text-sm text-muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-line px-4 py-8 text-center text-sm text-muted">
        © {new Date().getFullYear()} Audiyo
      </footer>
    </div>
  );
}
