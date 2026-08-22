"use client";

/**
 * US-22 — primeira dobra da Central. Exceções primeiro (relatório, solicitação,
 * multiplicação, saúde), com a pessoa e o próximo passo. Os totais da igreja
 * ficam recolhidos. Sem endpoint novo: reusa dashboard, pending-reports,
 * requests, multiplicações e health.
 */
import { useEffect, useMemo, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { formatLongDate, formatPublishedAt } from "@/components/minha-celula/format";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Icon, type IconKey } from "@/lib/icons";
import {
  getHealth,
  getPendingReports,
  type CellHealth,
  type CentralDashboard,
  type PendingReportItem,
} from "@/lib/cell-central-api";
import { listRequests, type CellRequest } from "@/lib/cell-requests-api";
import { ApiError } from "@/lib/dashboard-api";
import {
  getMultiplicacoesList,
  type MultiplicacaoPendente,
} from "@/lib/multiplicacoes-api";

import {
  buildTodayQueue,
  countActionableItems,
  type TodayItem,
  type TodayKind,
} from "./today-queue";
import type { CentralTab } from "./types";

interface CardDef {
  key: keyof CentralDashboard;
  label: string;
  icon: IconKey;
  delta: string;
  goTo: CentralTab;
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
  token,
  dashboard,
  loading,
  error,
  onRetry,
  onGoTo,
}: {
  token: string;
  dashboard: CentralDashboard | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onGoTo: (tab: CentralTab) => void;
}) {
  const { expireSession } = useAuth();
  const [reports, setReports] = useState<PendingReportItem[]>([]);
  const [requests, setRequests] = useState<CellRequest[]>([]);
  const [multiplications, setMultiplications] = useState<MultiplicacaoPendente[]>([]);
  const [health, setHealth] = useState<CellHealth[]>([]);
  const [queueLoading, setQueueLoading] = useState(true);
  const [queueLoaded, setQueueLoaded] = useState(false);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [queueNonce, setQueueNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setReports([]);
    setRequests([]);
    setMultiplications([]);
    setHealth([]);
    setQueueLoading(true);
    setQueueLoaded(false);
    setQueueError(null);

    Promise.all([
      getPendingReports(token, 1, 8),
      listRequests(token, "aguardando", 1, 8),
      getMultiplicacoesList(token),
      getHealth(token, 1, 12),
    ])
      .then(([reportPage, requestPage, multiplicationList, healthList]) => {
        if (cancelled) return;
        setReports(reportPage.items);
        setRequests(requestPage.items);
        setMultiplications(multiplicationList.pendentes);
        setHealth(healthList.cells);
        setQueueLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof SessionExpiredError) {
          expireSession();
          return;
        }
        setQueueError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar o que precisa de atenção hoje.",
        );
      })
      .finally(() => {
        if (!cancelled) setQueueLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [token, expireSession, queueNonce]);

  const queue = useMemo(
    () =>
      buildTodayQueue({
        reports,
        requests,
        multiplications,
        health,
      }),
    [reports, requests, multiplications, health],
  );

  const shownQueue = queue.slice(0, 8);
  const showQueueSkeleton = queueLoading && !queueLoaded;
  const showTotalsSkeleton = loading && !dashboard;
  const pendingCount = countActionableItems(dashboard);

  return (
    <section className="cc-today" aria-label="Hoje na Central">
      <header className="cc-today-head">
        <h3>Hoje na Central</h3>
        <p>
          {pendingCount > 0
            ? `${pendingCount} ${pendingCount === 1 ? "pendência pede" : "pendências pedem"} atenção. Abra a pendência, não apenas o número.`
            : "Nenhuma exceção aberta. Os totais da igreja ficam abaixo, se precisar conferir."}
        </p>
      </header>

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

      {queueError ? (
        <DsBanner
          kind="degraded"
          action={
            <DsButton
              variant="secondary"
              onClick={() => setQueueNonce((nonce) => nonce + 1)}
              disabled={queueLoading}
            >
              Tentar novamente
            </DsButton>
          }
        >
          {queueError}
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
      ) : shownQueue.length === 0 ? (
        <DsEmptyState
          illustration={<Icon name="check" />}
          title="Fila da Central zerada."
          hint="Quando um relatório, solicitação ou célula pedir cuidado, aparece aqui."
        />
      ) : (
        <ul className="cc-today-queue">
          {shownQueue.map((item) => {
            const visual = KIND_VISUAL[item.kind];
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className="cc-today-row"
                  onClick={() => onGoTo(item.goTo)}
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
      )}

      {!showTotalsSkeleton && dashboard ? (
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
                  onClick={() => onGoTo(card.goTo)}
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
      ) : null}
    </section>
  );
}
