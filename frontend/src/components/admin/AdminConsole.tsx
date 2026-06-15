"use client";

/**
 * Console Super-Admin autenticado: lista todas as igrejas da plataforma com
 * contadores (cross-tenant), provisiona novas igrejas (US-43) e altera
 * status/plano (US-42). Clicar numa linha abre a edição.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { DataTable, type Column } from "@/components/ui/DataTable";
import {
  AdminSessionExpiredError,
  createIgreja,
  listIgrejas,
  updateIgreja,
  type AdminIgreja,
  type CreateIgrejaInput,
  type UpdateIgrejaInput,
} from "@/lib/admin-api";
import { useAdminAuth } from "@/lib/admin-auth-context";

import { CreateIgrejaModal } from "./CreateIgrejaModal";
import { EditIgrejaModal } from "./EditIgrejaModal";

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
  const [notice, setNotice] = useState<string>();

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<AdminIgreja | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(undefined);
    try {
      setIgrejas(await listIgrejas(token));
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

  // Expira a sessão de forma centralizada; devolve true se tratou o erro.
  const handledSessionError = useCallback(
    (err: unknown): boolean => {
      if (err instanceof AdminSessionExpiredError) {
        logout();
        return true;
      }
      return false;
    },
    [logout],
  );

  const submitCreate = async (input: CreateIgrejaInput) => {
    if (!token) return;
    setModalBusy(true);
    setModalError(null);
    try {
      const res = await createIgreja(token, input);
      setCreateOpen(false);
      setNotice(
        `Igreja "${input.nome}" criada. Convite ao admin: ${
          res.emailEnviado ? "enviado" : "falhou — reenvie depois"
        }.`,
      );
      await load();
    } catch (err) {
      if (handledSessionError(err)) return;
      setModalError(err instanceof Error ? err.message : "Não foi possível provisionar.");
    } finally {
      setModalBusy(false);
    }
  };

  const submitEdit = async (input: UpdateIgrejaInput) => {
    if (!token || !editing) return;
    setModalBusy(true);
    setModalError(null);
    try {
      await updateIgreja(token, editing.id, input);
      setNotice(`"${editing.nome}" atualizada.`);
      setEditing(null);
      await load();
    } catch (err) {
      if (handledSessionError(err)) return;
      setModalError(err instanceof Error ? err.message : "Não foi possível atualizar.");
    } finally {
      setModalBusy(false);
    }
  };

  const columns: Array<Column<AdminIgreja>> = [
    { header: "Igreja", cell: (r) => <strong>{r.nome}</strong> },
    { header: "Status", cell: (r) => STATUS_LABEL[r.status] ?? r.status },
    { header: "Plano", cell: (r) => (r.plano ? PLANO_LABEL[r.plano] ?? r.plano : "—") },
    { header: "Membros", numeric: true, cell: (r) => r.membros },
    { header: "Pessoas", numeric: true, cell: (r) => r.pessoas },
    { header: "", width: "1px", cell: () => <span className="sub">Editar →</span> },
  ];

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", padding: "var(--s4)" }}>
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

      {notice ? (
        <div
          className="error-banner"
          role="status"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent)",
            marginBottom: "var(--s3)",
          }}
        >
          <span>{notice}</span>
        </div>
      ) : null}

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
          <div style={{ display: "flex", gap: "var(--s2)" }}>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void load()}
              loading={loading}
              loadingText="Atualizando…"
            >
              Atualizar
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setModalError(null);
                setCreateOpen(true);
              }}
            >
              Provisionar igreja
            </Button>
          </div>
        </div>

        {error ? (
          <div className="error-banner" role="alert" style={{ margin: "var(--s4)" }}>
            <span>{error}</span>
          </div>
        ) : null}

        {igrejas ? (
          <DataTable
            columns={columns}
            rows={igrejas}
            rowKey={(r) => r.id}
            onRowClick={(r) => {
              setModalError(null);
              setEditing(r);
            }}
            empty={{
              title: "Nenhuma igreja ainda.",
              hint: "Provisione a primeira no botão acima.",
            }}
          />
        ) : loading ? (
          <div style={{ padding: "var(--s6)", textAlign: "center" }}>
            <span className="spinner" aria-hidden="true" />
          </div>
        ) : null}
      </div>

      {createOpen ? (
        <CreateIgrejaModal
          busy={modalBusy}
          error={modalError}
          onClose={() => setCreateOpen(false)}
          onSubmit={submitCreate}
        />
      ) : null}

      {editing ? (
        <EditIgrejaModal
          igreja={editing}
          busy={modalBusy}
          error={modalError}
          onClose={() => setEditing(null)}
          onSubmit={submitEdit}
        />
      ) : null}
    </div>
  );
}
