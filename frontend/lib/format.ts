export function formatTime(seconds: number, withMs = true): string {
  const s = Math.max(0, seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const ms = Math.floor((s % 1) * 1000);
  const base = `${h > 0 ? `${h}:` : ""}${String(m).padStart(h > 0 ? 2 : 1, "0")}:${String(sec).padStart(2, "0")}`;
  return withMs ? `${base}.${String(ms).padStart(3, "0")}` : base;
}

export function formatDuration(ms: number | null | undefined): string {
  if (!ms) return "0:00";
  return formatTime(ms / 1000, false);
}

export function usd(value: string | number | null | undefined, digits?: number): string {
  const n = typeof value === "string" ? Number(value) : value ?? 0;
  // Kichik summalar (TTS segmentlari) uchun aniqlik oshiriladi
  const d = digits ?? (n !== 0 && Math.abs(n) < 0.1 ? 4 : 2);
  return `$${n.toFixed(d)}`;
}

export function dateTime(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Spiker ranglari: globals.css dagi tokenlar (CSS da toʻgʻridan-toʻgʻri ishlatiladi). */
export const SPEAKER_COLORS = Array.from({ length: 8 }, (_, i) => `var(--color-spk-${i + 1})`);
export const NO_SPEAKER_COLOR = "var(--color-spk-none)";

/** Canvas (WaveSurfer) CSS oʻzgaruvchilarini tushunmaydi: tokenni haqiqiy qiymatga aylantiradi. */
export function resolveColor(value: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(value);
  if (!m || typeof window === "undefined") return value;
  return getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || value;
}

export const GENDER_LABEL: Record<string, string> = { MALE: "Erkak", FEMALE: "Ayol", UNKNOWN: "Nomaʼlum" };
export const AGE_LABEL: Record<string, string> = {
  CHILD: "Bola", YOUNG_ADULT: "Yosh", ADULT: "Kattalar", ELDERLY: "Keksa", UNKNOWN: "Nomaʼlum",
};
export const EMOTION_LABEL: Record<string, string> = {
  neutral: "Neytral", happy: "Quvnoq", sad: "Gʻamgin", angry: "Jahldor", excited: "Hayajonli", fearful: "Qoʻrqqan",
  surprised: "Hayron", whisper: "Pichirlash", tender: "Mehribon", sarcastic: "Kinoyali", serious: "Jiddiy",
  curious: "Qiziquvchan", hesitant: "Ikkilangan", anxious: "Xavotirli",
};
export const MODE_LABEL: Record<string, string> = {
  PREMIUM: "Premium: hammasi ElevenLabs",
  BALANCED: "Muvozanat: asosiylar ElevenLabs, qolgani Gemini",
  BUDGET: "Tejamkor: hammasi Gemini",
};
