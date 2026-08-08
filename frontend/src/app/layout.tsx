import type { Metadata, Viewport } from "next";

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
// Fundação "Diamante Lapidado" (Gate 6): tokens semânticos + primitives ds-*.
// Aditivos — nenhum token legado muda de valor; telas não migradas não mudam.
import "./design-tokens.css";
import "./ds.css";

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

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // Gate 6.1: chrome do PWA na direção Diamante Lapidado — hex sRGB do token
  // --diamond-950 (oklch(24% 0.055 252)); o teal #0b2c29 era da identidade antiga.
  themeColor: "#092038",
  colorScheme: "light",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
