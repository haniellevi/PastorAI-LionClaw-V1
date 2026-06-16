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
  aprovarIgreja,
  createIgreja,
  deleteIgreja,
  fetchMetrics,
  listIgrejas,
  listPlanos,
  updateIgreja,
  type AdminIgreja,
  type AdminMetrics,
  type AdminPlano,
  type CreateIgrejaInput,
  type UpdateIgrejaInput,
} from "@/lib/admin-api";
import { useAdminAuth } from "@/lib/admin-auth-context";

import { AuditModal } from "./AuditModal";
import { CreateIgrejaModal } from "./CreateIgrejaModal";
import { EditIgrejaModal } from "./EditIgrejaModal";
import { IgrejaDetailModal } from "./IgrejaDetailModal";
import { PlanosManagerModal } from "./PlanosManagerModal";

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

const brl = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card" style={{ padding: "var(--s3)" }}>
      <div className="sub" style={{ color: "var(--muted)" }}>
        {label}
      </div>
      <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{value}</div>
      {hint ? (
        <div className="sub" style={{ color: "var(--muted)" }}>
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export function AdminConsole() {
  const { admin, token, logout } = useAdminAuth();
  const [igrejas, setIgrejas] = useState<AdminIgreja[] | null>(null);
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [planos, setPlanos] = useState<AdminPlano[]>([]);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string>();

  const [createOpen, setCreateOpen] = useState(false);
  const [planosOpen, setPlanosOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [viewing, setViewing] = useState<AdminIgreja | null>(null);
  const [editing, setEditing] = useState<AdminIgreja | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  // Catálogo de planos para os seletores dos modais — best-effort: uma falha
  // aqui não derruba a lista de igrejas (os modais caem no fallback padrão).
  const loadPlanos = useCallback(async () => {
    if (!token) return;
    try {
      setPlanos(await listPlanos(token));
    } catch (err) {
      if (err instanceof AdminSessionExpiredError) logout();
    }
  }, [token, logout]);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(undefined);
    try {
      const [list, mtr] = await Promise.all([listIgrejas(token), fetchMetrics(token)]);
      setIgrejas(list);
      setMetrics(mtr);
    } catch (err) {
      if (err instanceof AdminSessionExpiredError) {
        logout();
        return;
      }
      setError("Não foi possível carregar as igrejas.");
    } finally {
      setLoading(false);
    }
    void loadPlanos();
  }, [token, logout, loadPlanos]);

  useEffect(() => {
    void load();
  }, [load]);

  const activePlanos = planos.filter((p) => p.ativo);

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

  const submitDelete = async () => {
    if (!token || !editing) return;
    setModalBusy(true);
    setModalError(null);
    try {
      await deleteIgreja(token, editing.id);
      setNotice(`Igreja "${editing.nome}" excluída.`);
      setEditing(null);
      await load();
    } catch (err) {
      if (handledSessionError(err)) return;
      setModalError(err instanceof Error ? err.message : "Não foi possível excluir.");
    } finally {
      setModalBusy(false);
    }
  };

  // M2: aprova a igreja em foco no detalhe (aguardando_aprovacao -> ativa).
  const submitAprovar = async () => {
    if (!token || !viewing) return;
    setModalBusy(true);
    setModalError(null);
    try {
      await aprovarIgreja(token, viewing.id);
      setNotice(`Igreja "${viewing.nome}" aprovada e ativada.`);
      setViewing(null);
      await load();
    } catch (err) {
      if (handledSessionError(err)) return;
      setModalError(err instanceof Error ? err.message : "Não foi possível aprovar.");
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
    { header: "", width: "1px", cell: () => <span className="sub">Detalhes →</span> },
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
        <div style={{ display: "flex", gap: "var(--s2)" }}>
          <Button variant="ghost" size="sm" onClick={() => setPlanosOpen(true)}>
            Planos
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setAuditOpen(true)}>
            Auditoria
          </Button>
          <Button variant="ghost" size="sm" onClick={logout}>
            Sair
          </Button>
        </div>
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

      {metrics ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: "var(--s3)",
            marginBottom: "var(--s4)",
          }}
        >
          <MetricCard label="Igrejas" value={String(metrics.totalIgrejas)} />
          <MetricCard label="Ativas" value={String(metrics.porStatus.ativa ?? 0)} />
          <MetricCard
            label="Aguardando aprovação"
            value={String(metrics.porStatus.aguardando_aprovacao ?? 0)}
            hint="provisionadas, a aprovar"
          />
          <MetricCard
            label="Em pendência"
            value={String(
              (metrics.porStatus.suspensa ?? 0) + (metrics.porStatus.inadimplente ?? 0),
            )}
            hint="suspensas + inadimplentes"
          />
          <MetricCard label="MRR" value={brl(metrics.mrr)} hint="igrejas ativas" />
          <MetricCard label="Custo de IA" value={brl(metrics.custoIaTotal)} hint="acumulado" />
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
              setViewing(r);
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
          planos={activePlanos}
          onClose={() => setCreateOpen(false)}
          onSubmit={submitCreate}
        />
      ) : null}

      {planosOpen && token ? (
        <PlanosManagerModal
          token={token}
          onClose={() => setPlanosOpen(false)}
          onExpired={logout}
          onChanged={() => void loadPlanos()}
        />
      ) : null}

      {auditOpen && token ? (
        <AuditModal token={token} onClose={() => setAuditOpen(false)} onExpired={logout} />
      ) : null}

      {viewing && token ? (
        <IgrejaDetailModal
          igreja={viewing}
          token={token}
          approving={modalBusy}
          actionError={modalError}
          onClose={() => setViewing(null)}
          onExpired={logout}
          onApprove={submitAprovar}
          onEdit={() => {
            const target = viewing;
            setViewing(null);
            setModalError(null);
            setEditing(target);
          }}
        />
      ) : null}

      {editing ? (
        <EditIgrejaModal
          igreja={editing}
          busy={modalBusy}
          error={modalError}
          planos={activePlanos}
          onClose={() => setEditing(null)}
          onSubmit={submitEdit}
          onDelete={submitDelete}
        />
      ) : null}
    </div>
  );
}
