"use client";

import "@/components/config/administration-ux-v2.css";

/**
 * Console Super-Admin autenticado: lista todas as igrejas da plataforma com
 * contadores (cross-tenant), provisiona novas igrejas (US-43) e altera
 * status/plano (US-42). Clicar numa linha abre a edição.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { MineralBackdrop } from "@/components/brand/MineralBackdrop";
import { Button } from "@/components/ui/Button";
import { DataTable, type Column } from "@/components/ui/DataTable";
import {
  AdminSessionExpiredError,
  createIgreja,
  fetchMetrics,
  listIgrejas,
  listPlanos,
  type AdminIgreja,
  type AdminMetrics,
  type AdminPlano,
  type CreateIgrejaInput,
} from "@/lib/admin-api";
import { useAdminAuth } from "@/lib/admin-auth-context";
import { formatAiCostUsd } from "@/lib/ai-cost";

import dynamic from "next/dynamic";

// Keep the console and its focused opener mounted while a tool chunk loads.
const AuditModal = dynamic(() => import("./AuditModal").then((module) => module.AuditModal), { loading: () => null });
const ChurchPage = dynamic(() => import("./ChurchPage").then((module) => module.ChurchPage), { loading: () => null });
const CreateIgrejaModal = dynamic(() => import("./CreateIgrejaModal").then((module) => module.CreateIgrejaModal), { loading: () => null });
const JevModal = dynamic(() => import("./JevModal").then((module) => module.JevModal), { loading: () => null });
const OrquestradorModal = dynamic(() => import("./OrquestradorModal").then((module) => module.OrquestradorModal), { loading: () => null });
const PlanosManagerModal = dynamic(() => import("./PlanosManagerModal").then((module) => module.PlanosManagerModal), { loading: () => null });

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
    <div className="platform-metric">
      <div className="sub" style={{ color: "var(--muted)" }}>
        {label}
      </div>
      <div className="platform-metric-value">{value}</div>
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
  const [metricsError, setMetricsError] = useState(false);
  const loadGeneration = useRef(0);
  const [notice, setNotice] = useState<string>();

  const [createOpen, setCreateOpen] = useState(false);
  const [planosOpen, setPlanosOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [orquestradorOpen, setOrquestradorOpen] = useState(false);
  const [jevOpen, setJevOpen] = useState(false);
  const [viewing, setViewing] = useState<AdminIgreja | null>(null);
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
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError(undefined);
    setMetricsError(false);
    void fetchMetrics(token).then((metrics) => {
      if (generation === loadGeneration.current) setMetrics(metrics);
    }).catch((err) => {
      if (generation !== loadGeneration.current) return;
      if (err instanceof AdminSessionExpiredError) logout();
      else setMetricsError(true);
    });
    try {
      const list = await listIgrejas(token);
      if (generation !== loadGeneration.current) return;
      setIgrejas(list);
    } catch (err) {
      if (generation !== loadGeneration.current) return;
      if (err instanceof AdminSessionExpiredError) {
        logout();
        return;
      }
      setError("Não foi possível carregar as igrejas.");
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  }, [token, logout]);

  useEffect(() => {
    void load();
    return () => { loadGeneration.current += 1; };
  }, [load]);

  useEffect(() => {
    if (createOpen || planosOpen) void loadPlanos();
  }, [createOpen, planosOpen, loadPlanos]);

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

  const columns: Array<Column<AdminIgreja>> = [
    { header: "Igreja", cell: (r) => <strong>{r.nome}</strong> },
    { header: "Status", cell: (r) => STATUS_LABEL[r.status] ?? r.status },
    { header: "Plano", cell: (r) => (r.plano ? PLANO_LABEL[r.plano] ?? r.plano : "—") },
    { header: "Membros", numeric: true, cell: (r) => r.membros },
    { header: "Pessoas", numeric: true, cell: (r) => r.pessoas },
    { header: "Ações", cell: (r) => <Button variant="ghost" size="sm"
      aria-label={`Abrir igreja: ${r.nome}`} onClick={() => { setModalError(null); setViewing(r); }}>
      Abrir igreja
    </Button> },
  ];

  // Igreja aberta → página dedicada em tela cheia (substitui o antigo modal).
  if (viewing && token) {
    return (
      <ChurchPage
        igreja={viewing}
        token={token}
        planos={activePlanos}
        onBack={() => setViewing(null)}
        onExpired={logout}
        onChanged={() => void load()}
        onDeleted={() => {
          setViewing(null);
          setNotice("Igreja excluída.");
          void load();
        }}
      />
    );
  }

  return (
    <div className="administration-ux platform-console">
      <header className="platform-head admin-overview mineral-surface" data-mineral-surface>
        <MineralBackdrop compact />
        <div>
          <h1 style={{ margin: 0 }}>Console da Plataforma</h1>
          <p className="platform-guidance">Escolha a igreja antes de administrar seus dados.</p>
          <p className="sub" style={{ margin: 0 }}>
            {admin ? `${admin.nome} · ${admin.email}` : "Administração multi-igreja"}
          </p>
        </div>
        <nav className="platform-tools" aria-label="Operações da plataforma">
          <Button variant="ghost" size="sm" onClick={() => setOrquestradorOpen(true)}>
            Orquestrador
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setJevOpen(true)}>
            Jev
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setPlanosOpen(true)}>
            Planos
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setAuditOpen(true)}>
            Auditoria
          </Button>
          <Button variant="ghost" size="sm" onClick={logout}>
            Sair
          </Button>
        </nav>
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

      {metricsError ? <p className="error-banner" role="alert">Indicadores indisponíveis. A lista de igrejas continua disponível; use Atualizar para tentar novamente.</p> : null}
      {metrics ? (
        <section className="platform-summary" aria-label="Estados das igrejas">
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
        </section>
      ) : null}

      <div className="card">
        <div className="platform-list-head">
          <h2>Igrejas{igrejas ? ` (${igrejas.length})` : ""}</h2>
          <div className="platform-tools">
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
            className="ux-stack-table"
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
          <div role="status" style={{ padding: "var(--s6)", textAlign: "center" }}>
            <span className="spinner" aria-hidden="true" />
            <p>Carregando igrejas…</p>
          </div>
        ) : null}
      </div>

      {metrics ? (
        <details className="admin-disclosure">
          <summary>Financeiro da plataforma</summary>
          <div className="platform-finance">
            <MetricCard label="MRR" value={brl(metrics.mrr)} hint="igrejas ativas" />
            <MetricCard label="Custo de IA" value={formatAiCostUsd(metrics.custoIaTotal)} hint="acumulado, em dólar" />
          </div>
        </details>
      ) : null}

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

      {orquestradorOpen && token ? (
        <OrquestradorModal
          token={token}
          onClose={() => setOrquestradorOpen(false)}
          onExpired={logout}
        />
      ) : null}

      {jevOpen && token ? (
        <JevModal
          token={token}
          igrejas={igrejas?.map(({ id, nome }) => ({ id, nome }))}
          onClose={() => setJevOpen(false)}
          onExpired={logout}
        />
      ) : null}
    </div>
  );
}
