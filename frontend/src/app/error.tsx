"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <main className="full-loader" aria-label="Erro ao carregar painel">
      <div className="scaffold" role="alert">
        <h1>Não foi possível abrir o painel</h1>
        <p>Não foi possível carregar o painel. Tente novamente.</p>
        <button type="button" className="btn btn-primary" style={{ marginTop: "var(--s4)" }} onClick={reset}>
          Tentar de novo
        </button>
      </div>
    </main>
  );
}
