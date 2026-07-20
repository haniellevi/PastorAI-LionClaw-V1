"use client";

/**
 * Tela #dashboard — fila de trabalho pastoral (SPEC screen `dashboard`).
 *
 * Gate 7 (Onda 4A · Diamante Lapidado): o painel opera como FILA pastoral —
 * a fila domina a primeira dobra (desktop e mobile); resumo da semana e KPIs
 * viram disclosure DEPOIS da fila (<details> nativo); jornada e próximas
 * ações ficam na rail secundária. Nenhum dado, ação, callback ou regra de
 * urgência mudou — só a hierarquia visual.
 *
 *  - work-queue-item por tipo com ações diretas (assumir/atribuir/mensagem/
 *    conectar à célula/fonovisita), consumindo api-queue-action, api-link-cell,
 *    api-pipeline e api-send-internal-message;
 *  - deadline-badge que transiciona dentro->alerta->atrasado sem reload e
 *    reordena a fila por urgência (tick periódico);
 *  - próximas ações por responsável.
 *
 * Estados: loading / empty / populated. Falha ao carregar mostra banner de erro
 * com "tentar novamente" preservando o último conteúdo carregado.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsField } from "@/components/ds/Field";
import { DsToastRegion } from "@/components/ds/Toast";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  StaleItemError,
  fetchCells,
  fetchOverview,
  fetchTeamLookup,
  fetchWorkQueue,
  linkCell,
  queueAction,
  queueFonovisita,
  sendInternalMessage,
  type Cell,
  type OverviewStats,
  type TeamMember,
  type WorkItem,
} from "@/lib/dashboard-api";
import { compareUrgency } from "@/lib/deadline";
import { Icon, type IconKey } from "@/lib/icons";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { isLeader } from "@/lib/roles";
import { useHashRoute } from "@/lib/use-hash-route";

import { NextActions } from "./NextActions";
import { WorkQueueItem } from "./WorkQueueItem";

const TICK_MS = 30_000;
const RESOLVE_ANIM_MS = 220;

type Tab = "todos" | "meus";
type ModalKind = "assign" | "message" | "linkCell";

interface ModalState {
  kind: ModalKind;
  item: WorkItem;
}

interface Toast {
  kind: "ok" | "err";
  text: string;
}

/** Linha do resumo da semana. `value` undefined = dado indisponível ("—"). */
interface SummaryRow {
  key: string;
  label: string;
  icon: IconKey;
  value: number | undefined;
  sub: string;
  /** Rota de destino; null = linha informativa sem navegação (KPIs). */
  target: string | null;
}

