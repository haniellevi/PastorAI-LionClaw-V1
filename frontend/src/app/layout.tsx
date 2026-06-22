import type { Metadata, Viewport } from "next";

import { AppProviders } from "@/components/providers/AppProviders";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Igreja 12 — Painel da Igreja",
    template: "%s · Igreja 12",
  },
  description:
    "Sistema agêntico de gestão de igrejas na Visão G12: consolidação, discipulado e células orquestrados por IA no WhatsApp.",
  applicationName: "Igreja 12",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Igreja 12",
  },
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
  formatDetection: { telephone: false },
};

// O painel é inteiramente client-side e auth-gated (sessão via Clerk/contexto):
// não há HTML estático útil a pré-renderizar e o SSG do shell quebra ao ler o
// contexto de sessão durante o build. Renderização dinâmica evita esse prerender.
export const dynamic = "force-dynamic";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#1b2526",
  colorScheme: "light",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
