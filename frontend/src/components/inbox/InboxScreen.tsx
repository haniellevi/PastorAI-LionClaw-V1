"use client";

/**
 * Tela #inbox — Inbox do WhatsApp oficial (US-08/US-11..US-14).
 *
 * Área RESTRITA a papéis privilegiados (admin · pastor · lider_g12). Líder de
 * célula que chegar por deep-link recebe o bloqueio de acesso (US-11) — sem
 * qualquer chamada operacional à API.
 *
 * Reúne conversation-list (Todas/Aguardando/IA) e conversation-thread nos
 * estados ia-active/human/waiting, com handoff Assumir/Devolver (US-12/US-13)
 * consumindo api-conversation-handoff. Conflito de concorrência reflete o
 * `assumidoPor` real. A lista atualiza por polling (sem reload). Com o WhatsApp
 * offline/reconectando, exibe banner de degradação e desabilita o envio.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  ConversationConflictError,
  SessionExpiredError,
  canAccessInbox,
  fetchConversations,
  handoffConversation,
  sendMessage,
  type Conversation,
} from "@/lib/conversations-api";
import { Icon } from "@/lib/icons";
import {
  ApiError as WaApiError,
  canManageWhatsapp,
  fetchConnection,
  type ConnectionStatus,
} from "@/lib/whatsapp-api";

import { ConversationList, type ConvFilter } from "./ConversationList";
import { ConversationThread } from "./ConversationThread";
import { effectiveEstado } from "./conversation-format";

const POLL_MS = 15_000;

interface Toast {
  kind: "ok" | "err";
  text: string;
}

export function InboxScreen() {
  const { user, token, expireSession } = useAuth();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const [filter, setFilter] = useState<ConvFilter>("todas");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<Record<string, string>>({});
  const [localReplies, setLocalReplies] = useState<Record<string, string[]>>({});
  const [toast, setToast] = useState<Toast | null>(null);

  // "unknown" quando o papel não pode ler a conexão (não-admin) — tratado como
  // operante, sem banner de degradação.
  const [connStatus, setConnStatus] = useState<ConnectionStatus | "unknown">("unknown");

  const allowed = user ? canAccessInbox(user.roles) : false;
  // Só admin pode ler a conexão (/whatsapp/connection é admin-only). Para os
  // demais papéis privilegiados, o status fica "unknown" (sem banner).
  const canReadConnection = user ? canManageWhatsapp(user.roles) : false;

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

  // ---- carga + polling ----------------------------------------------------
  const load = useCallback(
    async (mode: "initial" | "poll" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      if (mode !== "poll") setError(null);
      try {
        const page = await fetchConversations(token);
        setConversations(page.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        if (mode !== "poll") {
          setError(
            err instanceof ApiError
              ? err.message
              : "Não foi possível carregar as conversas.",
          );
        }
      } finally {
        if (mode === "initial") setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  const loadConnection = useCallback(async () => {
    if (!token || !canReadConnection) return;
    try {
      const info = await fetchConnection(token);
      setConnStatus(info.status);
    } catch (err) {
      if (handleSessionError(err)) return;
      // 403 (papel sem acesso à conexão) ou falha: mantém "unknown" (sem banner).
      if (err instanceof WaApiError && err.status === 403) {
        setConnStatus("unknown");
      }
    }
  }, [token, canReadConnection, handleSessionError]);

  useEffect(() => {
    if (!allowed) {
      setLoading(false);
      return;
    }
    void load("initial");
    void loadConnection();
  }, [allowed, load, loadConnection]);

  useEffect(() => {
    if (!allowed) return;
    const id = window.setInterval(() => {
      setNow(Date.now());
      void load("poll");
      void loadConnection();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [allowed, load, loadConnection]);

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

  // ---- derivações ---------------------------------------------------------
  const waitingCount = useMemo(
    () => conversations.filter((c) => effectiveEstado(c) === "aguardando").length,
    [conversations],
  );

  const visible = useMemo(() => {
    if (filter === "todas") return conversations;
    return conversations.filter((c) => {
      const estado = effectiveEstado(c);
      if (filter === "aguardando") return estado === "aguardando";
      return estado === "ia";
    });
  }, [conversations, filter]);

  // Seleção padrão: primeira conversa visível quando nenhuma escolhida.
  useEffect(() => {
    if (selectedId && conversations.some((c) => c.id === selectedId)) return;
    setSelectedId(visible[0]?.id ?? null);
  }, [visible, conversations, selectedId]);

  const selected = useMemo(
    () => conversations.find((c) => c.id === selectedId) ?? null,
    [conversations, selectedId],
  );

  const degraded = connStatus === "offline" || connStatus === "reconectando";

  // ---- helpers de mutação -------------------------------------------------
  const patch = useCallback((id: string, p: Partial<Conversation>) => {
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, ...p } : c)));
  }, []);

  const clearConflict = useCallback((id: string) => {
    setConflicts((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  // ---- handoff ------------------------------------------------------------
  const doHandoff = useCallback(
    async (c: Conversation, to: "human" | "ia") => {
      if (!token || !user) return;
      setBusyId(c.id);
      clearConflict(c.id);
      try {
        const res = await handoffConversation(token, c.id, to);
        patch(c.id, {
          estado: (res.estado as Conversation["estado"]) ?? (to === "human" ? "humano" : "ia"),
          assumidoPor: to === "human" ? res.assumidoPor ?? user.appUserId : null,
          assumidoEm: to === "human" ? new Date().toISOString() : null,
          esperaDesde: to === "human" ? null : c.esperaDesde,
        });
        flashToast({
          kind: "ok",
          text: to === "human" ? "Atendimento assumido. IA pausada." : "Devolvido para a IA.",
        });
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof ConversationConflictError) {
          // Reflete o estado/holder real retornado pelo backend (US-12).
          patch(c.id, {
            estado: (err.estado as Conversation["estado"]) ?? "humano",
            assumidoPor: err.assumidoPor ?? c.assumidoPor,
          });
          setConflicts((prev) => ({ ...prev, [c.id]: err.message }));
          flashToast({ kind: "err", text: err.message });
          return;
        }
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível alternar o atendimento.",
        });
      } finally {
        setBusyId(null);
      }
    },
    [token, user, clearConflict, patch, flashToast, handleSessionError],
  );

  const handleAssume = useCallback((c: Conversation) => void doHandoff(c, "human"), [doHandoff]);
  const handleReturn = useCallback((c: Conversation) => void doHandoff(c, "ia"), [doHandoff]);

  const handleSend = useCallback(
    async (c: Conversation, text: string) => {
      if (!token) return;
      try {
        await sendMessage(token, c.id, text);
        // Eco otimista na thread + bump da última mensagem na lista.
        setLocalReplies((prev) => ({ ...prev, [c.id]: [...(prev[c.id] ?? []), text] }));
        patch(c.id, { ultimaMensagem: text });
        flashToast({ kind: "ok", text: "Resposta enviada pelo número oficial." });
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text:
            err instanceof ApiError
              ? err.message
              : "Não foi possível enviar a resposta. Tente novamente.",
        });
      }
    },
    [token, patch, flashToast, handleSessionError],
  );

  // ---- bloqueio de acesso (US-11) -----------------------------------------
  if (!allowed) {
    return (
      <div className="screen" key="inbox-denied">
        <div className="screen-head">
          <div className="titles">
            <h2>Inbox do WhatsApp</h2>
            <p>Área restrita ao atendimento pastoral.</p>
          </div>
        </div>
        <div className="card">
          <div className="access-denied">
            <Icon name="lock" className="access-ic" />
            <h3>Acesso restrito</h3>
            <p>
              O inbox do WhatsApp é exclusivo da liderança de atendimento
              (Administrador, Pastor ou Líder G12). Líderes de célula não têm acesso
              às conversas. Fale com a liderança da sua igreja se precisar de acesso.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const showSkeleton = loading && !loaded;
  const holderName = null; // nomes de usuários não são expostos nesta listagem

  return (
    <div className="screen screen-chat" key="inbox">
      <div className="screen-head">
        <div className="titles">
          <h2>Inbox do WhatsApp</h2>
          <p>
            Conversas pelo número oficial. Apenas o número da igreja é registrado —
            conversas pessoais do pastor não entram aqui.
          </p>
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

      {degraded ? (
        <div className="degraded-banner" role="status" style={{ borderRadius: "var(--r-md)", marginBottom: "var(--s3)" }}>
          <Icon name="alert" />
          <span>
            Conexão do WhatsApp {connStatus === "reconectando" ? "reconectando" : "offline"}.
            O atendimento está degradado e o envio de respostas está desabilitado.
          </span>
        </div>
      ) : null}

      <div className="inbox">
        {showSkeleton ? (
          <div className="conv-list">
            {Array.from({ length: 5 }).map((_, i) => (
              <div className="conv skeleton" key={i} style={{ cursor: "default" }}>
                <span className="av sk-icon" />
                <div className="conv-main">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <ConversationList
            conversations={visible}
            selectedId={selectedId}
            filter={filter}
            waitingCount={waitingCount}
            now={now}
            onSelect={setSelectedId}
            onFilter={setFilter}
          />
        )}

        {selected ? (
          <ConversationThread
            conversation={selected}
            selfId={user?.appUserId ?? ""}
            holderName={holderName}
            degraded={degraded}
            busy={busyId === selected.id}
            conflict={conflicts[selected.id] ?? null}
            localReplies={localReplies[selected.id] ?? []}
            onAssume={handleAssume}
            onReturn={handleReturn}
            onSend={handleSend}
          />
        ) : (
          <div className="empty-pane">
            <Icon name="chat" />
            <p>
              <strong>Nenhuma conversa por aqui ainda.</strong>
            </p>
            <p className="sub">
              Assim que alguém falar com o número oficial da igreja, a conversa
              aparece nesta lista.
            </p>
          </div>
        )}
      </div>

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
