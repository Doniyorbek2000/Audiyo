import type { Metadata, Viewport } from "next";
import { ToastProvider } from "@/components/ui";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Audiyo: oʻzbekcha dublyaj va audiokitoblar", template: "%s | Audiyo" },
  description: "Chet tilidagi video va kitoblarni tabiiy oʻzbekcha ovozga aylantiruvchi AI platforma.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "oklch(0.13 0.02 280)" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="uz">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap"
        />
      </head>
      <body>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
