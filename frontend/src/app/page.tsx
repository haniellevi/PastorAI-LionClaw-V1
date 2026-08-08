"use client";

/**
 * Raiz do painel. Decide entre a tela de login e o app shell autenticado.
 * O roteamento entre telas internas é por hash (#rota) e fica no AppShell.
 */
import dynamic from "next/dynamic";

import { AppProviders } from "@/components/providers/AppProviders";
import { useAuth } from "@/lib/auth-context";

const AppShell = dynamic(
  () => import("@/components/shell/AppShell").then((module) => module.AppShell),
  { loading: PageLoading },
);
const LoginScreen = dynamic(
  () => import("@/components/login/LoginScreen").then((module) => module.LoginScreen),
  { loading: PageLoading },
);

export default function HomePage() {
  return (
    <AppProviders>
      <HomeContent />
    </AppProviders>
  );
}

function PageLoading() {
  return (
    <div className="full-loader" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span className="sr-only">Carregando…</span>
    </div>
  );
}

function HomeContent() {
  const { status } = useAuth();

  if (status === "loading") {
    return <PageLoading />;
  }

  if (status === "authenticated") {
    return <AppShell />;
  }

  return <LoginScreen />;
}