export function DashboardScreen() {
  const { user, token, expireSession } = useAuth();
  const { matrix } = usePermissions();
  const [, navigate] = useHashRoute();

  const [items, setItems] = useState<WorkItem[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [cells, setCells] = useState<Cell[]>([]);
  const [overview, setOverview] = useState<OverviewStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [tab, setTab] = useState<Tab>("todos");

  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [resolvingIds, setResolvingIds] = useState<Set<string>>(new Set());
  const [conflicts, setConflicts] = useState<Record<string, string>>({});
  const [modal, setModal] = useState<ModalState | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  const leader = user ? isLeader(user.roles) : false;
  const memberById = useMemo(
    () => new Map(members.map((m) => [m.usuarioId, m])),
    [members],
  );

  // ---- carga de dados -----------------------------------------------------
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
        const [queue, team, cellPage, ov] = await Promise.all([
          fetchWorkQueue(token),
          fetchTeamLookup(token),
          fetchCells(token),
          // Visão geral (#2) é aditiva: uma falha não derruba a fila.
          fetchOverview(token).catch(() => null),
        ]);
        setItems(queue.items);
        setMembers(team.items);
        setCells(cellPage.items);
        setOverview(ov);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        const message =
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar a fila de trabalho.";
        setError(message);
      } finally {
        setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    if (!leader) {
      setLoading(false);
      return;
    }
    void load("initial");
  }, [leader, load]);

  // ---- tick para transição de prazos (sem reload) -------------------------
  useEffect(() => {
    if (!leader) return;
    const id = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, [leader]);

  // ---- toast efêmero ------------------------------------------------------
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

  // ---- itens abertos, filtrados e ordenados -------------------------------
  const openItems = useMemo(
    () => items.filter((i) => i.status !== "resolvido"),
    [items],
  );

  const visibleItems = useMemo(() => {
    const filtered =
      tab === "meus" && user
        ? openItems.filter((i) => i.responsavelId === user.appUserId)
        : openItems;
    return [...filtered].sort((a, b) => compareUrgency(a, b, now));
  }, [openItems, tab, user, now]);

  // ---- hero: saudação + data + nº de ações pendentes ----------------------
  const firstName = user?.nome ? user.nome.trim().split(/\s+/)[0] : "";
  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite";
  }, []);
  const todayLabel = useMemo(() => {
    const full = new Date().toLocaleDateString("pt-BR", {
      weekday: "long",
      day: "2-digit",
      month: "long",
      year: "numeric",
    });
    return full.charAt(0).toUpperCase() + full.slice(1);
  }, []);
  const acoesHoje = openItems.length;

  // ---- resumo da semana (dados reais; sem deltas inventados) ---------------
  const relatoriosPendentes = useMemo(
    () => openItems.filter((i) => i.tipo === "relatorio").length,
    [openItems],
  );
  const membros = overview?.porTipo?.membro;
  const summaryRows: SummaryRow[] = [
    {
      key: "visitantes",
      label: "Visitantes novos",
      icon: "ganhar",
      value: overview?.porTipo?.visitante,
      sub: "no funil de Ganhar",
      target: "ganhar",
    },
    {
      key: "consolidar",
      label: "Em consolidação",
      icon: "consolidar",
      value: overview?.porEtapa?.consolidar,
      sub: "na trilha de Consolidar",
      target: "consolidar",
    },
    {
      key: "celulas",
      label: "Células ativas",
      icon: "discipular",
      value: overview?.celulasAtivas,
      sub: membros != null ? `${membros} membros` : "com líder",
      target: "celulas",
    },
    {
      key: "relatorios",
      label: "Relatórios pendentes",
      icon: "document",
      value: relatoriosPendentes,
      sub: "células nesta semana",
      target: "relatorios",
    },
    {
      key: "decisoes",
      label: "Decisões por Jesus",
      icon: "check",
      value: overview?.decisoesJesus,
      sub: "decisões registradas",
      target: null,
    },
    {
      key: "csim",
      label: "Fora da igreja",
      icon: "alert",
      value: overview?.semInteresse,
      sub: "fora do funil",
      target: null,
    },
  ];

  // ---- helpers de mutação -------------------------------------------------
  const removeWithAnim = useCallback((id: string) => {
    setResolvingIds((prev) => new Set(prev).add(id));
    window.setTimeout(() => {
      setItems((prev) => prev.filter((i) => i.id !== id));
      setResolvingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, RESOLVE_ANIM_MS);
  }, []);

  const patchItem = useCallback((id: string, patch: Partial<WorkItem>) => {
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  }, []);

  const clearConflict = useCallback((id: string) => {
    setConflicts((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const handleStale = useCallback(
    (item: WorkItem, err: StaleItemError) => {
      const name =
        (err.responsavelId && memberById.get(err.responsavelId)?.nome) ||
        "outro usuário";
      setConflicts((prev) => ({ ...prev, [item.id]: `Já tratado por ${name}` }));
      patchItem(item.id, {
        status: err.itemStatus ?? "assumido",
        responsavelId: err.responsavelId ?? item.responsavelId,
      });
    },
    [memberById, patchItem],
  );

  // ---- ações --------------------------------------------------------------
  const handleAssume = useCallback(
    async (item: WorkItem) => {
      if (!token || !user) return;
      setBusyItemId(item.id);
      clearConflict(item.id);
      try {
        const res = await queueAction(token, item.id, "assume");
        patchItem(item.id, { status: res.status, responsavelId: res.responsavelId });
        flashToast({ kind: "ok", text: "Item assumido." });
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof StaleItemError) {
          handleStale(item, err);
          return;
        }
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível assumir.",
        });
      } finally {
        setBusyItemId(null);
      }
    },
    [token, user, clearConflict, patchItem, flashToast, handleSessionError, handleStale],
  );

  const handleAssign = useCallback(
    async (item: WorkItem, responsavelId: string) => {
      if (!token) return;
      setBusyItemId(item.id);
      clearConflict(item.id);
      setModal(null);
      try {
        const res = await queueAction(token, item.id, "assign", responsavelId);
        patchItem(item.id, { status: res.status, responsavelId: res.responsavelId });
        const name = memberById.get(responsavelId)?.nome ?? "responsável";
        flashToast({ kind: "ok", text: `Atribuído a ${name}.` });
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof StaleItemError) {
          handleStale(item, err);
          return;
        }
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível atribuir.",
        });
      } finally {
        setBusyItemId(null);
      }
    },
    [token, clearConflict, patchItem, memberById, flashToast, handleSessionError, handleStale],
  );

  const handleMessage = useCallback(
    async (item: WorkItem, mensagem: string) => {
      if (!token) return;
      setBusyItemId(item.id);
      setModal(null);
      try {
        await sendInternalMessage(token, item.id, mensagem);
        flashToast({ kind: "ok", text: "Mensagem enviada pelo WhatsApp." });
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível enviar.",
        });
      } finally {
        setBusyItemId(null);
      }
    },
    [token, flashToast, handleSessionError],
  );

  const handleLinkCell = useCallback(
    async (item: WorkItem, celulaId: string) => {
      if (!token || !item.pessoaId) return;
      setBusyItemId(item.id);
      setModal(null);
      try {
        await linkCell(token, item.pessoaId, celulaId);
        flashToast({ kind: "ok", text: "Conectado à célula." });
        removeWithAnim(item.id);
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível conectar.",
        });
      } finally {
        setBusyItemId(null);
      }
    },
    [token, flashToast, removeWithAnim, handleSessionError],
  );

  const handleFonovisita = useCallback(
    async (item: WorkItem) => {
      if (!token || !item.pessoaId) {
        flashToast({ kind: "err", text: "Item sem pessoa associada." });
        return;
      }
      setBusyItemId(item.id);
      try {
        await queueFonovisita(token, item.pessoaId);
        flashToast({ kind: "ok", text: "Fonovisita registrada na trilha." });
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível agendar.",
        });
      } finally {
        setBusyItemId(null);
      }
    },
    [token, flashToast, handleSessionError],
  );

  // ---- view de membro (sem papel de liderança) ----------------------------
  if (!leader) {
    return <MemberWelcome />;
  }

  const showSkeleton = loading && !loaded;
  const isEmpty = loaded && visibleItems.length === 0;

  return (
    <div className="screen dashboard dh" key="dashboard">
      {/* Cabeçalho curto e calmo: data · saudação · contador real · Atualizar. */}
      <header className="dh-hero">
        <div className="dh-greet">
          <p className="dh-date">{todayLabel}</p>
          <h2 className="dh-title">
            {greeting}
            {firstName ? `, ${firstName}` : ""}
          </h2>
          {showSkeleton ? (
            <div className="sk-line sk-md" />
          ) : acoesHoje > 0 ? (
            <p className="dh-lead">
              Você tem{" "}
              <strong>
                {acoesHoje} {acoesHoje === 1 ? "ação" : "ações"}
              </strong>{" "}
              que {acoesHoje === 1 ? "precisa" : "precisam"} de atenção hoje.
            </p>
          ) : (
            <p className="dh-lead">Nenhuma ação pastoral pendente agora.</p>
          )}
        </div>
        <DsButton
          variant="secondary"
          onClick={() => void load("retry")}
          disabled={loading}
        >
          Atualizar
        </DsButton>
      </header>

      {error ? (
        <DsBanner
          kind="error"
          action={
            <DsButton
              variant="secondary"
              onClick={() => void load("retry")}
              disabled={loading}
            >
              Tentar novamente
            </DsButton>
          }
        >
          {error}
        </DsBanner>
      ) : null}

      <div className="dh-grid">
        {/* Coluna principal: a fila domina a primeira dobra. */}
        <section className="dh-main" aria-label="Fila de trabalho pastoral">
          <div className="dh-queue-head">
            <div className="dh-queue-titles">
              <h3 className="dh-queue-title">Fila de trabalho pastoral</h3>
              <p className="dh-queue-sub">o que exige ação hoje</p>
            </div>
            <div className="dh-filter" role="group" aria-label="Filtrar fila">
              <button
                type="button"
                className={`dh-filter-btn${tab === "todos" ? " active" : ""}`}
                aria-pressed={tab === "todos"}
                onClick={() => setTab("todos")}
              >
                Todos
              </button>
              <button
                type="button"
                className={`dh-filter-btn${tab === "meus" ? " active" : ""}`}
                aria-pressed={tab === "meus"}
                onClick={() => setTab("meus")}
              >
                Meus
              </button>
            </div>
          </div>

          {showSkeleton ? (
            <div className="dh-queue">
              {Array.from({ length: 4 }).map((_, i) => (
                <div className="dh-item skeleton" key={i}>
                  <span className="dh-avatar sk-icon" />
                  <div className="dh-item-body">
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : isEmpty ? (
            <DsEmptyState
              title="Fila zerada."
              hint="Nenhuma pendência pastoral aberta agora."
            />
          ) : (
            <div className="dh-queue">
              {visibleItems.map((item) => (
                <WorkQueueItem
                  key={item.id}
                  item={item}
                  now={now}
                  responsibleName={
                    item.responsavelId
                      ? memberById.get(item.responsavelId)?.nome ?? null
                      : null
                  }
                  busy={busyItemId === item.id}
                  resolving={resolvingIds.has(item.id)}
                  conflict={conflicts[item.id] ?? null}
                  onAssume={handleAssume}
                  onAssign={(it) => setModal({ kind: "assign", item: it })}
                  onMessage={(it) => setModal({ kind: "message", item: it })}
                  onLinkCell={(it) => setModal({ kind: "linkCell", item: it })}
                  onFonovisita={handleFonovisita}
                />
              ))}
            </div>
          )}

          {/* Resumo da semana: DEPOIS da fila, recolhido por padrão
              (disclosure nativa <details> — mesmos dados dos antigos tiles/KPIs). */}
          {!showSkeleton ? (
            <details className="dh-summary">
              <summary className="dh-summary-toggle">Resumo da semana</summary>
              <div className="dh-summary-body">
                {summaryRows.map((row) => (
                  <SummaryLine
                    key={row.key}
                    row={row}
                    canNavigate={
                      row.target != null && user
                        ? canSee(row.target, user.roles, matrix)
                        : false
                    }
                    onNavigate={navigate}
                  />
                ))}
              </div>
            </details>
          ) : null}
        </section>

        {/* Rail secundária: jornada real da semana + próximas ações reais. */}
        <aside className="dh-side">
          {showSkeleton ? (
            <div className="dh-panel">
              <div className="sk-line sk-md" />
              <div className="sk-line sk-sm" />
            </div>
          ) : (
            <>
              <JourneyCard
                overview={overview}
                canSeeAgente={user ? canSee("agente", user.roles, matrix) : false}
                canNavigate={(target) => (user ? canSee(target, user.roles, matrix) : false)}
                onNavigate={navigate}
              />
              <NextActions items={openItems} members={members} />
            </>
          )}
        </aside>
      </div>

      {modal ? (
        <ActionModal
          modal={modal}
          members={members}
          cells={cells}
          onClose={() => setModal(null)}
          onAssign={handleAssign}
          onMessage={handleMessage}
          onLinkCell={handleLinkCell}
        />
      ) : null}

      {/* Feedback: visual da fundação; COMPORTAMENTO atual preservado
          (ok e err somem em 3200ms via flashToast — DsToast mudaria o err
          para persistente, o que seria delta funcional). */}
      <DsToastRegion>
        {toast ? (
          <div className={`ds-toast ds-toast--${toast.kind}`} role="status">
            <span className="ds-toast-icon" aria-hidden="true">
              <Icon name={toast.kind === "ok" ? "check" : "alert"} />
            </span>
            <span className="ds-toast-text">{toast.text}</span>
          </div>
        ) : null}
      </DsToastRegion>
    </div>
  );
}

// ---------------------------------------------------------------------------
// View de membro
// ---------------------------------------------------------------------------
function MemberWelcome() {
  return (
    <div className="screen" key="dashboard-membro">
      <div className="card card-pad" style={{ maxWidth: 560 }}>
        <div className="member-head">
          <Icon name="user" />
          <span>Bem-vindo(a) à sua igreja</span>
        </div>
        <p className="member-lead">
          Você acompanha aqui sua trilha de crescimento e os próximos eventos. As
          ferramentas de liderança aparecem automaticamente quando você assume um
          papel ministerial.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal de ações (atribuir / mensagem / conectar à célula) — DsDialog da
// fundação, substituição mecânica: mesmas opções, callbacks e estados; Esc,
// trap de foco, backdrop e retorno de foco vêm do primitive.
// ---------------------------------------------------------------------------
function ActionModal({
  modal,
  members,
  cells,
  onClose,
  onAssign,
  onMessage,
  onLinkCell,
}: {
  modal: ModalState;
  members: TeamMember[];
  cells: Cell[];
  onClose: () => void;
  onAssign: (item: WorkItem, responsavelId: string) => void;
  onMessage: (item: WorkItem, mensagem: string) => void;
  onLinkCell: (item: WorkItem, celulaId: string) => void;
}) {
  const { kind, item } = modal;
  const [text, setText] = useState("");
  const activeCells = cells.filter((c) => c.ativo && c.liderId);

  const title =
    kind === "assign"
      ? "Atribuir responsável"
      : kind === "message"
        ? "Mensagem interna (WhatsApp)"
        : "Conectar à célula";

  return (
    <DsDialog open onClose={onClose} title={title} description={item.titulo}>
      {kind === "assign" ? (
        <div className="dh-picker">
          {members.length === 0 ? (
            <p className="dh-picker-empty">Nenhum membro disponível para atribuição.</p>
          ) : (
            members.map((m) => (
              <button
                type="button"
                key={m.usuarioId}
                className="dh-picker-row"
                onClick={() => onAssign(item, m.usuarioId)}
              >
                <span className="dh-picker-nm">{m.nome}</span>
                <span className="dh-picker-sub">{m.email}</span>
              </button>
            ))
          )}
        </div>
      ) : null}

      {kind === "linkCell" ? (
        <div className="dh-picker">
          {activeCells.length === 0 ? (
            <p className="dh-picker-empty">Nenhuma célula ativa com líder disponível.</p>
          ) : (
            activeCells.map((c) => (
              <button
                type="button"
                key={c.id}
                className="dh-picker-row"
                onClick={() => onLinkCell(item, c.id)}
              >
                <span className="dh-picker-nm">{c.nome}</span>
              </button>
            ))
          )}
        </div>
      ) : null}

      {kind === "message" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const value = text.trim();
            if (value) onMessage(item, value);
          }}
        >
          <DsField
            label="Mensagem"
            as="textarea"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Escreva a mensagem que será enviada pelo número oficial…"
            helper="Enviada pelo número oficial da igreja."
            // Gate 7.1: paridade com o autoFocus original — o DsDialog foca o
            // alvo marcado ao abrir (fluxo direto de escrita).
            data-autofocus=""
          />
          <div className="dh-modal-foot">
            <DsButton variant="tertiary" onClick={onClose}>
              Cancelar
            </DsButton>
            <DsButton type="submit" disabled={!text.trim()}>
              <Icon name="send" />
              <span>Enviar</span>
            </DsButton>
          </div>
        </form>
      ) : null}
    </DsDialog>
  );
}

// ---------------------------------------------------------------------------
// Linha do resumo da semana (mesmos dados dos antigos tiles/KPIs; clicável só
// quando a rota é permitida ao usuário — mesma regra canSee do tile antigo).
// ---------------------------------------------------------------------------
function SummaryLine({
  row,
  canNavigate,
  onNavigate,
}: {
  row: SummaryRow;
  canNavigate: boolean;
  onNavigate: (target: string) => void;
}) {
  const display = row.value == null ? "—" : row.value;
  const inner = (
    <>
      <span className="dh-summary-ic" aria-hidden="true">
        <Icon name={row.icon} />
      </span>
      <span className="dh-summary-label">{row.label}</span>
      <span className="dh-summary-val num">{display}</span>
      <span className="dh-summary-hint">{row.sub}</span>
    </>
  );
  if (!canNavigate || row.target == null) {
    return <div className="dh-summary-row">{inner}</div>;
  }
  return (
    <button
      type="button"
      className="dh-summary-row is-link"
      onClick={() => onNavigate(row.target!)}
    >
      {inner}
    </button>
  );
}

// ---------------------------------------------------------------------------
// "A jornada esta semana" — totais por etapa G12 (dado real de overview).
// Barra de lapidação (Direção D): proporção entre as contagens ABSOLUTAS já
// exibidas — nenhuma métrica nova, sem tendência.
// ---------------------------------------------------------------------------
const JOURNEY_STAGES: Array<{ key: string; label: string; route: string }> = [
  { key: "ganhar", label: "Ganhar", route: "ganhar" },
  { key: "consolidar", label: "Consolidar", route: "consolidar" },
  { key: "discipular", label: "Discipular", route: "g12" },
  { key: "enviar", label: "Enviar", route: "enviar" },
];

function JourneyCard({
  overview,
  canSeeAgente,
  canNavigate,
  onNavigate,
}: {
  overview: OverviewStats | null;
  canSeeAgente: boolean;
  canNavigate: (target: string) => boolean;
  onNavigate: (target: string) => void;
}) {
  const scopeLabel = overview
    ? overview.scope === "celula"
      ? "sua célula"
      : "sua igreja"
    : null;
  const maxStage = Math.max(
    1,
    ...JOURNEY_STAGES.map((s) => overview?.porEtapa?.[s.key] ?? 0),
  );

  return (
    <section className="dh-panel dh-journey" aria-label="A jornada esta semana">
      <h3 className="dh-panel-title">
        A jornada esta semana
        {scopeLabel ? <span className="dh-panel-count"> · {scopeLabel}</span> : null}
      </h3>
      <div>
        {JOURNEY_STAGES.map((stage) => {
          const value = overview?.porEtapa?.[stage.key];
          const display = value == null ? "—" : value;
          const can = canNavigate(stage.route);
          const content = (
            <>
              <span className="dh-journey-line">
                <span className={`dh-journey-dot ${stage.key}`} aria-hidden="true" />
                <span className="dh-journey-label">{stage.label}</span>
                <span className="dh-journey-val num">{display}</span>
              </span>
              {value != null ? (
                <span className="dh-journey-bar" aria-hidden="true">
                  <span
                    className={`dh-journey-fill ${stage.key}`}
                    style={{ width: `${Math.round((value / maxStage) * 100)}%` }}
                  />
                </span>
              ) : null}
            </>
          );
          return can ? (
            <button
              type="button"
              className="dh-journey-row"
              key={stage.key}
              onClick={() => onNavigate(stage.route)}
            >
              {content}
            </button>
          ) : (
            <div className="dh-journey-row" key={stage.key}>
              {content}
            </div>
          );
        })}
        {canSeeAgente ? (
          <div className="dh-journey-foot">
            A cada estágio, o agente cobra prazos e avisa quem precisa agir.{" "}
            <button type="button" className="dh-journey-cta" onClick={() => onNavigate("agente")}>
              Configurar agente →
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
