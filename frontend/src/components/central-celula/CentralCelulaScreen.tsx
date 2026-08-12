"use client";

/**
 * Central de Célula (Jornada G12 > Discipular > Central de Célula).
 *
 * Superfície da Central — SÓ para pastor/admin (guarda no cliente; a aba já é
 * derivada por permissão), NUNCA dentro de Minha Célula. Casca com 5 abas
 * roláveis (CentralTabs): Dashboard, Gerenciar células, Solicitações, Avisos e
 * Materiais. Cada aba é um painel próprio que consome os endpoints da Central
 * (cell-central-api, cell-requests-api, cell-notices-api, cell-materials-api,
 * multiplicacoes-api). O dashboard é buscado aqui (fonte única dos badges) e
 * recarregado quando uma aba altera o estado (onChanged). Master-detail no
 * desktop e empilhado no mobile, no mesmo código-base.
 */
import { useCallback, useEffect, useState } from "react";

import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsToast, DsToastRegion } from "@/components/ds/Toast";
import { Icon } from "@/lib/icons";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { getDashboard, type CentralDashboard } from "@/lib/cell-central-api";

import { CentralTabs } from "./CentralTabs";
import { DashboardPanel } from "./DashboardPanel";
import { ManageCellsPanel } from "./ManageCellsPanel";
import { RequestsPanel } from "./RequestsPanel";
import { NoticesPanel } from "./NoticesPanel";
import { MaterialsPanel } from "./MaterialsPanel";
import type { CentralTab, CentralToast } from "./types";

export function CentralCelulaScreen() {
  const { token, user, expireSession } = useAuth();
  const isCentral = user?.roles.includes("pastor") || user?.roles.includes("admin") || false;

  const [tab, setTab] = useState<CentralTab>("dashboard");
  const [dashboard, setDashboard] = useState<CentralDashboard | null>(null);
  const [loadingDash, setLoadingDash] = useState(true);
  const [dashError, setDashError] = useState<string | null>(null);

  // Gate 10: sem timer manual — o DsToast é o dono do ciclo de vida (ok
  // auto-dismiss 3600ms; err persistente até fechar), igual ao contrato do
  // Gate 9.1 em Minha Célula.
  const [toast, setToast] = useState<CentralToast | null>(null);
  const flashToast = useCallback((t: CentralToast) => setToast(t), []);

  const loadDashboard = useCallback(
    async (mode: "initial" | "reload") => {
      if (!token || !isCentral) return;
      if (mode === "initial") setLoadingDash(true);
      setDashError(null);
      try {
        const data = await getDashboard(token);
        setDashboard(data);
      } catch (err) {
        if (err instanceof SessionExpiredError) {
          expireSession();
          return;
        }
        setDashError(err instanceof ApiError ? err.message : "Não foi possível carregar o painel da central.");
      } finally {
        setLoadingDash(false);
      }
    },
    [token, isCentral, expireSession],
  );

  useEffect(() => {
    void loadDashboard("initial");
  }, [loadDashboard]);

  const refreshDashboard = useCallback(() => {
    void loadDashboard("reload");
  }, [loadDashboard]);

  // Guarda de papel: a Central é exclusiva de pastor/admin.
  if (!isCentral) {
    return (
      <div className="screen cc" key="central-celula">
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
    <div className="screen cc" key="central-celula">
      <div className="screen-head">
        <div className="titles">
          <h2>Central de Célula</h2>
          <p>Supervisão das células: saúde, relatórios, solicitações, avisos e materiais.</p>
        </div>
      </div>

      <section className="cc-workspace" aria-label="Gestão central das células">
        <CentralTabs active={tab} onChange={setTab} badges={badges}>
          {tab === "dashboard" ? (
            <DashboardPanel
              dashboard={dashboard}
              loading={loadingDash}
              error={dashError}
              onRetry={() => void loadDashboard("initial")}
              onGoTo={setTab}
            />
          ) : null}

          {tab === "cells" && token ? (
            <ManageCellsPanel token={token} onToast={flashToast} onChanged={refreshDashboard} />
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
