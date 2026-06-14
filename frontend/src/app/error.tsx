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
    <div className="full-loader">
      <div className="scaffold">
        <h3>Algo deu errado</h3>
        <p>Não foi possível carregar o painel. Tente novamente.</p>
        <button type="button" className="btn btn-primary" style={{ marginTop: "var(--s4)" }} onClick={reset}>
          Tentar de novo
        </button>
      </div>
    </div>
  );
}
