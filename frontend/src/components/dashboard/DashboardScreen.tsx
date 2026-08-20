"use client";

/**
 * Tela #dashboard, composta por responsabilidades acumuladas (screen `dashboard`).
 *
 * Quando há capacidade operacional, a fila autorizada domina a primeira dobra.
 * Membro, operador e liderança sem tipo de fila recebem Agenda, avisos, célula
 * e atalhos reais, sem um template pastoral indevido.
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
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

import { DiamondMark } from "@/components/brand/DiamondMark";
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsField } from "@/components/ds/Field";
import { DsToast, DsToastRegion } from "@/components/ds/Toast";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  getMyNotices,
  listNotices,
  type DiscipleNotice,
  type Notice,
  type NoticePage,
} from "@/lib/cell-notices-api";
import {
  getLedCellsTodayContext,
  getNextMeeting,
  type LedCellsTodayContext,
  type NextMeetingBody,
  type NextMeetingResponse,
} from "@/lib/cells-api";
import {
  ApiError,
  StaleItemError,
  clearAuthedResponseCache,
  fetchCells,
  fetchOverview,
  fetchRemainingWorkQueuePages,
  fetchTeamLookup,
  fetchWorkQueuePage,
  linkCell,
  queueAction,
  queueFonovisita,
  sendInternalMessage,
  type Cell,
  type OverviewStats,
  type TeamLookupMember,
  type WorkItem,
} from "@/lib/dashboard-api";
import {
  resolveDashboardResponsibilities,
  type DashboardShortcutTarget,
} from "@/lib/dashboard-responsibilities";
import { compareUrgency } from "@/lib/deadline";
import { fetchUpcomingEvents, type EventItem } from "@/lib/events-api";
import { Icon, type IconKey } from "@/lib/icons";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { normalizeRoles, ROLE_DEFS, sortedRoles } from "@/lib/roles";
import { useHashRoute } from "@/lib/use-hash-route";

import { NextActions } from "./NextActions";
import { TodayContext } from "./TodayContext";
import { WorkQueueItem } from "./WorkQueueItem";

const TICK_MS = 30_000;
const RESOLVE_ANIM_MS = 220;
const DASHBOARD_QUEUE_PAGE_SIZE = 25;

type Tab = "todos" | "meus";
type ModalKind = "assign" | "message" | "linkCell";

function activateDashboardLink(
  event: ReactMouseEvent<HTMLAnchorElement>,
  target: string,
  onNavigate: (target: string) => void,
): void {
  if (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }
  event.preventDefault();
  onNavigate(target);
}

interface ModalState {
  kind: ModalKind;
  item: WorkItem;
}

interface Toast {
  kind: "ok" | "err";
  text: string;
}

interface ContextUnavailable {
  events: boolean;
  meeting: boolean;
  notices: boolean;
}

type CellContextMode = "leader" | "member" | "general";

const DASHBOARD_HONORIFIC =
  /^(?:pr(?:a)?\.?|pastor(?:a)?|bispo(?:a)?|ap\.?|ap[oó]stol(?:o|a))$/i;

/** Usa o nome de conversa quando existe e evita saudações como "Boa noite, Pr.". */
export function dashboardGreetingName(
  chatName: string | null | undefined,
  fullName: string | null | undefined,
): string {
  const parts = (chatName?.trim() || fullName?.trim() || "")
    .split(/\s+/)
    .map((part) => part.replace(/,$/, ""))
    .filter(Boolean);

  return parts.find((part) => !DASHBOARD_HONORIFIC.test(part)) ?? parts[0] ?? "";
}

function toDashboardNotice(notice: Notice): DiscipleNotice {
  return {
    id: notice.id,
    origem: notice.origem,
    escopo: notice.escopo,
    titulo: notice.titulo,
    conteudo: notice.conteudo,
    publicado_em: notice.publicado_em ?? "",
  };
}

function noticesForResponsibility(
  page: NoticePage,
  ledContext: LedCellsTodayContext | null,
): DiscipleNotice[] {
  const ledCellIds = new Set(ledContext?.cells.map((cell) => cell.id) ?? []);
  return page.items
    .filter(
      (notice) =>
        notice.escopo === "igreja" ||
        (notice.escopo === "celula" &&
          notice.celula_id != null &&
          ledCellIds.has(notice.celula_id)),
    )
    .map(toDashboardNotice);
}

