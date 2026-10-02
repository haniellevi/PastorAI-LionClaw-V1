"use client";

import { Button } from "@/components/ui/Button";

import { AuthLayout } from "./AuthLayout";

export function SessionUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <AuthLayout>
      <section className="login-card">
        <header className="login-card-head">
          <h1>Serviço temporariamente indisponível</h1>
          <p className="sub">
            Sua sessão foi preservada. Verifique sua conexão e tente novamente em instantes.
          </p>
        </header>
        <Button type="button" variant="primary" block onClick={onRetry}>
          Tentar novamente
        </Button>
      </section>
    </AuthLayout>
  );
}
