"use client";

/**
 * Raiz da superfície administrativa da igreja (admin.<domínio>, reescrito para
 * /gestao pelo middleware; em dev acessível direto por /gestao). Só admin entra;
 * um usuário autenticado sem papel admin é devolvido ao painel operacional.
 */
import { useEffect } from "react";

import { AdminAppShell } from "@/components/shell/AdminAppShell";
import { LoginScreen } from "@/components/login/LoginScreen";
import { useAuth } from "@/lib/auth-context";
import { isAdmin } from "@/lib/roles";
import { appSurfaceHref } from "@/lib/surface";

export default function GestaoPage() {
  const { status, user } = useAuth();
  const admin = user ? isAdmin(user.roles) : false;

  // Não-admin autenticado nesta superfície volta para o painel operacional.
  useEffect(() => {
    if (status === "authenticated" && user && !admin) {
      window.location.href = appSurfaceHref();
    }
  }, [status, user, admin]);

  if (status === "loading" || (status === "authenticated" && !admin)) {
    return (
      <div className="full-loader" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
          Carregando…
        </span>
      </div>
    );
  }

  if (status === "authenticated" && admin) {
    return <AdminAppShell />;
  }

  return <LoginScreen />;
}
