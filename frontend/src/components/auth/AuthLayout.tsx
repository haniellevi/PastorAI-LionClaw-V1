import Link from "next/link";
import type { ReactNode } from "react";

import { BrandSignature } from "@/components/brand/BrandSignature";
import { MineralBackdrop } from "@/components/brand/MineralBackdrop";
import { SupportReveal } from "@/components/brand/SupportReveal";

/** Marca e espaço de leitura comuns às entradas da igreja e da plataforma. */
export function AuthLayout({ children, purpose }: { children: ReactNode; purpose?: string }) {
  return (
    <main className="auth-page" data-mineral-surface>
      <section className="auth-story mineral-surface" aria-label="Igreja 12">
        <MineralBackdrop />
        <div className="auth-story-content">
          <BrandSignature size={32} tone="var(--text-on-action)" />
          <div className="auth-story-copy">
            <p className="auth-story-kicker">Presença que aproxima</p>
            <h2>Mais presença.{" "}<br />Cuidado próximo.</h2>
            <p>O WhatsApp é o ponto de encontro. O painel ajuda você a acompanhar e agir.</p>
          </div>
          <span className="auth-story-caption">Pessoas · Células · Cuidado</span>
        </div>
      </section>
      <div className="auth-form-side">
        <div className="auth-content">
        {children}
        <SupportReveal>
          <nav className="login-legal-links" aria-label="Informações legais">
          <Link href="/termos">Termos de Uso</Link>
          <span aria-hidden="true">·</span>
          <Link href="/privacidade">Privacidade</Link>
          </nav>
        {purpose ? <p className="auth-purpose">{purpose}</p> : null}
        </SupportReveal>
        </div>
      </div>
    </main>
  );
}
