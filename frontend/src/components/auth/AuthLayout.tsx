import Link from "next/link";
import type { ReactNode } from "react";

import { BrandSignature } from "@/components/brand/BrandSignature";

/** Marca e espaço de leitura comuns às entradas da igreja e da plataforma. */
export function AuthLayout({ children, purpose }: { children: ReactNode; purpose?: string }) {
  return (
    <main className="auth-page">
      <div className="auth-content">
        <header className="auth-brand">
          <BrandSignature size={32} tone="var(--diamond-900)" />
        </header>
        {children}
        <nav className="login-legal-links" aria-label="Informações legais">
          <Link href="/termos">Termos de Uso</Link>
          <span aria-hidden="true">·</span>
          <Link href="/privacidade">Privacidade</Link>
        </nav>
        {purpose ? <p className="auth-purpose">{purpose}</p> : null}
      </div>
    </main>
  );
}
