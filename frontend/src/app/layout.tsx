import type { Metadata, Viewport } from "next";
import { connection } from "next/server";

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
// Fundação "Diamante Lapidado": tokens semânticos + primitives ds-*.
// O globals.css mantém aliases compatíveis, todos alinhados a esta fundação.
import "./design-tokens.css";
import "./ds.css";
import "./expressive-ux-v3.css";

export const metadata: Metadata = {
  title: {
    default: "Igreja 12 — Painel da Igreja",
    template: "%s · Igreja 12",
  },
  description:
    "Cuidado e acompanhamento para sua igreja: pessoas, células e atendimentos pelo WhatsApp, com um painel para configuração e governança.",
  applicationName: "Igreja 12",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Igreja 12",
  },
  icons: {
    // URL própria da microversão evita que navegadores reaproveitem o favicon
    // legado já armazenado em cache. A silhueta sólida é a versão canônica em
    // 16 px da identidade Diamante Lapidado.
    icon: {
      url: "/brand/diamante-silhueta-16.svg",
      type: "image/svg+xml",
      sizes: "16x16",
    },
    shortcut: "/brand/diamante-silhueta-16.svg",
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

// O shell não contém dados de usuário no HTML do servidor: a sessão continua
// resolvida no cliente pelo AuthProvider. A casca renderiza a cada acesso só
// para receber o nonce da CSP gerado pelo middleware (ver src/lib/csp.mjs);
// uma página pré-renderizada teria scripts sem nonce.
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  await connection();
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
