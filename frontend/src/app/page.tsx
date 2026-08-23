"use client";

/**
 * Raiz do painel. Decide entre a tela de login e o app shell autenticado.
 * O roteamento entre telas internas é por hash (#rota) e fica no AppShell.
 */
import dynamic from "next/dynamic";

import { SessionUnavailable } from "@/components/auth/SessionUnavailable";
import { AppProviders } from "@/components/providers/AppProviders";
import { useAuth } from "@/lib/auth-context";
import { resolveRootSurface } from "@/lib/public-auth-flow";
import { useHashRoute } from "@/lib/use-hash-route";

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
  const { status, retrySession } = useAuth();
  const [route] = useHashRoute();
  const surface = resolveRootSurface(status, route);

  // Convites e recuperação sempre vencem uma sessão antiga de outro tenant.
  if (surface === "login") {
    return <LoginScreen />;
  }

  if (surface === "loading") {
    return <PageLoading />;
  }

  if (surface === "app") {
    return <AppShell />;
  }

  if (surface === "unavailable") {
    return <SessionUnavailable onRetry={retrySession} />;
  }

  return <LoginScreen />;
}
