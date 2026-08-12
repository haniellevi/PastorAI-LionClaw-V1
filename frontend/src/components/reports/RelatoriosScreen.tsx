"use client";

/**
 * Tela #relatorios (legada, deep-link — delta-012). Relatórios de célula da
 * semana: um card com os RECEBIDOS e outro com os que faltam entregar.
 *
 * Cada linha é uma REUNIÃO materializada (`celula_reuniao`), nunca uma célula
 * abstrata: célula sem reunião na semana simplesmente não aparece. As abas
 * Semana atual / Histórico trocam a semana ISO consultada — a atual fica a
 * cargo do backend (sem `?semana=`) e o histórico é derivado em
 * `America/Sao_Paulo`, nunca no fuso do navegador.
 *
 * A status-pill (Pendente / Atrasado) reflete o status classificado pelo
 * BACKEND — o SLA de 2h após a reunião roda no servidor, em America/Sao_Paulo.
 * Nada de prazo é calculado no cliente.
 *
 * Um ÚNICO relógio do produto avança a cada 60s e governa as duas coisas que
 * dependem do tempo aqui: qual semana o Histórico consulta e quando refazemos a
 * busca (refresh silencioso, sem skeleton e sem limpar a tela). Vale para as
 * DUAS abas — histórico não é imutável: a reunião de domingo à noite vence o
 * SLA depois da meia-noite, e a virada de segunda promove uma semana nova a
 * histórica.
 *
 * Acesso restrito a pastor/admin (GET /reports exige a Central); um papel sem
 * permissão recebe 403 e a tela mostra o banner de erro.
 *
 * O modal de detalhe guarda o ID da reunião, não o objeto: assim ele acompanha
 * o polling em vez de congelar no status da hora em que foi aberto.
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
  previousIsoWeekInSaoPaulo,
  reportSla,
  splitReports,
  type ReportItem,
} from "@/lib/reports-api";

import { ReportDetailModal } from "./ReportDetailModal";

type Tab = "atual" | "historico";

/** Intervalo do refetch da semana corrente (ms) — ver o efeito de polling. */
const REFRESH_MS = 60_000;

export function RelatoriosScreen() {
  const { token, expireSession } = useAuth();

  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("atual");

  // Guardamos o ID da reunião, não o objeto: o polling troca o array `reports`,
  // e uma cópia congelada deixaria o modal aberto exibindo o status antigo.
  const [detailId, setDetailId] = useState<string | null>(null);

  // Busca em voo (impede polls concorrentes) e sequência da requisição (impede
  // que uma resposta atrasada sobrescreva o resultado de uma carga mais nova).
  const inFlight = useRef(false);
  const latestRequest = useRef(0);

  // Relógio do produto: um único instante que avança a cada tick. Dele saem AS
  // DUAS coisas que dependem do tempo nesta tela — qual semana o Histórico
  // consulta e quando refazemos a busca. Sem ele, a aba aberta na virada de
  // segunda-feira continuaria presa na semana e nos status de antes.
  const [now, setNow] = useState(() => Date.now());

  // Semana atual NÃO manda `?semana=` (o backend resolve a semana corrente em
  // São Paulo); o histórico manda a semana anterior derivada NO MESMO fuso, a
  // partir do relógio acima — pelo fuso do navegador, ou com um instante
  // congelado na montagem, as duas abas acabariam na mesma semana.
  const semana = useMemo(
    () => (tab === "atual" ? undefined : previousIsoWeekInSaoPaulo(new Date(now))),
    [tab, now],
  );

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

  // Espelho sempre atual de `load`, para o efeito do tick não precisar dele nas
  // dependências (senão cada mudança de semana dispararia um refresh extra).
  // Declarado ANTES do efeito do tick: efeitos rodam na ordem de declaração,
  // então quando o refresh acontece o `load` já enxerga a semana recalculada.
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  // Carga dirigida pelo usuário/contexto: montagem, troca de aba e virada de
  // semana (quando `semana` muda, `load` muda junto).
  useEffect(() => {
    void load("initial");
  }, [load]);

  // ÚNICO relógio da tela: avança o instante a cada 60s. Não busca nada aqui —
  // só move o tempo, para a semana do Histórico ser recalculada na renderização
  // antes de qualquer requisição. Morre no unmount.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  // Depois que o tick re-renderizou (semana já recalculada), refaz a busca em
  // silêncio — nas DUAS abas. O status pendente/atrasado é do BACKEND (SLA de
  // data+hora+2h em São Paulo) e nada é recalculado aqui; o Histórico também
  // muda, porque a reunião de domingo à noite vence o SLA depois da meia-noite
  // e porque a virada de segunda promove uma nova semana a histórica.
  // Na virada, `load` muda junto e o efeito acima já dispara a busca da semana
  // nova; a guarda `inFlight` faz este refresh pular o ciclo em vez de duplicar.
  const skipFirstTick = useRef(true);
  useEffect(() => {
    if (skipFirstTick.current) {
      skipFirstTick.current = false;
      return;
    }
    void loadRef.current("refresh");
  }, [now]);

  const { recebidos, pendentes } = useMemo(() => splitReports(reports), [reports]);

  // O item do modal é DERIVADO do array atual: quando o poll traz a mesma
  // reunião já enviada (ou atrasada), o modal aberto acompanha na hora.
  const detail = useMemo(
    () => (detailId ? reports.find((r) => r.id === detailId) ?? null : null),
    [detailId, reports],
  );

  // Reunião sumiu do resultado (mudou de semana, foi cancelada): fecha o modal e
  // esquece o ID — sem isso, um poll futuro que a trouxesse de volta reabriria
  // o diálogo sozinho.
  useEffect(() => {
    if (detailId !== null && !reports.some((r) => r.id === detailId)) {
      setDetailId(null);
    }
  }, [detailId, reports]);

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
              setDetailId(r.id);
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
    <div className="screen operations-screen reports-screen" key="relatorios">
      <div className="screen-head">
        <div className="titles">
          <h2>Relatórios de células</h2>
          <p>Acompanhe o que chegou e o que ainda precisa de cuidado nesta semana.</p>
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
              onRowClick={(r) => setDetailId(r.id)}
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
                      <button type="button" className="btn btn-sm" onClick={() => setDetailId(r.id)}>
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

      {detail ? <ReportDetailModal report={detail} onClose={() => setDetailId(null)} /> : null}
    </div>
  );
}
