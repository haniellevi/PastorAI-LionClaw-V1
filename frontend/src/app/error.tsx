"use client";

import { useEffect } from "react";

import { DsButton } from "@/components/ds/Button";

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
        <DsButton className="ds-mt-4" onClick={reset}>
          Tentar de novo
        </DsButton>
      </div>
    </main>
  );
}
