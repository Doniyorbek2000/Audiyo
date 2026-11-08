export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 font-bold ${className}`}>
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="9" className="fill-surface-2" />
        <path d="M7 19v-6M11 23V9M15 20v-8M19 25V7M23 21v-10M27 18v-4" className="stroke-accent" strokeWidth="2.4" strokeLinecap="round" />
      </svg>
      <span>Audiyo</span>
    </span>
  );
}
