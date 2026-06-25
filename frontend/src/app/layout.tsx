import type { Metadata, Viewport } from "next";

import { AppProviders } from "@/components/providers/AppProviders";

// Webfonts self-hosted (Igreja 12 — F1). Servidas do node_modules via @fontsource;
// o build empacota os woff2 localmente, sem chamadas externas. As famílias batem
// com os tokens --font / --font-display / --mono do globals.css.
import "@fontsource/plus-jakarta-sans/400.css";
import "@fontsource/plus-jakarta-sans/500.css";
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
import "@fontsource/sora/600.css";
import "@fontsource/sora/700.css";
import "@fontsource/sora/800.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";

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
    apple: "/apple-touch-icon.png",
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
  themeColor: "#0b2c29",
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
