"use client";

/**
 * Tela #relatorios (legada, deep-link — delta-012). Relatórios de célula da
 * semana: um card com os RECEBIDOS e outro com os que faltam entregar.
 *
 * Cada linha é uma REUNIÃO materializada (`celula_reuniao`), nunca uma célula
 * abstrata: célula sem reunião na semana simplesmente não aparece. As abas
 * Semana atual / Histórico trocam a semana ISO consultada.
 *
 * A status-pill (Pendente / Atrasado) reflete o status classificado pelo
 * BACKEND — o SLA de 2h após a reunião roda no servidor, em America/Sao_Paulo.
 * Não há mais cálculo de prazo no cliente; para a pílula migrar sem reload
 * quando a reunião cruza a fronteira do SLA, a aba "Semana atual" rebusca o
 * endpoint a cada 60s (refresh silencioso: sem skeleton e sem limpar a tela).
 *
 * Acesso restrito a pastor/admin (GET /reports exige a Central); um papel sem
 * permissão recebe 403 e a tela mostra o banner de erro.
 *
 * Estados: loading (skeleton) · empty (sem reuniões) · populated · detail (modal).
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
  formatMeetingDate,
  reportSla,
  splitReports,
  type ReportItem,
} from "@/lib/reports-api";

import { ReportDetailModal } from "./ReportDetailModal";

type Tab = "atual" | "historico";

/** Intervalo do refetch da semana corrente (ms) — ver o efeito de polling. */
const REFRESH_MS = 60_000;

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

  const [detail, setDetail] = useState<ReportItem | null>(null);

  // Busca em voo (impede polls concorrentes) e sequência da requisição (impede
  // que uma resposta atrasada sobrescreva o resultado de uma carga mais nova).
  const inFlight = useRef(false);
  const latestRequest = useRef(0);

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
    async (mode: "initial" | "retry" | "refresh") => {
      if (!token) return;
      const background = mode === "refresh";
      // Um poll nunca concorre com uma busca em voo: pula o ciclo e tenta no
      // próximo. Cargas do usuário (initial/retry) não são puladas.
      if (background && inFlight.current) return;
      const requestId = ++latestRequest.current;
      inFlight.current = true;
      if (!background) {
        if (mode === "initial") setLoading(true);
        setError(null);
      }
      try {
        const page = await fetchReports(token, semana);
        // Resposta obsoleta (a semana já mudou, ou uma carga mais nova começou):
        // não escreve nada — senão o histórico sobrescreveria a semana atual.
        if (requestId !== latestRequest.current) return;
        setReports(page.items);
        setLoaded(true);
        setError(null);
      } catch (err) {
        if (handleSessionError(err)) return;
        if (requestId !== latestRequest.current) return;
        // Falha de poll é silenciosa: mantém na tela os dados já carregados,
        // sem piscar banner de erro, e tenta de novo no ciclo seguinte.
        if (!background) {
          setError(
            err instanceof ApiError ? err.message : "Não foi possível carregar os relatórios.",
          );
        }
      } finally {
        if (requestId === latestRequest.current) {
          inFlight.current = false;
          if (!background) setLoading(false);
        }
      }
    },
    [token, semana, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  // O status pendente/atrasado é do BACKEND (SLA de data+hora+2h em São Paulo);
  // nada é recalculado aqui. Para a pílula migrar sem reload quando a reunião
  // cruza a fronteira do SLA com a tela aberta, rebuscamos a semana corrente a
  // cada 60s. Só na aba "Semana atual" — o histórico é fechado e não muda de
  // status. O timer morre ao desmontar ou ao sair da aba (cleanup do efeito).
  useEffect(() => {
    if (tab !== "atual") return;
    const id = window.setInterval(() => {
      void load("refresh");
    }, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [tab, load]);

  const { recebidos, pendentes } = useMemo(() => splitReports(reports), [reports]);

  const showSkeleton = loading && !loaded;
  const reunioesTotal = recebidos.length + pendentes.length;

  const recebidosColumns: Array<Column<ReportItem>> = useMemo(
    () => [
      {
        header: "Célula",
        cell: (r) => <span className="nm">{r.celulaNome ?? "—"}</span>,
      },
      { header: "Reunião", cell: (r) => formatMeetingDate(r.dataReuniao) },
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
      ) : reunioesTotal === 0 ? (
        <div className="card">
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="document" />
            <p>
              <strong>Nenhuma reunião de célula nesta semana.</strong> Os
              relatórios aparecem aqui depois que as reuniões forem agendadas
              pelos líderes.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid-2" style={{ alignItems: "start" }}>
          <div className="card">
            <div className="panel-title">
              <Icon name="check" /> Recebidos
              <span className="count">· {recebidos.length} de {reunioesTotal} reuniões</span>
            </div>
            <DataTable
              columns={recebidosColumns}
              rows={recebidos}
              rowKey={(r) => r.id}
              empty={{
                icon: "document",
                title: "Nenhum relatório recebido ainda.",
                hint: "Os relatórios enviados pelos líderes aparecem aqui.",
              }}
              onRowClick={(r) => setDetail(r)}
            />
          </div>

          <div className="card">
            <div className="panel-title" style={{ color: pendentes.length ? "var(--warn)" : undefined }}>
              <Icon name="alert" /> Pendentes
              <span className="count">· {pendentes.length} reunião(ões)</span>
            </div>
            {pendentes.length === 0 ? (
              <div className="empty-state" style={{ padding: "var(--s5)" }}>
                <Icon name="check" />
                <p>
                  <strong>Tudo em dia!</strong> Todas as reuniões desta semana já
                  tiveram o relatório enviado.
                </p>
              </div>
            ) : (
              <div>
                {pendentes.map((r) => {
                  const sla = reportSla(r);
                  return (
                    <div className={`list-row${sla.overdue ? " overdue" : ""}`} key={r.id}>
                      <div style={{ flex: 1 }}>
                        <div className="nm">{r.celulaNome ?? "—"}</div>
                        <div className="sub">Reunião de {formatMeetingDate(r.dataReuniao)}</div>
                      </div>
                      <StatusPill tone={sla.tone}>{sla.label}</StatusPill>
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
    </div>
  );
}
