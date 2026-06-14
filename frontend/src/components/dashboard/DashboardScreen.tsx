"use client";

/**
 * Tela #dashboard — fila de trabalho pastoral (SPEC screen `dashboard`).
 *
 * Reúne os componentes desta sprint:
 *  - stat-cards de visão geral (normal/alert) derivados da fila;
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

import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  StaleItemError,
  fetchCells,
  fetchTeam,
  fetchWorkQueue,
  linkCell,
  queueAction,
  queueFonovisita,
  sendInternalMessage,
  type Cell,
  type TeamMember,
  type WorkItem,
} from "@/lib/dashboard-api";
import { compareUrgency, computeDeadline } from "@/lib/deadline";
import { Icon } from "@/lib/icons";
import { isLeader } from "@/lib/roles";

import { NextActions } from "./NextActions";
import { StatCard, type StatCardData } from "./StatCard";
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

export function DashboardScreen() {
  const { user, token, expireSession } = useAuth();

  const [items, setItems] = useState<WorkItem[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [cells, setCells] = useState<Cell[]>([]);
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
        const [queue, team, cellPage] = await Promise.all([
          fetchWorkQueue(token),
          fetchTeam(token),
          fetchCells(token),
        ]);
        setItems(queue.items);
        setMembers(team.items);
        setCells(cellPage.items);
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

  // ---- stat-cards derivados ----------------------------------------------
  const stats: StatCardData[] = useMemo(() => {
    const countByTipo = (tipos: string[]) =>
      openItems.filter((i) => tipos.includes(i.tipo)).length;
    const overdue = openItems.filter(
      (i) => computeDeadline(i.prazo, now).tone === "late",
    ).length;
    const visitantes = countByTipo(["visitante", "conectar_celula"]);
    const atendimentos = countByTipo(["atendimento"]);
    const relatorios = countByTipo(["relatorio"]);
    return [
      {
        icon: "user",
        label: "Visitantes sem acompanhamento",
        value: visitantes,
        delta: "aguardando conexão à célula",
        alert: visitantes > 0,
      },
      {
        icon: "chat",
        label: "Atendimentos aguardando",
        value: atendimentos,
        delta: "pedidos de atendimento humano",
        alert: atendimentos > 0,
      },
      {
        icon: "document",
        label: "Relatórios pendentes",
        value: relatorios,
        delta: "células nesta semana",
      },
      {
        icon: "clock",
        label: "Prazos atrasados",
        value: overdue,
        delta: "itens fora do prazo",
        alert: overdue > 0,
      },
    ];
  }, [openItems, now]);

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
    <div className="screen dashboard" key="dashboard">
      <div className="screen-head">
        <div className="titles">
          <h2>Dashboard</h2>
          <p>Fila de trabalho pastoral — o que exige ação hoje.</p>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            <Icon name="refresh" />
            <span>Atualizar</span>
          </button>
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            Tentar novamente
          </button>
        </div>
      ) : null}

      <div className="stat-grid">
        {showSkeleton
          ? Array.from({ length: 4 }).map((_, i) => (
              <div className="stat skeleton" key={i}>
                <div className="sk-line sk-sm" />
                <div className="sk-line sk-lg" />
              </div>
            ))
          : stats.map((s) => <StatCard key={s.label} {...s} />)}
      </div>

      <div className="dash-grid">
        <div className="card">
          <div className="panel-title">
            Fila de trabalho pastoral
            <span className="count">· o que exige ação hoje</span>
            <div className="right">
              <div className="tabs">
                <button
                  type="button"
                  className={`tab${tab === "todos" ? " active" : ""}`}
                  onClick={() => setTab("todos")}
                >
                  Todos
                </button>
                <button
                  type="button"
                  className={`tab${tab === "meus" ? " active" : ""}`}
                  onClick={() => setTab("meus")}
                >
                  Meus
                </button>
              </div>
            </div>
          </div>

          {showSkeleton ? (
            <div className="queue">
              {Array.from({ length: 4 }).map((_, i) => (
                <div className="qitem skeleton" key={i}>
                  <span className="qicon sk-icon" />
                  <div className="qbody">
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : isEmpty ? (
            <div className="empty-state">
              <Icon name="check" />
              <p>
                <strong>Fila zerada.</strong> Nenhuma pendência pastoral aberta agora.
              </p>
            </div>
          ) : (
            <div className="queue">
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
        </div>

        <div className="dash-side">
          {showSkeleton ? (
            <div className="card card-pad">
              <div className="sk-line sk-md" />
              <div className="sk-line sk-sm" />
            </div>
          ) : (
            <NextActions items={openItems} members={members} />
          )}
        </div>
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

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// View de membro
// ---------------------------------------------------------------------------
function MemberWelcome() {
  return (
    <div className="screen" key="dashboard-membro">
      <div className="screen-head">
        <div className="titles">
          <h2>Dashboard</h2>
          <p>Sua trilha de crescimento e próximos eventos.</p>
        </div>
      </div>
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
// Modal de ações (atribuir / mensagem / conectar à célula)
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
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>{title}</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="modal-sub">{item.titulo}</div>

        {kind === "assign" ? (
          <div className="picker">
            {members.length === 0 ? (
              <p className="sub">Nenhum membro disponível para atribuição.</p>
            ) : (
              members.map((m) => (
                <button
                  type="button"
                  key={m.usuarioId}
                  className="picker-row"
                  onClick={() => onAssign(item, m.usuarioId)}
                >
                  <span className="nm">{m.nome}</span>
                  <span className="sub">{m.email}</span>
                </button>
              ))
            )}
          </div>
        ) : null}

        {kind === "linkCell" ? (
          <div className="picker">
            {activeCells.length === 0 ? (
              <p className="sub">Nenhuma célula ativa com líder disponível.</p>
            ) : (
              activeCells.map((c) => (
                <button
                  type="button"
                  key={c.id}
                  className="picker-row"
                  onClick={() => onLinkCell(item, c.id)}
                >
                  <span className="nm">{c.nome}</span>
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
            <textarea
              className="msg-input"
              rows={4}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Escreva a mensagem que será enviada pelo número oficial…"
              autoFocus
            />
            <div className="modal-foot">
              <button type="button" className="btn btn-sm" onClick={onClose}>
                Cancelar
              </button>
              <button
                type="submit"
                className="btn btn-sm btn-primary"
                disabled={!text.trim()}
              >
                <Icon name="send" />
                <span>Enviar</span>
              </button>
            </div>
          </form>
        ) : null}
      </div>
    </div>
  );
}
