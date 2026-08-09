"use client";

/**
 * Raiz do console Super-Admin (rota /admin). Decide entre o login do console e
 * o console autenticado. Superfície separada do painel da igreja (PRD: US-42/43
 * em superfície própria, fora do painel operacional).
 */
import dynamic from "next/dynamic";

import { SessionUnavailable } from "@/components/auth/SessionUnavailable";
import { useAdminAuth } from "@/lib/admin-auth-context";

const AdminConsole = dynamic(
  () => import("@/components/admin/AdminConsole").then((module) => module.AdminConsole),
  { loading: PageLoading },
);
const AdminLoginScreen = dynamic(
  () =>
    import("@/components/admin/AdminLoginScreen").then(
      (module) => module.AdminLoginScreen,
    ),
  { loading: PageLoading },
);

function PageLoading() {
  return (
    <div className="full-loader" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span className="sr-only">Carregando…</span>
    </div>
  );
}

export default function AdminPage() {
  const { status, retrySession } = useAdminAuth();

  if (status === "loading") {
    return <PageLoading />;
  }

  if (status === "authenticated") {
    return <AdminConsole />;
  }

  if (status === "unavailable") {
    return <SessionUnavailable onRetry={retrySession} />;
  }

  return <AdminLoginScreen />;
}