/** Linha do resumo do escopo. `value` undefined = dado indisponível ("—"). */
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
  const [members, setMembers] = useState<TeamLookupMember[]>([]);
  const [cells, setCells] = useState<Cell[]>([]);
  const [overview, setOverview] = useState<OverviewStats | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [meeting, setMeeting] = useState<NextMeetingBody | null>(null);
  const [notices, setNotices] = useState<DiscipleNotice[]>([]);
  const [loading, setLoading] = useState(true);
  const [queueTotal, setQueueTotal] = useState(0);
  const [queueHydrating, setQueueHydrating] = useState(false);
  const [queueHydrationError, setQueueHydrationError] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const [loadedOperationsKey, setLoadedOperationsKey] = useState<string | null>(null);
  const [contextLoading, setContextLoading] = useState(true);
  const [loadedContextKey, setLoadedContextKey] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const [teamUnavailable, setTeamUnavailable] = useState(false);
  const [cellsUnavailable, setCellsUnavailable] = useState(false);
  const [overviewUnavailable, setOverviewUnavailable] = useState(false);
  const [supplementsReady, setSupplementsReady] = useState(false);
  const [contextError, setContextError] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const [contextUnavailable, setContextUnavailable] = useState<ContextUnavailable>({
    events: false,
    meeting: false,
    notices: false,
  });
  const [now, setNow] = useState(() => Date.now());
  const [tab, setTab] = useState<Tab>("todos");
  const [queueExpanded, setQueueExpanded] = useState(false);

  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [resolvingIds, setResolvingIds] = useState<Set<string>>(new Set());
  const [conflicts, setConflicts] = useState<Record<string, string>>({});
  const [modal, setModal] = useState<ModalState | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [queueFocusRequest, setQueueFocusRequest] = useState(0);

  const rolesKey = [...(user?.roles ?? [])].sort().join("|");
  const responsibilities = resolveDashboardResponsibilities(user?.roles ?? []);
  const normalizedRoles = normalizeRoles(user?.roles ?? []);
  const {
    hasWorkQueue,
    canLinkCell,
    canAssignQueue,
    showOverview,
    showTeamWorkload,
  } = responsibilities;
  const canSeeCalendar = user ? canSee("calendario", user.roles, matrix) : false;
  const canSeeMyCell = user ? canSee("minha-celula", user.roles, matrix) : false;
  const cellContextMode: CellContextMode = normalizedRoles.includes("lider_celula")
    ? "leader"
    : normalizedRoles.includes("membro")
      ? "member"
      : "general";
  const showCellMeeting = canSeeMyCell && cellContextMode !== "general";
  const shortcutTargets = responsibilities.shortcutCandidates
    .filter((target) => (user ? canSee(target, user.roles, matrix) : false))
    .slice(0, 4) as DashboardShortcutTarget[];
  const operationsKey =
    token && hasWorkQueue ? `${token}:${rolesKey || "sem-papel"}` : null;
  const contextKey = token
    ? `${token}:${rolesKey || "sem-papel"}:${canSeeCalendar ? "agenda" : "sem-agenda"}:${cellContextMode}:${
        showCellMeeting ? "reuniao" : "sem-reuniao"
      }`
    : null;
  const operationsReady = operationsKey != null && loadedOperationsKey === operationsKey;
  const contextReady = contextKey != null && loadedContextKey === contextKey;
  const canUseAssignment = canAssignQueue && supplementsReady && !teamUnavailable;
  const canUseCellLink = canLinkCell && supplementsReady && !cellsUnavailable;
  const memberById = useMemo(
    () => new Map(members.map((m) => [m.usuarioId, m])),
    [members],
  );
  const operationsRequest = useRef(0);
  const contextRequest = useRef(0);
  const locallyRemovedItemIds = useRef<Set<string>>(new Set());
  const modalRef = useRef<ModalState | null>(modal);
  modalRef.current = modal;

  useEffect(() => {
    if (canUseCellLink) return;
    setCells([]);
    setModal((current) => (current?.kind === "linkCell" ? null : current));
  }, [canUseCellLink]);

  useEffect(() => {
    if (canUseAssignment) return;
    setModal((current) => (current?.kind === "assign" ? null : current));
  }, [canUseAssignment]);

  useEffect(() => {
    setModal((current) => {
      if (current?.kind !== "message") return current;
      const fresh = items.find((item) => item.id === current.item.id);
      return fresh?.canMessage ? { ...current, item: fresh } : null;
    });
  }, [items]);

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

  const loadOperations = useCallback(
    async (mode: "initial" | "retry", expectedKey: string) => {
      if (!token || !hasWorkQueue) return;
      const requestId = ++operationsRequest.current;
      setLoading(true);
      setQueueHydrating(false);
      setQueueHydrationError(null);
      setSupplementsReady(false);
      locallyRemovedItemIds.current = new Set();
      if (mode === "retry") {
        const paths = [
          "/work-queue?",
          ...(canAssignQueue ? ["/team/lookup?"] : []),
          ...(canLinkCell ? ["/cells?"] : []),
          "/dashboard/overview",
        ];
        clearAuthedResponseCache(token, paths);
      }
      setOperationError(null);

      const supplementsPromise = Promise.allSettled([
        canAssignQueue ? fetchTeamLookup(token) : Promise.resolve(null),
        canLinkCell ? fetchCells(token) : Promise.resolve(null),
        showOverview ? fetchOverview(token) : Promise.resolve(null),
      ]);

      try {
        const firstPage = await fetchWorkQueuePage(
          token,
          1,
          DASHBOARD_QUEUE_PAGE_SIZE,
        );
        if (requestId !== operationsRequest.current) return;

        setItems(firstPage.items);
        setQueueTotal(firstPage.total);
        setLoadedOperationsKey(expectedKey);
        setLoading(false);

        const needsHydration = firstPage.items.length < firstPage.total;
        setQueueHydrating(needsHydration);

        const applySupplements = async () => {
          const [teamResult, cellResult, overviewResult] = await supplementsPromise;
          if (requestId !== operationsRequest.current) return;

          const expired = [teamResult, cellResult, overviewResult].find(
            (result) =>
              result.status === "rejected" &&
              result.reason instanceof SessionExpiredError,
          );
          if (
            expired &&
            expired.status === "rejected" &&
            handleSessionError(expired.reason)
          ) {
            return;
          }

          const team = teamResult.status === "fulfilled" ? teamResult.value : null;
          const cellPage = cellResult.status === "fulfilled" ? cellResult.value : null;
          const nextOverview =
            overviewResult.status === "fulfilled" ? overviewResult.value : null;

          setMembers(team?.items ?? []);
          setCells(cellPage?.items ?? []);
          setOverview(nextOverview);
          setTeamUnavailable(canAssignQueue && teamResult.status === "rejected");
          setCellsUnavailable(canLinkCell && cellResult.status === "rejected");
          setOverviewUnavailable(showOverview && overviewResult.status === "rejected");
          setSupplementsReady(true);
        };

        const hydrateQueue = async () => {
          if (!needsHydration) return;
          try {
            const remainder = await fetchRemainingWorkQueuePages(token, firstPage);
            if (requestId !== operationsRequest.current) return;

            const stableFirstPage = remainder.firstPage ?? firstPage;
            const completeServerItems = [
              ...stableFirstPage.items,
              ...remainder.items,
            ];
            const removedIds = locallyRemovedItemIds.current;
            const removedCount = completeServerItems.filter((item) =>
              removedIds.has(item.id),
            ).length;

            setItems((current) => {
              const currentById = new Map(current.map((item) => [item.id, item]));
              const seen = new Set<string>();
              const next: WorkItem[] = [];
              for (const serverItem of completeServerItems) {
                if (seen.has(serverItem.id) || removedIds.has(serverItem.id)) continue;
                seen.add(serverItem.id);
                next.push(currentById.get(serverItem.id) ?? serverItem);
              }
              return next;
            });
            setQueueTotal(Math.max(0, remainder.total - removedCount));
          } catch (err) {
            if (requestId !== operationsRequest.current) return;
            if (handleSessionError(err)) return;
            setQueueHydrationError({
              key: expectedKey,
              message:
                err instanceof ApiError
                  ? err.message
                  : "A fila foi carregada parcialmente. Tente novamente para buscar todas as ações.",
            });
          } finally {
            if (requestId === operationsRequest.current) setQueueHydrating(false);
          }
        };

        await Promise.allSettled([applySupplements(), hydrateQueue()]);
      } catch (err) {
        if (requestId !== operationsRequest.current) return;
        if (handleSessionError(err)) return;
        const message =
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar a fila de trabalho.";
        setOperationError({ key: expectedKey, message });
      } finally {
        if (requestId === operationsRequest.current) setLoading(false);
      }
    },
    [
      token,
      hasWorkQueue,
      canAssignQueue,
      canLinkCell,
      showOverview,
      handleSessionError,
    ],
  );

  useEffect(() => {
    if (!operationsKey) {
      operationsRequest.current += 1;
      setItems([]);
      setQueueTotal(0);
      setQueueHydrating(false);
      setQueueHydrationError(null);
      locallyRemovedItemIds.current = new Set();
      setMembers([]);
      setCells([]);
      setOverview(null);
      setTeamUnavailable(false);
      setCellsUnavailable(false);
      setOverviewUnavailable(false);
      setSupplementsReady(false);
      setModal(null);
      setLoadedOperationsKey(null);
      setLoading(false);
      return;
    }
    setItems([]);
    setQueueTotal(0);
    setQueueHydrating(false);
    setQueueHydrationError(null);
    locallyRemovedItemIds.current = new Set();
    setMembers([]);
    setCells([]);
    setOverview(null);
    setTeamUnavailable(false);
    setCellsUnavailable(false);
    setOverviewUnavailable(false);
    setSupplementsReady(false);
    setModal(null);
    setLoadedOperationsKey(null);
    void loadOperations("initial", operationsKey);
  }, [operationsKey, loadOperations]);

  const loadContext = useCallback(
    async (mode: "initial" | "retry", expectedKey: string) => {
      if (!token) return;
      const requestId = ++contextRequest.current;
      setContextLoading(true);
      if (mode === "retry") {
        clearAuthedResponseCache(token, [
          ...(canSeeCalendar ? ["/events?"] : []),
          ...(showCellMeeting && cellContextMode === "leader"
            ? ["/cells/me/leading", "/cells/"]
            : []),
          ...(showCellMeeting && cellContextMode === "member"
            ? ["/cells/me/next-meeting"]
            : []),
          ...(cellContextMode === "member"
            ? ["/cells/me/notices"]
            : ["/cell-notices?"]),
        ]);
      }
      setContextError(null);

      const meetingPromise: Promise<
        LedCellsTodayContext | NextMeetingResponse | null
      > =
        showCellMeeting && cellContextMode === "leader"
          ? getLedCellsTodayContext(token)
          : showCellMeeting && cellContextMode === "member"
            ? getNextMeeting(token)
            : Promise.resolve(null);
      const noticePromise: Promise<DiscipleNotice[] | NoticePage> =
        cellContextMode === "member" ? getMyNotices(token) : listNotices(token);
      const [eventResult, meetingResult, noticeResult] = await Promise.allSettled([
        canSeeCalendar ? fetchUpcomingEvents(token) : Promise.resolve(null),
        meetingPromise,
        noticePromise,
      ]);
      if (requestId !== contextRequest.current) return;

      const failures = [eventResult, meetingResult, noticeResult].filter(
        (result) => result.status === "rejected",
      );
      const expired = failures.find(
        (result) =>
          result.status === "rejected" && result.reason instanceof SessionExpiredError,
      );
      if (expired && expired.status === "rejected" && handleSessionError(expired.reason)) {
        return;
      }

      const leaderCellScopeUnavailable =
        cellContextMode === "leader" && meetingResult.status === "rejected";

      setContextUnavailable({
        events: canSeeCalendar && eventResult.status === "rejected",
        meeting: showCellMeeting && meetingResult.status === "rejected",
        notices: noticeResult.status === "rejected" || leaderCellScopeUnavailable,
      });

      if (eventResult.status === "fulfilled") {
        setEvents(eventResult.value?.items ?? []);
      }
      if (meetingResult.status === "fulfilled") {
        setMeeting(meetingResult.value?.meeting ?? null);
      } else {
        setMeeting(null);
      }
      if (noticeResult.status === "fulfilled" && !leaderCellScopeUnavailable) {
        if (Array.isArray(noticeResult.value)) {
          setNotices(noticeResult.value);
        } else {
          const ledContext =
            cellContextMode === "leader" && meetingResult.status === "fulfilled"
              ? (meetingResult.value as LedCellsTodayContext | null)
              : null;
          setNotices(noticesForResponsibility(noticeResult.value, ledContext));
        }
      }

      if (failures.length > 0) {
        setContextError({
          key: expectedKey,
          message:
            failures.length === 3
              ? "Não foi possível carregar agenda, reunião e avisos."
              : "Algumas informações de hoje não puderam ser atualizadas.",
        });
      }
      setLoadedContextKey(expectedKey);
      setContextLoading(false);
    },
    [
      token,
      canSeeCalendar,
      showCellMeeting,
      cellContextMode,
      handleSessionError,
    ],
  );

  useEffect(() => {
    if (!contextKey) {
      contextRequest.current += 1;
      setEvents([]);
      setMeeting(null);
      setNotices([]);
      setContextUnavailable({ events: false, meeting: false, notices: false });
      setLoadedContextKey(null);
      setContextLoading(false);
      return;
    }
    setEvents([]);
    setMeeting(null);
    setNotices([]);
    setContextUnavailable({ events: false, meeting: false, notices: false });
    setLoadedContextKey(null);
    void loadContext("initial", contextKey);
  }, [contextKey, loadContext]);

  // ---- tick para transição de prazos (sem reload) -------------------------
  useEffect(() => {
    if (!hasWorkQueue) return;
    const id = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, [hasWorkQueue]);

  // Sucesso some sozinho; erro permanece até a pessoa fechar.
  const flashToast = useCallback((nextToast: Toast) => setToast(nextToast), []);

  // ---- itens abertos, filtrados e ordenados -------------------------------
  const openItems = useMemo(
    () => (operationsReady ? items.filter((i) => i.status !== "resolvido") : []),
    [items, operationsReady],
  );

  const visibleItems = useMemo(() => {
    const filtered =
      tab === "meus" && user
        ? openItems.filter((i) => i.responsavelId === user.appUserId)
        : openItems;
    return [...filtered].sort((a, b) => compareUrgency(a, b, now));
  }, [openItems, tab, user, now]);
  const displayedItems = queueExpanded ? visibleItems : visibleItems.slice(0, 3);
  const queueComplete =
    operationsReady && !queueHydrating && queueHydrationError?.key !== operationsKey;
  const showQueueToggle = queueExpanded || visibleItems.length > 3;
  const queueToggleLabel = queueExpanded
    ? "Mostrar menos"
    : queueComplete
      ? `Ver todas as ${visibleItems.length} ações`
      : `Ver ${visibleItems.length} ações já carregadas`;

  useEffect(() => setQueueExpanded(false), [operationsKey, tab]);

  useEffect(() => {
    if (queueFocusRequest === 0) return;
    document.getElementById("dashboard-queue-title")?.focus();
  }, [queueFocusRequest]);

  // ---- hero: saudação + data + nº de ações pendentes ----------------------
  const firstName = dashboardGreetingName(user?.chatNome, user?.nome);
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
  const acoesAbertas = queueComplete
    ? openItems.length
    : Math.max(queueTotal, openItems.length);

  // ---- resumo do escopo (dados reais; sem deltas inventados) ----------------
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
      sub: "itens abertos no seu escopo",
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
    locallyRemovedItemIds.current.add(id);
    setQueueTotal((current) => Math.max(0, current - 1));
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
        setBusyItemId((current) => (current === item.id ? null : current));
      }
    },
    [token, user, clearConflict, patchItem, flashToast, handleSessionError, handleStale],
  );

  const handleAssign = useCallback(
    async (item: WorkItem, responsavelId: string) => {
      if (!canUseAssignment || !token) return;
      setBusyItemId(item.id);
      clearConflict(item.id);
      try {
        const res = await queueAction(token, item.id, "assign", responsavelId);
        const leavesPersonalFilter =
          tab === "meus" && user != null && res.responsavelId !== user.appUserId;
        const currentModal = modalRef.current;
        const ownsOrClosedModal =
          currentModal == null ||
          (currentModal.kind === "assign" && currentModal.item.id === item.id);
        patchItem(item.id, { status: res.status, responsavelId: res.responsavelId });
        const name = memberById.get(responsavelId)?.nome ?? "responsável";
        flashToast({ kind: "ok", text: `Atribuído a ${name}.` });
        setModal((current) =>
          current?.kind === "assign" && current.item.id === item.id ? null : current,
        );
        if (leavesPersonalFilter && ownsOrClosedModal) {
          setQueueFocusRequest((request) => request + 1);
        }
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
        setBusyItemId((current) => (current === item.id ? null : current));
      }
    },
    [
      canUseAssignment,
      token,
      clearConflict,
      patchItem,
      memberById,
      tab,
      user,
      flashToast,
      handleSessionError,
      handleStale,
    ],
  );

  const handleMessage = useCallback(
    async (item: WorkItem, mensagem: string) => {
      if (!item.canMessage || !token) return;
      setBusyItemId(item.id);
      try {
        await sendInternalMessage(token, item.id, mensagem);
        flashToast({ kind: "ok", text: "Mensagem enviada pelo WhatsApp." });
        setModal((current) =>
          current?.kind === "message" && current.item.id === item.id ? null : current,
        );
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível enviar.",
        });
      } finally {
        setBusyItemId((current) => (current === item.id ? null : current));
      }
    },
    [token, flashToast, handleSessionError],
  );

  const handleLinkCell = useCallback(
    async (item: WorkItem, celulaId: string) => {
      if (!canUseCellLink || !token || !item.pessoaId) return;
      setBusyItemId(item.id);
      try {
        await linkCell(token, item.pessoaId, celulaId);
        const currentModal = modalRef.current;
        const ownsOrClosedModal =
          currentModal == null ||
          (currentModal.kind === "linkCell" && currentModal.item.id === item.id);
        flashToast({ kind: "ok", text: "Conectado à célula." });
        removeWithAnim(item.id);
        setModal((current) =>
          current?.kind === "linkCell" && current.item.id === item.id
            ? null
            : current,
        );
        if (ownsOrClosedModal) setQueueFocusRequest((request) => request + 1);
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível conectar.",
        });
      } finally {
        setBusyItemId((current) => (current === item.id ? null : current));
      }
    },
    [canUseCellLink, token, flashToast, removeWithAnim, handleSessionError],
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
        setBusyItemId((current) => (current === item.id ? null : current));
      }
    },
    [token, flashToast, handleSessionError],
  );

  const handleRefresh = useCallback(() => {
    if (operationsKey) void loadOperations("retry", operationsKey);
    if (contextKey) void loadContext("retry", contextKey);
  }, [operationsKey, contextKey, loadOperations, loadContext]);

  const showSkeleton = hasWorkQueue && loading && !operationsReady;
  const showContextSkeleton = contextLoading && !contextReady;
  const isEmpty =
    operationsReady &&
    visibleItems.length === 0 &&
    (queueComplete || (tab === "todos" && queueTotal === 0));
  const isPartialFilterEmpty =
    operationsReady && visibleItems.length === 0 && !isEmpty;
  const dashboardUpdating = loading || queueHydrating || contextLoading;
  const unavailableOperationParts = [
    ...(teamUnavailable ? ["equipe"] : []),
    ...(cellsUnavailable ? ["células"] : []),
    ...(overviewUnavailable ? ["visão geral"] : []),
  ];

  return (
    <div className="screen dashboard dh" key="dashboard">
      {/* Farol compacto: calor pastoral, estado real do dia e uma ação quieta. */}
      <header
        className={`dh-hero${
          hasWorkQueue && acoesAbertas > 0 ? " has-actions" : " is-calm"
        }`}
      >
        <DiamondMark className="dh-hero-mark" size={42} title="" />
        <div className="dh-greet">
          <p className="dh-date">
            <span>Seu dia em foco</span>
            <span aria-hidden="true">·</span>
            <span>{todayLabel}</span>
          </p>
          <h2 className="dh-title">
            {greeting}
            {firstName ? `, ${firstName}` : ""}
          </h2>
          {showSkeleton ? (
            <div className="sk-line sk-md" aria-hidden="true" />
          ) : hasWorkQueue && operationError?.key === operationsKey ? (
            <p className="dh-lead">Não foi possível confirmar suas ações agora.</p>
          ) : hasWorkQueue && acoesAbertas > 0 ? (
            <p className="dh-lead">
              Você tem{" "}
              <strong>
                {acoesAbertas} {acoesAbertas === 1 ? "ação" : "ações"}
              </strong>{" "}
              que {acoesAbertas === 1 ? "precisa" : "precisam"} de atenção.
            </p>
          ) : hasWorkQueue ? (
            <p className="dh-lead">{responsibilities.emptyQueueText}</p>
          ) : (
            <p className="dh-lead">
              Agenda, avisos e seus espaços reunidos para orientar o próximo passo.
            </p>
          )}
        </div>
        <div className="dh-hero-actions">
          {hasWorkQueue && !showSkeleton && operationError?.key !== operationsKey ? (
            <span className="dh-focus-state" aria-hidden="true">
              <span className="dh-focus-dot" />
              {acoesAbertas > 0
                ? `${acoesAbertas} ${acoesAbertas === 1 ? "cuidado" : "cuidados"}`
                : "Tudo em ordem"}
            </span>
          ) : null}
          <DsButton
            variant="secondary"
            onClick={handleRefresh}
            disabled={dashboardUpdating}
            aria-busy={dashboardUpdating || undefined}
          >
            <Icon name="refresh" />
            <span>Atualizar</span>
          </DsButton>
        </div>
      </header>

      <p className="sr-only" role="status" aria-live="polite">
        {dashboardUpdating
          ? "Atualizando as informações de hoje."
          : hasWorkQueue && operationsReady && queueComplete
            ? `${openItems.length} ${openItems.length === 1 ? "ação disponível" : "ações disponíveis"}.`
            : "Informações de hoje atualizadas."}
      </p>

      {hasWorkQueue && operationError?.key === operationsKey ? (
        <DsBanner
          kind="error"
          action={
            <DsButton
              variant="secondary"
              onClick={handleRefresh}
              disabled={loading || queueHydrating || contextLoading}
            >
              Tentar novamente
            </DsButton>
          }
        >
          {operationError.message}
        </DsBanner>
      ) : null}

      {queueHydrationError?.key === operationsKey ? (
        <DsBanner
          kind="degraded"
          action={
            <DsButton
              variant="secondary"
              onClick={handleRefresh}
              disabled={loading || queueHydrating || contextLoading}
            >
              Tentar novamente
            </DsButton>
          }
        >
          {queueHydrationError.message} {openItems.length} de {queueTotal} ações estão
          disponíveis.
        </DsBanner>
      ) : null}

      {operationsReady && supplementsReady && unavailableOperationParts.length > 0 ? (
        <DsBanner kind="degraded">
          {queueComplete
            ? "A fila está atualizada."
            : "As ações já carregadas permanecem disponíveis."}{" "}
          Dados complementares indisponíveis agora:{" "}
          {unavailableOperationParts.join(", ")}.
        </DsBanner>
      ) : null}

      {contextError?.key === contextKey ? (
        <DsBanner
          kind="degraded"
          action={
            <DsButton
              variant="secondary"
              onClick={handleRefresh}
              disabled={loading || queueHydrating || contextLoading}
            >
              Tentar novamente
            </DsButton>
          }
        >
          {contextError.message}
        </DsBanner>
      ) : null}

      <div className={`dh-grid${hasWorkQueue ? "" : " dh-grid--home"}`}>
        {/* A fila autorizada domina a primeira dobra quando existe. */}
        {hasWorkQueue ? (
          <section
            className="dh-main dh-workboard"
            aria-label={responsibilities.queueTitle}
            aria-busy={loading || queueHydrating}
          >
          <div className="dh-queue-head">
            <div className="dh-queue-heading">
              <span className="dh-queue-symbol" aria-hidden="true">
                <Icon name="bell" />
              </span>
              <div className="dh-queue-titles">
                <span className="dh-queue-title-line">
                  <h3 id="dashboard-queue-title" className="dh-queue-title" tabIndex={-1}>
                    {responsibilities.queueTitle}
                  </h3>
                  {!showSkeleton && operationsReady ? (
                    <span className="dh-queue-count" aria-hidden="true">
                      {acoesAbertas}
                    </span>
                  ) : null}
                </span>
                <p className="dh-queue-sub">{responsibilities.queueHint}</p>
              </div>
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

          {operationsReady && queueHydrating ? (
            <p className="dh-queue-progress">
              {tab === "meus"
                ? "Conferindo todas as páginas para completar suas ações."
                : `${openItems.length} de ${queueTotal} ações carregadas. Completando a fila.`}
            </p>
          ) : null}

          {showSkeleton ? (
            <div className="dh-queue" aria-hidden="true">
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
          ) : !operationsReady ? (
            <DsEmptyState
              title="A fila não pôde ser carregada."
              hint="Use Tentar novamente para buscar as ações autorizadas."
            />
          ) : isPartialFilterEmpty ? (
            <DsEmptyState
              title={
                tab === "meus"
                  ? "Conferindo suas ações."
                  : "A fila está disponível parcialmente."
              }
              hint={
                queueHydrating
                  ? "Aguarde a carga das páginas restantes."
                  : "Use Tentar novamente para confirmar todas as ações."
              }
            />
          ) : isEmpty ? (
            <DsEmptyState
              title="Fila zerada."
              hint={responsibilities.emptyQueueText}
            />
          ) : (
            <>
              <div className="dh-queue" id="dashboard-work-queue" role="list">
                {displayedItems.map((item) => (
                  <WorkQueueItem
                  key={item.id}
                  item={item}
                  now={now}
                  responsibleName={
                    item.responsavelId
                      ? memberById.get(item.responsavelId)?.nome ?? null
                      : null
                  }
                  canLinkCell={canUseCellLink}
                  canAssignQueue={canUseAssignment}
                  busy={busyItemId !== null}
                  resolving={resolvingIds.has(item.id)}
                  conflict={conflicts[item.id] ?? null}
                  onAssume={handleAssume}
                  onAssign={(it) => {
                    if (canUseAssignment) setModal({ kind: "assign", item: it });
                  }}
                  onMessage={(it) => {
                    if (it.canMessage) setModal({ kind: "message", item: it });
                  }}
                  onLinkCell={(it) => {
                    if (canUseCellLink) setModal({ kind: "linkCell", item: it });
                  }}
                  onFonovisita={handleFonovisita}
                  />
                ))}
              </div>
              {showQueueToggle ? (
                <button
                  type="button"
                  className="dh-queue-more"
                  aria-expanded={queueExpanded}
                  aria-controls="dashboard-work-queue"
                  onClick={() => setQueueExpanded((current) => !current)}
                >
                  {queueToggleLabel}
                </button>
              ) : null}
            </>
          )}

          {/* Totais do escopo atual ficam depois da fila e recolhidos por padrão. */}
          {!showSkeleton && operationsReady && supplementsReady && showOverview ? (
            <details className="dh-summary">
              <summary className="dh-summary-toggle">Visão geral do seu cuidado</summary>
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
        ) : (
          <section className="dh-main dh-home-main" aria-label={responsibilities.homeTitle}>
            <TodayContext
              title={responsibilities.homeTitle}
              loading={showContextSkeleton}
              events={events}
              meeting={meeting}
              notices={notices}
              showEvents={canSeeCalendar}
              showMeeting={showCellMeeting}
              shortcuts={shortcutTargets}
              prioritizeShortcuts={responsibilities.prioritizeShortcuts}
              eventsUnavailable={contextUnavailable.events}
              meetingUnavailable={contextUnavailable.meeting}
              noticesUnavailable={contextUnavailable.notices}
              onNavigate={navigate}
            />
          </section>
        )}

        {hasWorkQueue ? (
          <div className="dh-support" aria-label="Contexto das suas responsabilidades">
          {showSkeleton ? (
            <div className="dh-panel" aria-hidden="true">
              <div className="sk-line sk-md" />
              <div className="sk-line sk-sm" />
            </div>
          ) : (
            <>
              <TodayContext
                title="Hoje no seu contexto"
                loading={showContextSkeleton}
                events={events}
                meeting={meeting}
                notices={notices}
                showEvents={canSeeCalendar}
                showMeeting={showCellMeeting}
                shortcuts={shortcutTargets}
                prioritizeShortcuts={false}
                eventsUnavailable={contextUnavailable.events}
                meetingUnavailable={contextUnavailable.meeting}
                noticesUnavailable={contextUnavailable.notices}
                onNavigate={navigate}
              />
              {operationsReady && supplementsReady && showOverview && !overviewUnavailable ? (
                <JourneyCard
                  overview={overview}
                  canSeeAgente={user ? canSee("agente", user.roles, matrix) : false}
                  canNavigate={(target) =>
                    user ? canSee(target, user.roles, matrix) : false
                  }
                  onNavigate={navigate}
                />
              ) : null}
              {operationsReady && supplementsReady && showTeamWorkload ? (
                <NextActions items={openItems} members={members} />
              ) : null}
            </>
          )}
          </div>
        ) : null}
      </div>

      {modal &&
      (modal.kind !== "linkCell" || canUseCellLink) &&
      (modal.kind !== "assign" || canUseAssignment) &&
      (modal.kind !== "message" || modal.item.canMessage) ? (
        <ActionModal
          modal={modal}
          members={members}
          cells={cells}
          busy={busyItemId !== null}
          onClose={() => setModal(null)}
          onAssign={handleAssign}
          onMessage={handleMessage}
          onLinkCell={handleLinkCell}
        />
      ) : null}

      <DsToastRegion>
        {toast ? (
          toast.kind === "ok" ? (
            <DsToast
              kind="ok"
              text={toast.text}
              duration={3200}
              onDismiss={() => setToast(null)}
            />
          ) : (
            <DsToast kind="err" text={toast.text} onDismiss={() => setToast(null)} />
          )
        ) : null}
      </DsToastRegion>
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
  busy,
  onClose,
  onAssign,
  onMessage,
  onLinkCell,
}: {
  modal: ModalState;
  members: TeamLookupMember[];
  cells: Cell[];
  busy: boolean;
  onClose: () => void;
  onAssign: (item: WorkItem, responsavelId: string) => void;
  onMessage: (item: WorkItem, mensagem: string) => void;
  onLinkCell: (item: WorkItem, celulaId: string) => void;
}) {
  const { kind, item } = modal;
  const [text, setText] = useState("");
  const activeCells = cells.filter((c) => c.ativo && c.liderId);
  const eligibleMembers = members.filter((member) =>
    member.tiposFila.includes(item.tipo),
  );

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
          {eligibleMembers.length === 0 ? (
            <p className="dh-picker-empty">Nenhum membro disponível para atribuição.</p>
          ) : (
            eligibleMembers.map((m) => (
              <button
                type="button"
                key={m.usuarioId}
                className="dh-picker-row"
                disabled={busy}
                aria-busy={busy || undefined}
                onClick={() => onAssign(item, m.usuarioId)}
              >
                <span className="dh-picker-nm">{m.nome}</span>
                <span className="dh-picker-sub">
                  {sortedRoles(normalizeRoles(m.papeis))
                    .map((role) => ROLE_DEFS[role].label)
                    .join(" · ")}
                </span>
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
                disabled={busy}
                aria-busy={busy || undefined}
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
            disabled={busy}
            onChange={(e) => setText(e.target.value)}
            placeholder="Escreva a mensagem que será enviada pelo número oficial…"
            helper="Enviada pelo número oficial da igreja."
            // Gate 7.1: paridade com o autoFocus original — o DsDialog foca o
            // alvo marcado ao abrir (fluxo direto de escrita).
            data-autofocus=""
          />
          <div className="dh-modal-foot">
            <DsButton variant="tertiary" disabled={busy} onClick={onClose}>
              Cancelar
            </DsButton>
            <DsButton type="submit" disabled={!text.trim()} loading={busy}>
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
// Linha do resumo do escopo (mesmos dados dos antigos tiles/KPIs; clicável só
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
    <a
      href={`#${row.target}`}
      className="dh-summary-row is-link"
      onClick={(event) => activateDashboardLink(event, row.target!, onNavigate)}
    >
      {inner}
    </a>
  );
}

// ---------------------------------------------------------------------------
// O Caminho vivo usa somente as contagens atuais por etapa do overview.
// A linha conecta as quatro etapas sem transformar os totais em percentual.
// ---------------------------------------------------------------------------
const JOURNEY_STAGES: Array<{
  key: string;
  label: string;
  route: string;
  icon: IconKey;
}> = [
  { key: "ganhar", label: "Ganhar", route: "ganhar", icon: "ganhar" },
  { key: "consolidar", label: "Consolidar", route: "consolidar", icon: "consolidar" },
  { key: "discipular", label: "Discipular", route: "g12", icon: "discipular" },
  { key: "enviar", label: "Enviar", route: "enviar", icon: "enviar" },
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
  return (
    <section className="dh-panel dh-journey" aria-label="Jornada no seu escopo">
      <header className="dh-panel-head">
        <span className="dh-panel-symbol" aria-hidden="true">
          <Icon name="g12" />
        </span>
        <span>
          <h3 className="dh-panel-title">
            Jornada G12
            {scopeLabel ? <span className="dh-panel-count"> · {scopeLabel}</span> : null}
          </h3>
        </span>
      </header>
      <div className="dh-journey-track" role="list">
        {JOURNEY_STAGES.map((stage) => {
          const value = overview?.porEtapa?.[stage.key];
          const display = value == null ? "—" : value;
          const can = canNavigate(stage.route);
          const content = (
            <>
              <span className={`dh-journey-node ${stage.key}`} aria-hidden="true">
                <Icon name={stage.icon} />
              </span>
              <span className="dh-journey-copy">
                <span className="dh-journey-label">{stage.label}</span>
                <span className="dh-journey-meta">
                  <strong className="dh-journey-val num">{display}</strong>{" "}
                  {value === 1 ? "pessoa" : "pessoas"}
                </span>
              </span>
            </>
          );
          return (
            <div className="dh-journey-item" key={stage.key} role="listitem">
              {can ? (
                <a
                  href={`#${stage.route}`}
                  className="dh-journey-row is-link"
                  onClick={(event) =>
                    activateDashboardLink(event, stage.route, onNavigate)
                  }
                >
                  {content}
                </a>
              ) : (
                <div className="dh-journey-row">{content}</div>
              )}
            </div>
          );
        })}
        <span className="dh-journey-diamond" aria-hidden="true" />
      </div>
      <div>
        {canSeeAgente ? (
          <div className="dh-journey-foot">
            Instruções e automações da igreja.{" "}
            <a
              href="#agente"
              className="dh-journey-cta"
              onClick={(event) => activateDashboardLink(event, "agente", onNavigate)}
            >
              Configurar agente
            </a>
          </div>
        ) : null}
      </div>
    </section>
  );
}
