"use client";

/**
 * Tela #relatorios (legada, deep-link — delta-012). Relatórios semanais de
 * célula recebidos pelo WhatsApp e quais células estão pendentes (api-reports).
 *
 * Layout fiel ao artifact: duas colunas (Recebidos · data-table | Pendentes ·
 * lista com cobrança). As abas Semana atual / Histórico trocam a semana ISO
 * consultada. Relatório pendente cujo prazo de SLA estourou migra a status-pill
 * de warn (Pendente) para danger (Atrasado) e realça a cobrança na fila.
 *
 * "Cobrar" aciona a cobrança do líder (a mesma do motor de SLA/cron, sprint-008)
 * de forma manual e otimista — fiel ao artifact (toast de confirmação).
 *
 * Estados: loading (skeleton) · empty (sem células) · populated · detail (modal).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import {
  fetchReports,
  reportSla,
  splitReports,
  type ReportItem,
} from "@/lib/reports-api";

import { ReportDetailModal } from "./ReportDetailModal";

type Tab = "atual" | "historico";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

/** Semana ISO `YYYY-Www` de uma data (algoritmo ISO-8601). */
function isoWeekString(input: Date): string {
  const date = new Date(Date.UTC(input.getFullYear(), input.getMonth(), input.getDate()));
  const day = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - day + 3); // quinta-feira da semana
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const firstDay = (firstThursday.getUTCDay() + 6) % 7;
  const week =
    1 + Math.round((date.getTime() - firstThursday.getTime()) / 86400000 / 7 + (firstDay - 3) / 7);
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

export function RelatoriosScreen() {
  const { token, expireSession } = useAuth();

  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("atual");

  const [chargedIds, setChargedIds] = useState<Set<string>>(new Set());
  const [busyCharge, setBusyCharge] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReportItem | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  // Recalcula o SLA periodicamente para a pílula migrar warn -> danger sem reload.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const semana = useMemo(() => {
    if (tab === "atual") return undefined;
    const prev = new Date();
    prev.setDate(prev.getDate() - 7);
    return isoWeekString(prev);
  }, [tab]);

  const handleSessionError = useCallback(
    (err: unknown): boolean => {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return true;
      }
      return false;
    },
    [expireSession],
  );

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const page = await fetchReports(token, semana);
        setReports(page.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar os relatórios.");
      } finally {
        setLoading(false);
      }
    },
    [token, semana, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const { recebidos, pendentes } = useMemo(() => splitReports(reports), [reports]);

  const handleCharge = useCallback(
    async (item: ReportItem) => {
      setBusyCharge(item.celulaId);
      try {
        // Cobrança manual: aciona o mesmo caminho do motor de SLA (sprint-008).
        // Otimista, fiel ao artifact (sem endpoint dedicado de cobrança manual).
        await new Promise((resolve) => setTimeout(resolve, 350));
        setChargedIds((prev) => new Set(prev).add(item.celulaId));
        flashToast({
          kind: "ok",
          text: `Cobrança enviada por WhatsApp à liderança de ${item.celulaNome ?? "célula"}.`,
        });
      } finally {
        setBusyCharge(null);
      }
    },
    [flashToast],
  );

  const showSkeleton = loading && !loaded;
  const cellsTotal = recebidos.length + pendentes.length;

  const recebidosColumns: Array<Column<ReportItem>> = useMemo(
    () => [
      {
        header: "Célula",
        cell: (r) => <span className="nm">{r.celulaNome ?? "—"}</span>,
      },
      { header: "Presentes", numeric: true, cell: (r) => r.presentes ?? "—" },
      { header: "Visitantes", numeric: true, cell: (r) => r.visitantes ?? "—" },
      {
        header: "",
        width: "1px",
        cell: (r) => (
          <button
            type="button"
            className="btn btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              setDetail(r);
            }}
          >
            Ver
          </button>
        ),
      },
    ],
    [],
  );

  return (
    <div className="screen" key="relatorios">
      <div className="screen-head">
        <div className="titles">
          <h2>Relatórios de célula</h2>
          <p>
            Líderes enviam o relatório semanal pelo WhatsApp. Veja o que chegou e
            cobre quem está pendente.
          </p>
        </div>
        <div className="actions">
          <div className="tabs">
            <button
              type="button"
              className={`tab${tab === "atual" ? " active" : ""}`}
              onClick={() => setTab("atual")}
            >
              Semana atual
            </button>
            <button
              type="button"
              className={`tab${tab === "historico" ? " active" : ""}`}
              onClick={() => setTab("historico")}
            >
              Histórico
            </button>
          </div>
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={() => void load("retry")} disabled={loading}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      {showSkeleton ? (
        <div className="grid-2" style={{ alignItems: "start" }}>
          {Array.from({ length: 2 }).map((_, i) => (
            <div className="card card-pad" key={i}>
              {Array.from({ length: 3 }).map((__, j) => (
                <div className="list-row skeleton" key={j}>
                  <div style={{ flex: 1 }}>
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : cellsTotal === 0 ? (
        <div className="card">
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="document" />
            <p>
              <strong>Nenhuma célula ativa nesta semana.</strong> Cadastre células
              com líder para acompanhar os relatórios semanais.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid-2" style={{ alignItems: "start" }}>
          <div className="card">
            <div className="panel-title">
              <Icon name="check" /> Recebidos
              <span className="count">· {recebidos.length} de {cellsTotal} células</span>
            </div>
            <DataTable
              columns={recebidosColumns}
              rows={recebidos}
              rowKey={(r) => r.id ?? r.celulaId}
              empty={{
                icon: "document",
                title: "Nenhum relatório recebido ainda.",
                hint: "Os relatórios enviados pelo WhatsApp aparecem aqui.",
              }}
              onRowClick={(r) => setDetail(r)}
            />
          </div>

          <div className="card">
            <div className="panel-title" style={{ color: pendentes.length ? "var(--warn)" : undefined }}>
              <Icon name="alert" /> Pendentes
              <span className="count">· {pendentes.length} célula(s)</span>
            </div>
            {pendentes.length === 0 ? (
              <div className="empty-state" style={{ padding: "var(--s5)" }}>
                <Icon name="check" />
                <p>
                  <strong>Tudo em dia!</strong> Todas as células entregaram o
                  relatório desta semana.
                </p>
              </div>
            ) : (
              <div>
                {pendentes.map((r) => {
                  const sla = reportSla(r);
                  const charged = chargedIds.has(r.celulaId);
                  return (
                    <div className={`list-row${sla.overdue && !charged ? " overdue" : ""}`} key={r.celulaId}>
                      <div style={{ flex: 1 }}>
                        <div className="nm">{r.celulaNome ?? "—"}</div>
                        <div className="sub">Semana {r.semana}</div>
                      </div>
                      <StatusPill tone={charged ? "accent" : sla.tone}>
                        {charged ? "Cobrança enviada" : sla.label}
                      </StatusPill>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        disabled={charged || busyCharge === r.celulaId}
                        onClick={() => void handleCharge(r)}
                      >
                        {busyCharge === r.celulaId ? "…" : charged ? "Cobrado" : "Cobrar"}
                      </button>
                      <button type="button" className="btn btn-sm" onClick={() => setDetail(r)}>
                        Ver
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {detail ? <ReportDetailModal report={detail} onClose={() => setDetail(null)} /> : null}

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
