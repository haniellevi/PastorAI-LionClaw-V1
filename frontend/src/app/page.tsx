"use client";

/**
 * Raiz do painel. Decide entre a tela de login e o app shell autenticado.
 * O roteamento entre telas internas é por hash (#rota) e fica no AppShell.
 */
import { AppShell } from "@/components/shell/AppShell";
import { LoginScreen } from "@/components/login/LoginScreen";
import { useAuth } from "@/lib/auth-context";

export default function HomePage() {
  const { status } = useAuth();

  if (status === "loading") {
    return (
      <div className="full-loader" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
          Carregando sessão…
        </span>
      </div>
    );
  }

  if (status === "authenticated") {
    return <AppShell />;
  }

  return <LoginScreen />;
}
