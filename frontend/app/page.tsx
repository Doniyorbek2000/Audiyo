import { AudioLines, BookOpen, Captions, Languages, Sparkles, Wand2 } from "lucide-react";
import Link from "next/link";
import { Logo } from "@/components/Logo";

const STEPS = [
  { icon: AudioLines, title: "Ovozni ajratish", text: "Demucs vokalni fon musiqasi va effektlardan ajratadi, fon oʻz joyida qoladi." },
  { icon: Captions, title: "Nutqni aniqlash", text: "WhisperX soʻz darajasidagi vaqt belgilari, spikerlar va jinsini aniqlaydi." },
  { icon: Languages, title: "Moslashgan tarjima", text: "Tarjima boʻgʻinlar soni bilan cheklanadi, shuning uchun oʻzbekcha matn sahnaga sigʻadi." },
  { icon: Sparkles, title: "Aqlli TTS", text: "Asosiy qahramonlar ElevenLabs, qolganlar Gemini ovozida: sifat ham, narx ham joyida." },
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
                           className={i % 7 === 0 ? "fill-accent" : "fill-surface-2"} />;
            })}
          </svg>
        </div>
        <div className="relative mx-auto max-w-4xl text-center">
          <h1 className="text-4xl font-bold leading-tight sm:text-6xl">
            Har qanday videoni oʻzbekcha gapirting
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-lg text-muted">
            Film, dars va kitoblar tabiiy oʻzbekcha ovozda, asl fon musiqasi bilan.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/register" className="btn-primary min-h-12 px-6 text-base">
              Birinchi videoni dublyaj qilish
            </Link>
            <Link href="/login" className="btn-secondary min-h-12 px-6 text-base">Hisobga kirish</Link>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-24">
        <h2 className="mb-8 text-2xl font-bold sm:text-3xl">Yuklaysiz, qolganini Audiyo bajaradi</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, text }) => (
            <div key={title} className="card p-6 transition-colors duration-200 hover:border-info/50">
              <Icon aria-hidden className="mb-4 size-6 text-info" />
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
