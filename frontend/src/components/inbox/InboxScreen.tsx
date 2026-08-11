"use client";

/**
 * Tela #inbox — Inbox do WhatsApp oficial (US-08/US-11..US-14).
 *
 * Área RESTRITA à liderança de atendimento (US-11/#5). admin/pastor têm visão
 * completa; líder G12/consolidação/célula e operador são "responsáveis" e veem
 * só as conversas transferidas a eles (o backend filtra por assumido_por).
 * Papéis sem acesso (ex.: membro) recebem o bloqueio — sem chamar a API.
 *
 * Reúne conversation-list (Todas/Aguardando/IA) e conversation-thread nos
 * estados ia-active/human/waiting, com handoff Assumir/Devolver (US-12/US-13)
 * consumindo api-conversation-handoff. Conflito de concorrência reflete o
 * `assumidoPor` real. A lista atualiza por polling (sem reload). Com o WhatsApp
 * offline/reconectando, exibe banner de degradação e desabilita o envio.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsToastRegion } from "@/components/ds/Toast";
import { useAuth } from "@/lib/auth-context";
import {
  ApiError,
  ConversationConflictError,
  SessionExpiredError,
  canAccessInbox,
  deleteConversation,
  fetchConversationPhoto,
  fetchConversations,
  fetchInboxTransferTargets,
  fetchMessages,
  handoffConversation,
  markConversationRead,
  sendMedia,
  sendMessage,
  transferConversation,
  type ChatMessage,
  type Conversation,
  type InboxTransferTarget,
} from "@/lib/conversations-api";
import { clearAuthedResponseCache } from "@/lib/dashboard-api";
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
// O GET normal deve concluir bem antes disso. Encerrar em 12 s libera o
// single-flight antes do próximo tick de 15 s, sem transformar oscilações
// breves de rede em várias requisições concorrentes.
const REQUEST_TIMEOUT_MS = 12_000;

class RequestTimeoutError extends Error {
  constructor() {
    super("A requisição excedeu o tempo limite.");
    this.name = "RequestTimeoutError";
  }
}

/**
 * O `fetch` respeita AbortSignal, mas esta corrida também encerra o await caso
 * um mock/adaptador intermediário ignore o cancelamento. Assim o single-flight
 * sempre é liberado no prazo e a promessa tardia fica observada, sem rejection
 * não tratada.
 */
