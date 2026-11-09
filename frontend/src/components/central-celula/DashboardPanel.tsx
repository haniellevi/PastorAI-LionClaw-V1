"use client";

/**
 * US-22 — primeira dobra da Central. Exceções primeiro (relatório, solicitação,
 * multiplicação, saúde), com a pessoa e o próximo passo. Os totais da igreja
 * ficam recolhidos. Sem endpoint novo: reusa dashboard, pending-reports,
 * requests, multiplicações e health.
 */
import { SupportReveal } from "@/components/brand/SupportReveal";
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { formatLongDate, formatPublishedAt } from "@/components/minha-celula/format";
import { Icon, type IconKey } from "@/lib/icons";
import type { CentralDashboard } from "@/lib/cell-central-api";

import {
  countActionableItems,
  type TodayItem,
  type TodayKind,
} from "./today-queue";
import type { CellsSection, CentralTab } from "./types";

interface CardDef {
  key: keyof CentralDashboard;
  label: string;
  icon: IconKey;
  delta: string;
  goTo: CentralTab;
  section?: CellsSection;
  alertWhenPositive?: boolean;
}

const CARDS: CardDef[] = [
  {
    key: "relatorios_pendentes",
    label: "Relatórios pendentes",
    icon: "document",
    delta: "cobrar líderes",
    goTo: "cells",
    section: "reports",
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

const KIND_VISUAL: Record<TodayKind, { icon: IconKey; cls: "r" | "h" | "v" }> = {
  report: { icon: "document", cls: "r" },
  request: { icon: "bell", cls: "h" },
  multiplication: { icon: "enviar", cls: "v" },
  health: { icon: "alert", cls: "h" },
};

function formatItemMeta(item: TodayItem): string {
  if (item.kind === "report") {
    const [leader, date] = item.meta.split(" · reunião em ");
    return date ? `${leader} · reunião em ${formatLongDate(date)}` : item.meta;
  }
  if (item.kind === "request" || item.kind === "multiplication") {
    return formatPublishedAt(item.meta) || item.meta;
  }
  return item.meta;
}

export function DashboardPanel({
  dashboard,
  queue,
  loading,
  error,
  onRefresh,
  onGoTo,
}: {
  dashboard: CentralDashboard | null;
  queue: TodayItem[] | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onGoTo: (tab: CentralTab, section?: CellsSection) => void;
}) {
  const shownQueue = queue?.slice(0, 8) ?? [];
  const showQueueSkeleton = loading && !queue;
  const loaded = dashboard && queue && !error;
  const pendingCount = countActionableItems(dashboard);
  let status = loading
    ? "Carregando as pendências da Central…"
    : "Não foi possível confirmar as pendências agora.";
  if (loaded) {
    if (pendingCount > 0) {
      status = `${pendingCount} ${pendingCount === 1 ? "pendência pede" : "pendências pedem"} atenção. Abra a pendência, não apenas o número.`;
    } else if (shownQueue.length > 0) {
      status = "A lista tem pendências. Atualize para conferir o total.";
    } else {
      status = loading
        ? "Atualizando as pendências da Central…"
        : "Nenhuma exceção aberta. Os totais da igreja ficam abaixo, se precisar conferir.";
    }
  }

  return (
    <section className="cc-today" aria-label="Hoje na Central">
      <header className="cc-today-head">
        <h3>Hoje na Central</h3>
        <p role="status">{status}</p>
        <DsButton variant="secondary" onClick={onRefresh} loading={loading}>
          Atualizar
        </DsButton>
      </header>

      {error ? (
        <DsBanner
          kind="error"
          action={
            <DsButton variant="secondary" onClick={onRefresh} disabled={loading}>
              Tentar novamente
            </DsButton>
          }
        >
          {error}
        </DsBanner>
      ) : null}

      {showQueueSkeleton ? (
        <div className="cc-today-queue" aria-hidden="true">
          {Array.from({ length: 3 }).map((_, index) => (
            <div className="cc-today-row skeleton" key={index}>
              <span className="cc-today-ic sk-icon" />
              <div className="cc-today-body">
                <div className="sk-line sk-md" />
                <div className="sk-line sk-sm" />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {loaded && shownQueue.length === 0 && !loading ? (
        <DsEmptyState
          illustration={<Icon name="check" />}
          title="Nenhuma pendência na lista carregada."
          hint="Quando um relatório, solicitação ou célula pedir cuidado, aparece aqui."
        />
      ) : null}

      {loaded && shownQueue.length > 0 ? (
        <ul className="cc-today-queue">
          {shownQueue.map((item) => {
            const visual = KIND_VISUAL[item.kind];
            const section = item.kind === "health" ? "health" : item.kind === "report" ? "reports" : undefined;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className="cc-today-row"
                  onClick={() => onGoTo(item.goTo, section)}
                >
                  <span className={`cc-today-ic ${visual.cls}`} aria-hidden="true">
                    <Icon name={visual.icon} />
                  </span>
                  <span className="cc-today-body">
                    <strong>{item.title}</strong>
                    <span className="cc-today-meta">{formatItemMeta(item)}</span>
                  </span>
                  <span className="cc-today-action">{item.action}</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {dashboard && !error ? (
        <SupportReveal>
        <details className="cc-today-summary">
          <summary>Totais da igreja</summary>
          <div className="central-cards">
            {CARDS.map((card) => {
              const value = dashboard[card.key] ?? 0;
              const alert = Boolean(card.alertWhenPositive && value > 0);
              return (
                <button
                  key={card.key}
                  type="button"
                  className={`central-card${alert ? " alert" : ""}`}
                  onClick={() => onGoTo(card.goTo, card.section)}
                >
                  <div className="cc-lbl">
                    <Icon name={card.icon} />
                    {card.label}
                  </div>
                  <div className="cc-val num">{value}</div>
                  <div className="cc-delta">
                    {alert ? <span className="cc-delta-alert">Atenção · </span> : null}
                    {card.delta}
                  </div>
                </button>
              );
            })}
          </div>
        </details>
        </SupportReveal>
      ) : null}
    </section>
  );
}
