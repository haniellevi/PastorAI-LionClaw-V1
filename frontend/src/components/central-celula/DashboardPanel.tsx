"use client";

/**
 * US-22 — Dashboard / WorkQueuePanel da Central. Mostra os contadores do painel
 * (relatórios pendentes, solicitações aguardando, células com alerta,
 * multiplicações pendentes, avisos e materiais recentes) em cards clicáveis que
 * levam à aba correspondente. Estados: loading (skeleton) · empty · erro (retry).
 *
 * Componente presentacional: o `dashboard` é buscado pela casca (fonte única
 * também dos badges das abas) e injetado por props.
 */
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { Icon, type IconKey } from "@/lib/icons";
import type { CentralDashboard } from "@/lib/cell-central-api";
import type { CentralTab } from "./types";

interface CardDef {
  key: keyof CentralDashboard;
  label: string;
  icon: IconKey;
  delta: string;
  /** Aba de destino ao clicar. */
  goTo: CentralTab;
  /** Destaca (alerta) quando o valor for > 0. */
  alertWhenPositive?: boolean;
}

const CARDS: CardDef[] = [
  {
    key: "relatorios_pendentes",
    label: "Relatórios pendentes",
    icon: "document",
    delta: "cobrar líderes",
    goTo: "cells",
    alertWhenPositive: true,
  },
  {
    key: "solicitacoes_aguardando",
    label: "Solicitações aguardando",
    icon: "bell",
    delta: "decidir na fila",
    goTo: "requests",
    alertWhenPositive: true,
  },
  {
    key: "celulas_com_alerta",
    label: "Células com alerta",
    icon: "alert",
    delta: "saúde das células",
    goTo: "cells",
    alertWhenPositive: true,
  },
  {
    key: "multiplicacoes_pendentes",
    label: "Multiplicações pendentes",
    icon: "enviar",
    delta: "aprovar multiplicação",
    goTo: "cells",
    alertWhenPositive: true,
  },
  {
    key: "avisos_recentes",
    label: "Avisos recentes",
    icon: "broadcast",
    delta: "últimos publicados",
    goTo: "notices",
  },
  {
    key: "materiais_recentes",
    label: "Materiais recentes",
    icon: "link",
    delta: "biblioteca de apoio",
    goTo: "materials",
  },
];

export function DashboardPanel({
  dashboard,
  loading,
  error,
  onRetry,
  onGoTo,
}: {
  dashboard: CentralDashboard | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onGoTo: (tab: CentralTab) => void;
}) {
  const showSkeleton = loading && !dashboard;

  return (
    <section className="card" aria-label="Painel da Central">
      <div className="panel-title">
        <Icon name="dashboard" /> Painel da Central
      </div>

      {error ? (
        <DsBanner
          kind="error"
          action={
            <DsButton variant="secondary" onClick={onRetry} disabled={loading}>
              Tentar novamente
            </DsButton>
          }
        >
          {error}
        </DsBanner>
      ) : null}

      <div style={{ padding: "var(--s4)" }}>
        {showSkeleton ? (
          <div className="central-cards">
            {Array.from({ length: 6 }).map((_, i) => (
              <div className="stat skeleton" key={i}>
                <div className="sk-line sk-sm" />
                <div className="sk-line sk-lg" />
              </div>
            ))}
          </div>
        ) : !dashboard ? (
          <DsEmptyState
            illustration={<Icon name="dashboard" />}
            title="Nada por aqui ainda."
            hint="Os contadores aparecem assim que houver movimento nas células."
          />
        ) : (
          <div className="central-cards">
            {CARDS.map((c) => {
              const value = dashboard[c.key] ?? 0;
              const alert = Boolean(c.alertWhenPositive && value > 0);
              return (
                <button
                  key={c.key}
                  type="button"
                  className={`central-card${alert ? " alert" : ""}`}
                  onClick={() => onGoTo(c.goTo)}
                >
                  <div className="cc-lbl">
                    <Icon name={c.icon} />
                    {c.label}
                  </div>
                  <div className="cc-val num">{value}</div>
                  <div className="cc-delta">
                    {alert ? <span className="cc-delta-alert">Atenção · </span> : null}
                    {c.delta}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