function runTimedRequest<T>(
  controller: AbortController,
  request: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const { signal } = controller;
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    let timedOut = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      signal.removeEventListener("abort", onAbort);
      callback();
    };
    const onAbort = () =>
      finish(() =>
        reject(
          timedOut
            ? new RequestTimeoutError()
            : new DOMException("Requisição cancelada.", "AbortError"),
        ),
      );
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);

    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) {
      onAbort();
      return;
    }

    try {
      request(signal).then(
        (value) => finish(() => resolve(value)),
        (error: unknown) => finish(() => reject(error)),
      );
    } catch (error) {
      finish(() => reject(error));
    }
  });
}

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
  const [team, setTeam] = useState<InboxTransferTarget[]>([]);
  const [teamLoading, setTeamLoading] = useState(false);

  // "unknown" quando o papel não pode ler a conexão (não-admin) — tratado como
  // operante, sem banner de degradação.
  const [connStatus, setConnStatus] = useState<ConnectionStatus | "unknown">("unknown");

  // Polling is best-effort. A slow network must not stack another identical
  // request every 15 seconds; besides wasting work, overlapping responses
  // allocate duplicate arrays and can keep the browser busy indefinitely.
  const conversationsRequestRef = useRef<AbortController | null>(null);
  const connectionRequestRef = useRef<AbortController | null>(null);

  // Master-detail mobile (PR2): em ≤860px o inbox é tela única (lista OU thread).
  // selectedId null = lista; tocar uma conversa abre a thread; "voltar" volta à
  // lista. No desktop a lista e a thread seguem lado a lado (seleção automática).
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(max-width: 860px)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 860px)");
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

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
      if (conversationsRequestRef.current) return;
      const controller = new AbortController();
      conversationsRequestRef.current = controller;
      if (mode !== "poll") setLoading(true);
      if (mode !== "initial") {
        clearAuthedResponseCache(token, ["/conversations?page="]);
      }
      if (mode !== "poll") setError(null);
      try {
        const page = await runTimedRequest(controller, (signal) =>
          fetchConversations(token, 100, signal),
        );
        setConversations(page.items);
        setLoaded(true);
      } catch (err) {
        if (err instanceof RequestTimeoutError) {
          if (mode !== "poll") {
            setError("A carga das conversas demorou mais que o esperado. Tente novamente.");
          }
          return;
        }
        if (controller.signal.aborted) return;
        if (handleSessionError(err)) return;
        if (mode !== "poll") {
          setError(
            err instanceof ApiError
              ? err.message
              : "Não foi possível carregar as conversas.",
          );
        }
      } finally {
        if (conversationsRequestRef.current === controller) {
          conversationsRequestRef.current = null;
          if (mode !== "poll") setLoading(false);
        }
      }
    },
    [token, handleSessionError],
  );

  const loadConnection = useCallback(async () => {
    if (!token || !canReadConnection) return;
    if (connectionRequestRef.current) return;
    const controller = new AbortController();
    connectionRequestRef.current = controller;
    try {
      const info = await runTimedRequest(controller, (signal) => fetchConnection(token, signal));
      setConnStatus(info.status);
    } catch (err) {
      if (controller.signal.aborted) return;
      if (handleSessionError(err)) return;
      // 403 (papel sem acesso à conexão) ou falha: mantém "unknown" (sem banner).
      if (err instanceof WaApiError && err.status === 403) {
        setConnStatus("unknown");
      }
    } finally {
      if (connectionRequestRef.current === controller) {
        connectionRequestRef.current = null;
      }
    }
  }, [token, canReadConnection, handleSessionError]);

  // ---- histórico de mensagens da conversa selecionada ---------------------
  // INBOX-RACE-1: qual conversa está aberta AGORA. Requisições de /messages são
  // concorrentes (troca de conversa, polling, envio), e a resposta de uma
  // conversa antiga pode chegar depois da atual — sem esta guarda ela
  // sobrescreveria a thread sob o cabeçalho de outro contato.
  const selectedIdRef = useRef<string | null>(null);
  // INBOX-RACE-1A: o id sozinho não separa DUAS VISITAS à mesma conversa
  // (A → B → A): na volta o id bate de novo e a resposta da 1ª visita seria
  // aceita. Esta geração muda a cada troca de seleção — nunca por requisição —,
  // então o polling e o envio da conversa atual seguem na mesma geração da carga
  // inicial e não deixam o `messagesLoading` preso.
  const selectionGenRef = useRef(0);
  // INBOX-RACE-1B: dentro da MESMA visita ainda há concorrência — a carga
  // inicial e o polling (ou o recarregamento pós-envio) correm juntos. Se a mais
  // nova responder primeiro, a mais antiga chegando depois voltaria o histórico
  // para um snapshot vencido. `reqSeq` numera cada requisição e `appliedSeq`
  // guarda a última que escreveu; uma iniciada antes dessa não escreve mais.
  // Ordena só a ESCRITA: o fim do `messagesLoading` continua preso à visita,
  // senão uma carga inicial ultrapassada por um poll deixaria o skeleton na tela.
  const reqSeqRef = useRef(0);
  const appliedSeqRef = useRef(0);
  // One request per selection visit. A → B → A remains valid because each
  // visit gets a new generation; only duplicate initial/poll/send refreshes
  // from the same visit are coalesced.
  const messageRequestsInFlightRef = useRef(new Set<string>());
  const messageRequestControllersRef = useRef(new Map<string, AbortController>());
  // A refresh requested after a successful send must not be lost behind a
  // slower poll that was already in flight. Keep a single trailing refresh
  // for that visit and run it immediately after the current request settles.
  const messageRefreshPendingRef = useRef(new Set<string>());

  const loadMessages = useCallback(
    async (convId: string, mode: "initial" | "poll" | "refresh" = "initial") => {
      if (!token) return;
      const gen = selectionGenRef.current;
      if (selectedIdRef.current !== convId) return;
      const requestKey = `${gen}:${convId}`;
      if (messageRequestsInFlightRef.current.has(requestKey)) {
        if (mode === "refresh") messageRefreshPendingRef.current.add(requestKey);
        return;
      }
      messageRequestsInFlightRef.current.add(requestKey);
      const controller = new AbortController();
      messageRequestControllersRef.current.set(requestKey, controller);
      // A requisição só continua valendo se, na volta, a conversa aberta for a
      // mesma E ainda for a mesma visita a ela.
      const atual = () => selectedIdRef.current === convId && selectionGenRef.current === gen;
      if (mode === "initial") setMessagesLoading(true);
      try {
        while (true) {
          const seq = (reqSeqRef.current += 1);
          try {
            const items = await runTimedRequest(controller, (signal) =>
              fetchMessages(token, convId, 200, signal),
            );
            // Resposta obsoleta (trocou de conversa, ou é de uma visita anterior a
            // esta mesma conversa): descarta sem tocar na UI.
            if (!atual()) return;
            // Fora de ordem: outra requisição desta mesma visita, iniciada depois,
            // já escreveu um histórico mais recente.
            if (seq >= appliedSeqRef.current) {
              appliedSeqRef.current = seq;
              setMessages(items);
            }
          } catch (err) {
            if (controller.signal.aborted) break;
            if (handleSessionError(err)) return;
            // No poll/refresh a falha é silenciosa; no initial a thread mostra vazio.
          }

          // Coalesce any number of sends completed during this request into one
          // fresh snapshot. Ordinary polling never queues another request.
          if (!messageRefreshPendingRef.current.delete(requestKey) || !atual()) break;
        }
      } finally {
        if (messageRequestControllersRef.current.get(requestKey) === controller) {
          messageRequestControllersRef.current.delete(requestKey);
        }
        messageRequestsInFlightRef.current.delete(requestKey);
        messageRefreshPendingRef.current.delete(requestKey);
        // Idem para o "carregando": só a requisição da visita atual pode
        // encerrá-lo — senão a resposta antiga apagaria o skeleton da nova.
        if (mode === "initial" && atual()) setMessagesLoading(false);
      }
    },
    [token, handleSessionError],
  );

  // Ao trocar de conversa, limpa e recarrega o histórico daquela conversa.
  useEffect(() => {
    const requestControllers = messageRequestControllersRef.current;
    const requestsInFlight = messageRequestsInFlightRef.current;
    const refreshesPending = messageRefreshPendingRef.current;
    selectedIdRef.current = selectedId;
    selectionGenRef.current += 1;
    const requestKey = `${selectionGenRef.current}:${selectedId ?? ""}`;
    setMessages([]);
    if (!selectedId) {
      // Sem conversa aberta não há requisição para encerrar o carregamento: a
      // que estava em voo já não conta como atual e seu `finally` é descartado.
      setMessagesLoading(false);
      return;
    }
    void loadMessages(selectedId, "initial");
    return () => {
      const controller = requestControllers.get(requestKey);
      requestControllers.delete(requestKey);
      requestsInFlight.delete(requestKey);
      refreshesPending.delete(requestKey);
      controller?.abort();
    };
  }, [selectedId, loadMessages]);

  // Rede pendente não deve sobreviver ao Inbox. A limpeza por visita acima
  // cobre a seleção atual; esta guarda também encerra qualquer pedido residual.
  useEffect(() => {
    const requestControllers = messageRequestControllersRef.current;
    const requestsInFlight = messageRequestsInFlightRef.current;
    const refreshesPending = messageRefreshPendingRef.current;
    return () => {
      for (const controller of requestControllers.values()) {
        controller.abort();
      }
      requestControllers.clear();
      requestsInFlight.clear();
      refreshesPending.clear();
    };
  }, []);

  useEffect(() => {
    if (!allowed) {
      setLoading(false);
      return;
    }
    void load("initial");
    void loadConnection();
    return () => {
      const conversationsController = conversationsRequestRef.current;
      const connectionController = connectionRequestRef.current;
      conversationsRequestRef.current = null;
      connectionRequestRef.current = null;
      conversationsController?.abort();
      connectionController?.abort();
    };
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

  // Gate 8: o painel de dados é um DRAWER sob demanda em TODAS as larguras —
  // sem três colunas permanentes competindo por atenção. Abre só pelo botão
  // "Dados do contato" (mesmo gatilho de antes).

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

  // Seleção padrão: no desktop abre a 1ª conversa visível; no mobile o inbox é
  // master-detail (começa na lista), então só limpamos uma seleção que ficou
  // inválida (conversa saiu da lista) — voltando para a lista.
  useEffect(() => {
    if (selectedId && conversations.some((c) => c.id === selectedId)) return;
    if (isMobile) {
      if (selectedId) setSelectedId(null);
      return;
    }
    setSelectedId(visible[0]?.id ?? null);
  }, [visible, conversations, selectedId, isMobile]);

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
          text:
            to === "human"
              ? "Atendimento assumido. IA pausada."
              : c.semInteresse
                ? "Atendimento encerrado. A IA segue pausada."
                : "Devolvido para a IA.",
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
        void loadMessages(c.id, "refresh");
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
        void loadMessages(c.id, "refresh");
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
        fetchInboxTransferTargets(token)
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
              O inbox do WhatsApp é restrito à liderança de atendimento. Conforme o
              seu papel, você veria todas as conversas (admin/pastor) ou apenas as
              transferidas a você (responsável). Fale com a liderança da sua igreja
              se precisar de acesso.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const showSkeleton = loading && !loaded;
  const showInitialFailure = Boolean(error) && !loaded;

  return (
    <div className={`screen screen-chat ib${selected ? " thread-open" : ""}`} key="inbox">
      <div className="screen-head ib-head">
        <div className="actions">
          <DsButton
            variant="secondary"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            Atualizar
          </DsButton>
        </div>
      </div>

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

      {degraded ? (
        <DsBanner kind="degraded">
          Conexão do WhatsApp {connStatus === "reconectando" ? "reconectando" : "offline"}.
          O atendimento está degradado e o envio de respostas está desabilitado.
        </DsBanner>
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
        ) : showInitialFailure ? null : (
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

        {showSkeleton || showInitialFailure ? null : selected ? (
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
            showBack={isMobile}
            onBack={() => setSelectedId(null)}
          />
        ) : (
          <div className="empty-pane">
            <DsEmptyState
              title="Nenhuma conversa por aqui ainda."
              hint="Assim que alguém falar com o número oficial da igreja, a conversa aparece nesta lista."
            />
          </div>
        )}

        {selected && panelOpen ? (
          <>
            {/* Botão semântico (Gate 8); fora do tab order — Esc e o trap do
                drawer cobrem o teclado (padrão do shell/Gate 6.1). */}
            <button
              type="button"
              className="panel-backdrop"
              aria-label="Fechar painel de dados"
              tabIndex={-1}
              onClick={() => setPanelOpen(false)}
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

      {/* Feedback: visual da fundação; COMPORTAMENTO atual preservado (ok e
          err somem em 3200ms via flashToast — DsToast mudaria o err para
          persistente, o que seria delta funcional). */}
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
