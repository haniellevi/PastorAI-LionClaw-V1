"use client";

/**
 * Console Super-Admin autenticado: lista todas as igrejas da plataforma com
 * contadores de membros/pessoas (cross-tenant). Provisionar e alterar
 * status/plano entram na próxima fatia.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { DataTable, type Column } from "@/components/ui/DataTable";
import {
  AdminSessionExpiredError,
  listIgrejas,
  type AdminIgreja,
} from "@/lib/admin-api";
import { useAdminAuth } from "@/lib/admin-auth-context";

const STATUS_LABEL: Record<string, string> = {
  ativa: "Ativa",
  suspensa: "Suspensa",
  aguardando_aprovacao: "Aguardando aprovação",
  inadimplente: "Inadimplente",
};

const PLANO_LABEL: Record<string, string> = {
  ate_100: "Até 100",
  "101_200": "101–200",
  acima_201: "201+",
};

export function AdminConsole() {
  const { admin, token, logout } = useAdminAuth();
  const [igrejas, setIgrejas] = useState<AdminIgreja[] | null>(null);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(undefined);
    try {
      const data = await listIgrejas(token);
      setIgrejas(data);
    } catch (err) {
      if (err instanceof AdminSessionExpiredError) {
        logout();
        return;
      }
      setError("Não foi possível carregar as igrejas.");
    } finally {
      setLoading(false);
    }
  }, [token, logout]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: Array<Column<AdminIgreja>> = [
    { header: "Igreja", cell: (r) => <strong>{r.nome}</strong> },
    { header: "Status", cell: (r) => STATUS_LABEL[r.status] ?? r.status },
    { header: "Plano", cell: (r) => (r.plano ? PLANO_LABEL[r.plano] ?? r.plano : "—") },
    { header: "Membros", numeric: true, cell: (r) => r.membros },
    { header: "Pessoas", numeric: true, cell: (r) => r.pessoas },
  ];

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "var(--s4)" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "var(--s2)",
          marginBottom: "var(--s4)",
        }}
      >
        <div>
          <h1 style={{ margin: 0 }}>Console da Plataforma</h1>
          <p className="sub" style={{ margin: 0 }}>
            {admin ? `${admin.nome} · ${admin.email}` : "Administração multi-igreja"}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={logout}>
          Sair
        </Button>
      </header>

      <div className="card">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "var(--s2)",
            padding: "var(--s3) var(--s4)",
          }}
        >
          <strong>Igrejas{igrejas ? ` (${igrejas.length})` : ""}</strong>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void load()}
            loading={loading}
            loadingText="Atualizando…"
          >
            Atualizar
          </Button>
        </div>

        {error ? (
          <div className="auth-error" role="alert" style={{ margin: "var(--s4)" }}>
            <span>{error}</span>
          </div>
        ) : null}

        {igrejas ? (
          <DataTable
            columns={columns}
            rows={igrejas}
            rowKey={(r) => r.id}
            empty={{
              title: "Nenhuma igreja ainda.",
              hint: "Provisione a primeira pelo console.",
            }}
          />
        ) : loading ? (
          <div style={{ padding: "var(--s6)", textAlign: "center" }}>
            <span className="spinner" aria-hidden="true" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
