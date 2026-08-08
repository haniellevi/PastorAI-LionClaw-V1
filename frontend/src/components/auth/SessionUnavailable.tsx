"use client";

import { Button } from "@/components/ui/Button";

export function SessionUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: "var(--s4)",
      }}
    >
      <section className="login-card" style={{ maxWidth: 420, width: "100%" }}>
        <h1>Serviço temporariamente indisponível</h1>
        <p className="sub">
          Sua sessão foi preservada. Verifique sua conexão e tente novamente em instantes.
        </p>
        <Button type="button" variant="primary" block onClick={onRetry}>
          Tentar novamente
        </Button>
      </section>
    </main>
  );
}
