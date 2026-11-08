"use client";

import "../cells/operations-ux-v2.css";

/**
 * Central de Célula (Jornada G12 > Discipular > Central de Célula).
 *
 * Superfície da Central — SÓ para pastor/admin (guarda no cliente; a aba já é
 * derivada por permissão), NUNCA dentro de Minha Célula. Casca com 5 abas
 * roláveis (CentralTabs): Dashboard, Gerenciar células, Solicitações, Avisos e
 * Materiais. Cada aba é um painel próprio que consome os endpoints da Central
 * (cell-central-api, cell-requests-api, cell-notices-api, cell-materials-api,
 * multiplicacoes-api). O dashboard é buscado aqui (fonte única dos badges) e
 * recarregado com a fila ao abrir ou atualizar Hoje.
 * Master-detail no desktop e empilhado no mobile, no mesmo código-base.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsToast, DsToastRegion } from "@/components/ds/Toast";
import { Icon } from "@/lib/icons";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { getDashboard, getHealth, getPendingReports, type CentralDashboard } from "@/lib/cell-central-api";
import { listRequests } from "@/lib/cell-requests-api";
import { getMultiplicacoesList } from "@/lib/multiplicacoes-api";

import { VisitCellSuggestions } from "../contacts/VisitCellSuggestions";
import { CentralTabs } from "./CentralTabs";
import { DashboardPanel } from "./DashboardPanel";
import { ManageCellsPanel } from "./ManageCellsPanel";
import { RequestsPanel } from "./RequestsPanel";
import { NoticesPanel } from "./NoticesPanel";
import { MaterialsPanel } from "./MaterialsPanel";
import { buildTodayQueue, type TodayItem } from "./today-queue";
import type { CentralTab, CentralToast } from "./types";

function readValue<T>(result: PromiseSettledResult<T>): T {
  if (result.status === "rejected") throw result.reason;
  return result.value;
}

async function readToday(token: string, summary: Promise<CentralDashboard>) {
  // Keep the refresh in flight until every read has finished, even on error.
  const results = await Promise.allSettled([
    summary,
    getPendingReports(token, 1, 8),
    listRequests(token, "aguardando", 1, 8),
    getMultiplicacoesList(token),
    getHealth(token, 1, 12),
  ]);
  for (const result of results) {
    if (result.status === "rejected" && result.reason instanceof SessionExpiredError) throw result.reason;
  }
  const [dashboard, reports, requests, multiplications, health] = results;
  return {
    dashboard: readValue(dashboard),
    queue: buildTodayQueue({
      reports: readValue(reports).items,
      requests: readValue(requests).items,
      multiplications: readValue(multiplications).pendentes,
      health: readValue(health).cells,
    }),
  };
}

export function CentralCelulaScreen() {
  const { token, user, expireSession } = useAuth();
  const isCentral = user?.roles.includes("pastor") || user?.roles.includes("admin") || false;

  const [tab, setTab] = useState<CentralTab>("dashboard");
  const [revealHealth, setRevealHealth] = useState(false);
  const [dashboard, setDashboard] = useState<CentralDashboard | null>(null);
  const [queue, setQueue] = useState<TodayItem[] | null>(null);
  const [loadingToday, setLoadingToday] = useState(true);
  const [todayError, setTodayError] = useState<string | null>(null);
  const activeTab = useRef<CentralTab>("dashboard");
  const activeToken = useRef<string | null>(null);
  const activeRequest = useRef<{ summary: Promise<CentralDashboard> } | null>(null);

  // Gate 10: sem timer manual — o DsToast é o dono do ciclo de vida (ok
  // auto-dismiss 3600ms; err persistente até fechar), igual ao contrato do
  // Gate 9.1 em Minha Célula.
  const [toast, setToast] = useState<CentralToast | null>(null);
  const flashToast = useCallback((t: CentralToast) => setToast(t), []);

  const loadDashboard = useCallback(async (
    mode: "initial" | "refresh" | "changed" | "badge",
    summaryInFlight?: Promise<CentralDashboard>,
  ) => {
    if (!token || activeToken.current !== token || !isCentral || (mode === "refresh" && activeRequest.current)) return;
    const request = { summary: summaryInFlight ?? getDashboard(token) };
    activeRequest.current = request;
    if (mode !== "badge") {
      setLoadingToday(true);
      setTodayError(null);
      if (mode === "initial") setQueue(null);
    }

    try {
      if (mode === "badge") {
        const data = await request.summary;
        if (activeRequest.current === request) setDashboard(data);
        return;
      }
      const data = await readToday(token, request.summary);
      if (activeRequest.current !== request) return;
      setDashboard(data.dashboard);
      setQueue(data.queue);
    } catch (err: unknown) {
      if (activeRequest.current !== request) return;
      setDashboard(null);
      if (err instanceof SessionExpiredError) {
        setQueue(null);
        expireSession();
      } else if (mode !== "badge") {
        setQueue(null);
        setTodayError(err instanceof ApiError ? err.message : "Não foi possível confirmar as pendências da Central.");
      }
    } finally {
      if (activeRequest.current === request) {
        activeRequest.current = null;
        if (mode !== "badge") setLoadingToday(false);
      }
    }
  }, [token, isCentral, expireSession]);

  useEffect(() => {
    activeToken.current = isCentral ? token : null;
    setDashboard(null);
    void loadDashboard(activeTab.current === "dashboard" ? "initial" : "badge");
    return () => {
      activeToken.current = null;
      activeRequest.current = null;
    };
  }, [token, isCentral, loadDashboard]);

  const refreshToday = useCallback(() => {
    if (activeTab.current === "dashboard" && document.visibilityState !== "hidden") {
      void loadDashboard("refresh");
    }
  }, [loadDashboard]);

  useEffect(() => {
    if (tab !== "dashboard" || !isCentral || !token) return;
    window.addEventListener("focus", refreshToday);
    document.addEventListener("visibilitychange", refreshToday);
    return () => {
      window.removeEventListener("focus", refreshToday);
      document.removeEventListener("visibilitychange", refreshToday);
    };
  }, [tab, isCentral, token, refreshToday]);

  const openTab = useCallback((nextTab: CentralTab, showHealth = false) => {
    const previousTab = activeTab.current;
    activeTab.current = nextTab;
    if (nextTab === "dashboard" && previousTab !== "dashboard") void loadDashboard("initial");
    if (nextTab !== "dashboard" && previousTab === "dashboard" && activeRequest.current) {
      // The other tabs still use the summary for their badges.
      void loadDashboard("badge", activeRequest.current.summary);
    }
    setRevealHealth(nextTab === "cells" && showHealth);
    setTab(nextTab);
  }, [loadDashboard]);

  const refreshDashboard = useCallback(() => {
    void loadDashboard(activeTab.current === "dashboard" ? "changed" : "badge");
  }, [loadDashboard]);

  // Guarda de papel: a Central é exclusiva de pastor/admin.
  if (!isCentral) {
    return (
      <div className="screen cc access-screen" key="central-celula">
        <div className="card">
          <DsEmptyState
            illustration={<Icon name="lock" />}
            title="Acesso restrito"
            hint="A Central de Célula é exclusiva de pastores e administradores."
          />
        </div>
      </div>
    );
  }

  const badges: Partial<Record<CentralTab, number>> = {
    requests: dashboard?.solicitacoes_aguardando ?? 0,
  };

  return (
    <div className="screen cc ops-v2" key="central-celula">
      <div className="screen-head">
        <div className="titles">
          <h2>Central de Célula</h2>
          <p>Veja quem precisa de atenção hoje e decida o próximo passo de cada célula.</p>
        </div>
      </div>

      <section className="cc-workspace" aria-label="Gestão central das células">
        {tab === "dashboard" ? <VisitCellSuggestions onConfirmed={refreshDashboard} /> : null}
        <CentralTabs active={tab} onChange={openTab} badges={badges}>
          {tab === "dashboard" && token ? (
            <DashboardPanel
              dashboard={queue ? dashboard : null}
              queue={queue}
              loading={loadingToday}
              error={todayError}
              onRefresh={refreshToday}
              onGoTo={openTab}
            />
          ) : null}

          {tab === "cells" && token ? (
            <ManageCellsPanel token={token} onToast={flashToast} onChanged={refreshDashboard} revealHealth={revealHealth} />
          ) : null}

          {tab === "requests" && token ? (
            <RequestsPanel token={token} onToast={flashToast} onChanged={refreshDashboard} />
          ) : null}

          {tab === "notices" && token ? (
            <NoticesPanel token={token} onToast={flashToast} onChanged={refreshDashboard} />
          ) : null}

          {tab === "materials" && token ? (
            <MaterialsPanel token={token} onToast={flashToast} onChanged={refreshDashboard} />
          ) : null}
        </CentralTabs>
      </section>

      <DsToastRegion>
        {toast ? (
          toast.kind === "ok" ? (
            <DsToast kind="ok" text={toast.text} duration={3600} onDismiss={() => setToast(null)} />
          ) : (
            <DsToast kind="err" text={toast.text} onDismiss={() => setToast(null)} />
          )
        ) : null}
      </DsToastRegion>
    </div>
  );
}
