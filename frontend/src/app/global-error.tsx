"use client";

/**
 * Fronteira de erro global (App Router). Substitui o documento de erro padrão
 * do pages-runtime na exportação, evitando o falso-positivo de prerender das
 * páginas /404 e /500. Precisa renderizar a própria árvore <html>/<body>.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="pt-BR">
      <body style={{ margin: 0, color: "var(--text-primary, #122333)", background: "var(--surface-canvas, #f5f9fb)", fontFamily: "Arial, sans-serif" }}>
        <style>{`.global-recovery button:focus-visible { outline: 3px solid #1c6197; outline-offset: 3px; }`}</style>
        <main className="global-recovery" aria-label="Erro ao carregar painel" style={{ display: "grid", placeItems: "center", minHeight: "100dvh", padding: 24, boxSizing: "border-box" }}>
          <div role="alert" style={{ width: "min(100%, 480px)", padding: 24, background: "var(--surface-panel, #fff)", border: "1px solid var(--border-subtle, #c8d6df)", borderRadius: 14 }}>
            <p style={{ fontSize: 14, fontWeight: 700 }}>Igreja 12</p>
            <h1 style={{ fontSize: 24, lineHeight: 1.3 }}>Não foi possível abrir o painel</h1>
            <p>Não foi possível carregar o painel. Tente novamente.</p>
            <button
              type="button"
              style={{ marginTop: 16, minHeight: 44, padding: "10px 16px", background: "var(--action-primary, #1c6197)", color: "#fff", border: 0, borderRadius: 8, fontSize: 15, fontWeight: 650, cursor: "pointer" }}
              onClick={reset}
            >
              Tentar de novo
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
