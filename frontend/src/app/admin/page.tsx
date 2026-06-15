"use client";

/**
 * Raiz do console Super-Admin (rota /admin). Decide entre o login do console e
 * o console autenticado. Superfície separada do painel da igreja (PRD: US-42/43
 * em superfície própria, fora do painel operacional).
 */
import { AdminConsole } from "@/components/admin/AdminConsole";
import { AdminLoginScreen } from "@/components/admin/AdminLoginScreen";
import { useAdminAuth } from "@/lib/admin-auth-context";

export default function AdminPage() {
  const { status } = useAdminAuth();

  if (status === "loading") {
    return (
      <div className="full-loader" role="status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <span
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            overflow: "hidden",
            clip: "rect(0 0 0 0)",
          }}
        >
          Carregando sessão…
        </span>
      </div>
    );
  }

  if (status === "authenticated") {
    return <AdminConsole />;
  }

  return <AdminLoginScreen />;
}
