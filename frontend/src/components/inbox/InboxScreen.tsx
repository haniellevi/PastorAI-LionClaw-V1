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
  deleteConversation,
  fetchConversationPhoto,
  fetchConversations,
  fetchMessages,
  handoffConversation,
  markConversationRead,
  sendMedia,
  sendMessage,
  transferConversation,
  type ChatMessage,
  type Conversation,
} from "@/lib/conversations-api";
import { fetchTeamLookup, type TeamMember } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { isAdmin, type Role } from "@/lib/roles";
import {
  ApiError as WaApiError,
  canManageWhatsapp,
  fetchConnection,
  type ConnectionStatus,
} from "@/lib/whatsapp-api";

import { ContactPanel } from "./ContactPanel";
import { ConversationList, type ConvFilter } from "./ConversationList";
import { ConversationThread } from "./ConversationThread";
import { DeleteConversationDialog } from "./DeleteConversationDialog";
import { TransferConversationModal } from "./TransferConversationModal";
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
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);

  // Painel de dados do contato (Parte B) e exclusão de conversa.
  const [panelOpen, setPanelOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Foto de perfil da conversa selecionada (Etapa 4) e transferência (#2).
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [transferTarget, setTransferTarget] = useState<Conversation | null>(null);
  const [transferBusy, setTransferBusy] = useState(false);
  const [transferError, setTransferError] = useState<string | null>(null);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [teamLoading, setTeamLoading] = useState(false);

  // "unknown" quando o papel não pode ler a conexão (não-admin) — tratado como
  // operante, sem banner de degradação.
  const [connStatus, setConnStatus] = useState<ConnectionStatus | "unknown">("unknown");

  const allowed = user ? canAccessInbox(user.roles) : false;
  // Exclusão de conversa é admin-only (espelha require_role(["admin"]) no backend).
  const isAdminUser = user ? isAdmin(user.roles) : false;
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

  // ---- histórico de mensagens da conversa selecionada ---------------------
  const loadMessages = useCallback(
    async (convId: string, mode: "initial" | "poll" = "initial") => {
      if (!token) return;
      if (mode === "initial") setMessagesLoading(true);
      try {
        const items = await fetchMessages(token, convId);
        setMessages(items);
      } catch (err) {
        if (handleSessionError(err)) return;
        // No poll a falha é silenciosa; no initial a thread mostra vazio.
      } finally {
        if (mode === "initial") setMessagesLoading(false);
      }
    },
    [token, handleSessionError],
  );

  // Ao trocar de conversa, limpa e recarrega o histórico daquela conversa.
  useEffect(() => {
    if (!selectedId) {
      setMessages([]);
      return;
    }
    setMessages([]);
    void loadMessages(selectedId, "initial");
  }, [selectedId, loadMessages]);

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
      if (selectedId) void loadMessages(selectedId, "poll");
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [allowed, load, loadConnection, selectedId, loadMessages]);

  // Painel de dados: aberto por padrão no desktop, fechado (drawer) no mobile.
  useEffect(() => {
    if (typeof window === "undefined") return;
    setPanelOpen(window.matchMedia("(min-width: 1101px)").matches);
  }, []);

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
    const q = search.trim().toLowerCase();
    return conversations.filter((c) => {
      const estado = effectiveEstado(c);
      if (filter === "aguardando" && estado !== "aguardando") return false;
      if (filter === "ia" && estado !== "ia") return false;
      if (!q) return true;
      const hay = `${c.nome ?? ""} ${c.telefone} ${c.ultimaMensagem ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [conversations, filter, search]);

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
        // Bump da última mensagem na lista + recarrega o histórico (a mensagem
        // enviada é persistida no backend e aparece na thread).
        patch(c.id, { ultimaMensagem: text });
        void loadMessages(c.id, "poll");
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
    [token, patch, flashToast, handleSessionError, loadMessages],
  );

  const handleSendMedia = useCallback(
    async (c: Conversation, file: File, caption?: string): Promise<boolean> => {
      if (!token) return false;
      try {
        await sendMedia(token, c.id, file, caption);
        // Bump da lista + recarrega o histórico (a mídia enviada é persistida).
        const label = caption?.trim()
          ? caption.trim()
          : file.type.startsWith("image/")
            ? "📷 Imagem"
            : file.type.startsWith("audio/")
              ? "🎤 Áudio"
              : "📎 Arquivo";
        patch(c.id, { ultimaMensagem: label });
        void loadMessages(c.id, "poll");
        flashToast({ kind: "ok", text: "Mídia enviada pelo número oficial." });
        return true;
      } catch (err) {
        if (handleSessionError(err)) return false;
        flashToast({
          kind: "err",
          text:
            err instanceof ApiError
              ? err.message
              : "Não foi possível enviar a mídia. Tente novamente.",
        });
        return false;
      }
    },
    [token, patch, flashToast, handleSessionError, loadMessages],
  );

  // ---- exclusão de conversa (hard delete, admin) --------------------------
  const confirmDelete = useCallback(async () => {
    if (!token || !deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteConversation(token, deleteTarget.id);
      const deletedId = deleteTarget.id;
      setConversations((prev) => prev.filter((c) => c.id !== deletedId));
      if (selectedId === deletedId) setSelectedId(null);
      setDeleteTarget(null);
      flashToast({ kind: "ok", text: "Conversa excluída." });
    } catch (err) {
      if (handleSessionError(err)) return;
      setDeleteError(
        err instanceof ApiError ? err.message : "Não foi possível excluir a conversa.",
      );
    } finally {
      setDeleting(false);
    }
  }, [token, deleteTarget, selectedId, flashToast, handleSessionError]);

  // ---- marcar como lida ao abrir + foto de perfil -------------------------
  useEffect(() => {
    if (!selectedId || !token) return;
    const conv = conversations.find((c) => c.id === selectedId);
    if (conv && conv.naoLidas > 0) {
      patch(selectedId, { naoLidas: 0 });
      void markConversationRead(token, selectedId).catch(() => {});
    }
  }, [selectedId, conversations, token, patch]);

  useEffect(() => {
    setPhotoUrl(null);
    if (!selectedId || !token) return;
    let cancelled = false;
    void fetchConversationPhoto(token, selectedId)
      .then((url) => {
        if (!cancelled) setPhotoUrl(url);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedId, token]);

  // ---- transferir conversa (#2) -------------------------------------------
  const openTransfer = useCallback(
    (c: Conversation) => {
      setTransferError(null);
      setTransferTarget(c);
      if (team.length === 0 && token) {
        setTeamLoading(true);
        fetchTeamLookup(token)
          .then((page) => setTeam(page.items))
          .catch(() => {})
          .finally(() => setTeamLoading(false));
      }
    },
    [team.length, token],
  );

  const confirmTransfer = useCallback(
    async (userId: string) => {
      if (!token || !transferTarget) return;
      setTransferBusy(true);
      setTransferError(null);
      try {
        const res = await transferConversation(token, transferTarget.id, userId);
        patch(transferTarget.id, {
          estado: (res.estado as Conversation["estado"]) ?? "humano",
          assumidoPor: res.assumidoPor,
          assumidoPorNome: res.assumidoPorNome,
          esperaDesde: null,
        });
        flashToast({
          kind: "ok",
          text: `Conversa transferida para ${res.assumidoPorNome ?? "outro líder"}.`,
        });
        setTransferTarget(null);
      } catch (err) {
        if (handleSessionError(err)) return;
        setTransferError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível transferir a conversa.",
        );
      } finally {
        setTransferBusy(false);
      }
    },
    [token, transferTarget, patch, flashToast, handleSessionError],
  );

  const transferMembers = useMemo(() => {
    const selfId = user?.appUserId;
    const holderId = transferTarget?.assumidoPor;
    return team
      .filter((m) => canAccessInbox(m.papeis as Role[]))
      .filter((m) => m.usuarioId !== selfId && m.usuarioId !== holderId)
      .sort((a, b) => a.nome.localeCompare(b.nome));
  }, [team, user, transferTarget]);

  // ---- bloqueio de acesso (US-11) -----------------------------------------
  if (!allowed) {
    return (
      <div className="screen" key="inbox-denied">
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

  return (
    <div className="screen screen-chat" key="inbox">
      <div className="screen-head">
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

      <div className={`inbox${selected && panelOpen ? " with-panel" : ""}`}>
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
            search={search}
            onSelect={setSelectedId}
            onFilter={setFilter}
            onSearch={setSearch}
          />
        )}

        {selected ? (
          <ConversationThread
            conversation={selected}
            selfId={user?.appUserId ?? ""}
            holderName={selected.assumidoPorNome}
            degraded={degraded}
            busy={busyId === selected.id}
            conflict={conflicts[selected.id] ?? null}
            messages={messages}
            messagesLoading={messagesLoading}
            panelOpen={panelOpen}
            isAdmin={isAdminUser}
            avatarUrl={photoUrl}
            onAssume={handleAssume}
            onReturn={handleReturn}
            onSend={handleSend}
            onSendMedia={handleSendMedia}
            onTogglePanel={() => setPanelOpen((v) => !v)}
            onDelete={(c) => {
              setDeleteError(null);
              setDeleteTarget(c);
            }}
            onTransfer={openTransfer}
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

        {selected && panelOpen ? (
          <>
            <div
              className="panel-backdrop"
              onClick={() => setPanelOpen(false)}
              role="presentation"
            />
            <ContactPanel
              pessoaId={selected.pessoaId}
              telefone={selected.telefone}
              avatarUrl={photoUrl}
              onClose={() => setPanelOpen(false)}
            />
          </>
        ) : null}
      </div>

      {deleteTarget ? (
        <DeleteConversationDialog
          conversation={deleteTarget}
          busy={deleting}
          error={deleteError}
          onCancel={() => {
            if (deleting) return;
            setDeleteTarget(null);
            setDeleteError(null);
          }}
          onConfirm={() => void confirmDelete()}
        />
      ) : null}

      {transferTarget ? (
        <TransferConversationModal
          conversation={transferTarget}
          members={transferMembers}
          loading={teamLoading}
          busy={transferBusy}
          error={transferError}
          onCancel={() => {
            if (transferBusy) return;
            setTransferTarget(null);
            setTransferError(null);
          }}
          onConfirm={(userId) => void confirmTransfer(userId)}
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
