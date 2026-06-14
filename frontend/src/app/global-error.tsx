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
      <body>
        <div className="full-loader">
          <div className="scaffold">
            <h3>Algo deu errado</h3>
            <p>Não foi possível carregar o painel. Tente novamente.</p>
            <button
              type="button"
              className="btn btn-primary"
              style={{ marginTop: "var(--s4)" }}
              onClick={reset}
            >
              Tentar de novo
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
