"use client";

/**
 * Raiz da superfície administrativa da igreja (admin.<domínio>, reescrito para
 * /gestao pelo middleware; em dev acessível direto por /gestao). Só admin entra;
 * um usuário autenticado sem papel admin é devolvido ao painel operacional.
 */
import dynamic from "next/dynamic";
import { useEffect } from "react";

import { AppProviders } from "@/components/providers/AppProviders";
import { useAuth } from "@/lib/auth-context";
import { isAdmin } from "@/lib/roles";
import { appSurfaceHref } from "@/lib/surface";

const AdminAppShell = dynamic(
  () => import("@/components/shell/AdminAppShell").then((module) => module.AdminAppShell),
  { loading: PageLoading },
);
const LoginScreen = dynamic(
  () => import("@/components/login/LoginScreen").then((module) => module.LoginScreen),
  { loading: PageLoading },
);

export default function GestaoPage() {
  return (
    <AppProviders>
      <GestaoContent />
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

function GestaoContent() {
  const { status, user } = useAuth();
  const admin = user ? isAdmin(user.roles) : false;

  // Não-admin autenticado nesta superfície volta para o painel operacional.
  useEffect(() => {
    if (status === "authenticated" && user && !admin) {
      window.location.href = appSurfaceHref();
    }
  }, [status, user, admin]);

  if (status === "loading" || (status === "authenticated" && !admin)) {
    return <PageLoading />;
  }

  if (status === "authenticated" && admin) {
    return <AdminAppShell />;
  }

  return <LoginScreen />;
}
