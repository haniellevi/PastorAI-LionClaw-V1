/**
 * Cliente da API do dashboard (sprint Frontend Dashboard / Fila de Trabalho).
 * Consome a fila de trabalho, ações diretas e pipeline do backend (sprints 004/005).
 *
 * Contratos (SPEC 3.2 / routers existentes):
 *   GET  /work-queue                      -> Page<WorkItem>
 *   POST /work-queue/{itemId}/action      -> { status, itemId, responsavelId }
 *   POST /work-queue/{itemId}/message     -> { status, messageId }
 *   POST /contacts/{id}/cell              -> ContactOut
 *   POST /pipeline/fonovisita             -> { status, itemId }
 *   GET  /team                            -> Page<TeamMember>
 *   GET  /cells                           -> Page<Cell>
 *
 * 401 em qualquer chamada sinaliza sessão expirada (redireciona para #login).
 * 409 em ação na fila carrega o estado real do item (tratamento de concorrência).
 */

import { SessionExpiredError } from "./api";
import { AuthedResponseCache } from "./authed-response-cache";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const responseCache = new AuthedResponseCache();
const inFlightReads = new Map<string, Promise<Response>>();

/**
 * Somente leituras aquecidas pela navegação entram no cache. Manter uma lista
 * explícita evita alterar a semântica de telas administrativas, polling e
 * outros GETs que precisam refletir o servidor imediatamente.
 */
function cacheTtl(path: string): number {
  if (path.startsWith("/conversations?page=")) return 15_000;
  if (path.startsWith("/events?page=")) return 60_000;
  if (path.startsWith("/pipeline?")) return 30_000;
  if (path.startsWith("/work-queue?")) return 30_000;
  if (path.startsWith("/team/lookup?")) return 30_000;
  if (path.startsWith("/cells?")) return 30_000;
  if (path === "/dashboard/overview") return 30_000;
  return 0;
}

/** Invalida leituras recentes após refresh explícito, polling ou troca de sessão. */
export function clearAuthedResponseCache(token?: string, pathPrefixes?: string[]): void {
  responseCache.clear(token, pathPrefixes);
  if (!token) {
    inFlightReads.clear();
    return;
  }
  const tokenPrefix = `${token}\u0000`;
  for (const key of inFlightReads.keys()) {
    if (!key.startsWith(tokenPrefix)) continue;
    const path = key.slice(tokenPrefix.length);
    if (pathPrefixes?.length && !pathPrefixes.some((prefix) => path.startsWith(prefix))) {
      continue;
    }
    // Não cancela a requisição já enviada, mas impede que um refresh explícito
    // espere por ela ou que seu finally remova uma requisição nova do mapa.
    inFlightReads.delete(key);
  }
}

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

/** Tipos de item da fila pastoral (work_queue_items.tipo). */
export type WorkItemType =
  | "visitante"
  | "atendimento"
  | "relatorio"
  | "conectar_celula"
  | "fonovisita";

export interface WorkItem {
  id: string;
  tipo: string;
  titulo: string;
  contexto: string | null;
  status: string | null;
  pessoaId: string | null;
  responsavelId: string | null;
  prioridade: number | null;
  /** Capacidade por item, resolvida no backend conforme a conversa atribuída. */
  canMessage: boolean;
  /** ISO-8601 ou null quando o item não tem prazo. */
  prazo: string | null;
}

export interface TeamMember {
  usuarioId: string;
  nome: string;
  email: string;
  status: string | null;
  papeis: string[];
  pessoaId: string | null;
}

export interface TeamLookupMember extends TeamMember {
  /** Tipos de item que este usuário pode receber, derivados no servidor. */
  tiposFila: string[];
}

export interface Cell {
  id: string;
  nome: string;
  liderId: string | null;
  ativo: boolean;
}

/** Visão geral do dashboard (#2): totais por tipo/etapa + KPIs, escopados por papel. */
export interface OverviewStats {
  /** "igreja" (admin/pastor/sênior) ou "celula" (líder de célula, só as suas). */
  scope: string;
  total: number;
  decisoesJesus: number;
  celulasAtivas: number;
  /** Líderes de célula DERIVADOS (celulas.lider_id em célula ativa). */
  lideresCelula: number;
  semInteresse: number;
  porTipo: Record<string, number>;
  porEtapa: Record<string, number>;
}

export interface QueueActionResult {
  status: string;
  itemId: string;
  responsavelId: string | null;
}

/** Erro genérico de API (mensagem amigável já em pt-BR). */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Conflito de concorrência: item já assumido/resolvido por outro usuário. */
export class StaleItemError extends Error {
  readonly itemStatus: string | null;
  readonly responsavelId: string | null;
  constructor(message: string, itemStatus: string | null, responsavelId: string | null) {
    super(message);
    this.name = "StaleItemError";
    this.itemStatus = itemStatus;
    this.responsavelId = responsavelId;
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export async function authedFetch(
  token: string,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const method = (init?.method ?? "GET").toUpperCase();
  const cacheMode = init?.cache;
  const cacheEnabled = process.env.NODE_ENV !== "test";
  const ttlMs = cacheTtl(path);
  const cacheable =
    cacheEnabled && ttlMs > 0 && method === "GET" && !init?.body && !init?.headers;

  if (cacheEnabled && method !== "GET") {
    // Uma mutação pode alterar qualquer leitura da tela atual. O cache é curto,
    // mas invalidar agora evita mostrar um snapshot antigo após salvar/excluir.
    clearAuthedResponseCache(token);
  }

  if (cacheable && cacheMode !== "reload" && cacheMode !== "no-store") {
    const cached = responseCache.get(token, path);
    if (cached) return cached;
  }

  let res: Response;
  try {
    const request = () =>
      fetch(`${API_BASE}${path}`, {
        ...init,
        headers: {
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
          Authorization: `Bearer ${token}`,
          ...(init?.headers ?? {}),
        },
      });

    if (cacheable && cacheMode !== "no-store") {
      const key = `${token}\u0000${path}`;
      let pending = inFlightReads.get(key);
      if (!pending) {
        pending = request()
          .then((response) => {
            // Uma invalidação pode remover esta promessa e iniciar outra para
            // a mesma chave. Só a leitura ainda vigente pode repovoar o cache;
            // caso contrário, uma resposta antiga que termine por último
            // sobrescreveria o snapshot mais novo.
            if (inFlightReads.get(key) === pending) {
              responseCache.set(token, path, response, ttlMs);
            }
            return response;
          })
          .finally(() => {
            // Um refresh pode ter removido esta promessa e iniciado outra com
            // a mesma chave. A antiga nunca deve apagar a nova ao terminar.
            if (inFlightReads.get(key) === pending) inFlightReads.delete(key);
          });
        inFlightReads.set(key, pending);
      }
      // Cada consumidor recebe seu próprio body; o Response original fica só
      // como fonte das cópias e nunca é consumido diretamente.
      res = (await pending).clone();
    } else {
      res = await request();
    }
  } catch {
    throw new ApiError(0, "Falha de conexão. Verifique sua internet e tente novamente.");
  }
  if (res.status === 401) {
    throw new SessionExpiredError();
  }
  return res;
}

export async function readDetail(res: Response): Promise<string | null> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (isRecord(detail) && typeof detail.message === "string") return detail.message;
  } catch {
    /* corpo não-JSON */
  }
  return null;
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
/**
 * Lê uma página isolada da fila. O dashboard usa a página 1 para liberar a
 * primeira dobra sem esperar a paginação completa; consumidores que precisam
 * do conjunto inteiro continuam usando `fetchWorkQueue`.
 */
export async function fetchWorkQueuePage(
  token: string,
  page = 1,
  pageSize = 100,
  options?: { revalidate?: boolean },
): Promise<Page<WorkItem>> {
  const res = await authedFetch(
    token,
    `/work-queue?page=${page}&pageSize=${pageSize}`,
    options?.revalidate ? { cache: "reload" } : undefined,
  );
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a fila de trabalho.");
  }
  return (await res.json()) as Page<WorkItem>;
}

export interface WorkQueueRemainder {
  /** Somente itens posteriores à primeira página, sem repetir IDs já vistos. */
  items: WorkItem[];
  /** Total do snapshot estável confirmado ao fim da paginação. */
  total: number;
  /**
   * Página 1 revalidada do mesmo snapshot. É opcional apenas para manter
   * compatibilidade com consumidores que simulam o contrato em testes.
   */
  firstPage?: Page<WorkItem>;
}

const WORK_QUEUE_SNAPSHOT_ATTEMPTS = 3;

interface WorkQueueSnapshot {
  firstPage: Page<WorkItem>;
  /** Todos os itens, deduplicados e na ordem observada entre as páginas. */
  items: WorkItem[];
  /** Totais coerentes entre páginas e quantidade única igual ao total. */
  complete: boolean;
}

/**
 * Coleta uma visão integral da fila. Quando `firstPage` não é fornecida, toda
 * a coleta ignora cache; isso permite comparar duas passagens completas e
 * detectar também trocas compensadas nas páginas posteriores.
 */
async function collectWorkQueueSnapshot(
  token: string,
  pageSize: number,
  initialFirstPage?: Page<WorkItem>,
): Promise<WorkQueueSnapshot> {
  const firstPage =
    initialFirstPage ??
    (await fetchWorkQueuePage(token, 1, pageSize, {
      revalidate: true,
    }));
  const seenIds = new Set<string>();
  const items: WorkItem[] = [];
  for (const item of firstPage.items) {
    if (seenIds.has(item.id)) continue;
    seenIds.add(item.id);
    items.push(item);
  }

  let page = firstPage.page + 1;
  let pageRequests = 0;
  let totalsStayedStable = true;

  // Duas páginas extras toleram duplicatas transitórias, sem permitir que um
  // servidor instável repita páginas indefinidamente.
  const safePageSize = Math.max(1, firstPage.pageSize);
  const expectedRemainingPages = Math.max(
    0,
    Math.ceil(firstPage.total / safePageSize) - firstPage.page,
  );
  const maxPageRequests = Math.max(1, expectedRemainingPages + 2);
  while (seenIds.size < firstPage.total && pageRequests < maxPageRequests) {
    const chunk = await fetchWorkQueuePage(token, page, firstPage.pageSize, {
      revalidate: true,
    });
    pageRequests += 1;
    if (chunk.total !== firstPage.total) totalsStayedStable = false;
    if (chunk.items.length === 0) break;

    for (const item of chunk.items) {
      if (seenIds.has(item.id)) continue;
      seenIds.add(item.id);
      items.push(item);
    }
    page += 1;
  }

  return {
    firstPage,
    items,
    complete: totalsStayedStable && seenIds.size === firstPage.total,
  };
}

function sameWorkQueueSnapshot(
  left: WorkQueueSnapshot,
  right: WorkQueueSnapshot,
): boolean {
  if (
    !left.complete ||
    !right.complete ||
    left.firstPage.total !== right.firstPage.total ||
    left.items.length !== right.items.length
  ) {
    return false;
  }
  return left.items.every((item, index) => item.id === right.items[index]?.id);
}

/**
 * Completa uma primeira página já carregada. Separar as fases evita o waterfall
 * visual, preserva deduplicação por ID e mantém a função completa abaixo para
 * pré-carregamento e outros consumidores.
 */
export async function fetchRemainingWorkQueuePages(
  token: string,
  firstPage: Page<WorkItem>,
): Promise<WorkQueueRemainder> {
  let snapshot = await collectWorkQueueSnapshot(
    token,
    firstPage.pageSize,
    firstPage,
  );

  for (let attempt = 0; attempt < WORK_QUEUE_SNAPSHOT_ATTEMPTS; attempt += 1) {
    const verification = await collectWorkQueueSnapshot(token, firstPage.pageSize);
    if (sameWorkQueueSnapshot(snapshot, verification)) {
      const firstPageIds = new Set(
        verification.firstPage.items.map((item) => item.id),
      );
      return {
        firstPage: verification.firstPage,
        items: verification.items.filter((item) => !firstPageIds.has(item.id)),
        total: verification.firstPage.total,
      };
    }
    snapshot = verification;
  }

  throw new ApiError(
    409,
    "A fila mudou enquanto era carregada. A primeira página permanece disponível; tente novamente para confirmar todas as ações.",
  );
}

export async function fetchWorkQueue(token: string, pageSize = 100): Promise<Page<WorkItem>> {
  const firstPage = await fetchWorkQueuePage(token, 1, pageSize);
  if (firstPage.items.length >= firstPage.total) return firstPage;

  const remainder = await fetchRemainingWorkQueuePages(token, firstPage);
  const stableFirstPage = remainder.firstPage ?? firstPage;
  const seenIds = new Set<string>();
  const items = [...stableFirstPage.items, ...remainder.items].filter((item) => {
    if (seenIds.has(item.id)) return false;
    seenIds.add(item.id);
    return true;
  });
  return {
    items,
    page: 1,
    pageSize: stableFirstPage.pageSize,
    total: remainder.total,
  };
}

export async function fetchTeam(token: string, pageSize = 100): Promise<Page<TeamMember>> {
  const items: TeamMember[] = [];
  let page = 1;
  let total = 0;

  do {
    const res = await authedFetch(token, `/team?page=${page}&pageSize=${pageSize}`);
    if (!res.ok) {
      throw new ApiError(res.status, "Não foi possível carregar a equipe.");
    }
    const chunk = (await res.json()) as Page<TeamMember>;
    total = chunk.total;
    items.push(...chunk.items);
    if (chunk.items.length === 0) break;
    page += 1;
  } while (items.length < total);

  return { items, page: 1, pageSize, total };
}

/**
 * Busca ENXUTA de destinos elegíveis (id, nome, papéis, tipos de fila; e-mail
 * vazio) para o seletor de atribuição. O backend a restringe aos mesmos papéis
 * que podem atribuir a fila; os demais papéis não devem chamar este endpoint.
 * A lista completa com e-mail (GET /team) mantém seu contrato administrativo.
 */
export async function fetchTeamLookup(
  token: string,
  pageSize = 200,
): Promise<Page<TeamLookupMember>> {
  const items: TeamLookupMember[] = [];
  let page = 1;
  let total = 0;

  do {
    const res = await authedFetch(
      token,
      `/team/lookup?page=${page}&pageSize=${pageSize}`,
    );
    if (!res.ok) {
      throw new ApiError(res.status, "Não foi possível carregar a equipe.");
    }
    const chunk = (await res.json()) as Page<TeamLookupMember>;
    total = chunk.total;
    items.push(...chunk.items);
    if (chunk.items.length === 0) break;
    page += 1;
  } while (items.length < total);

  return { items, page: 1, pageSize, total };
}

export async function fetchOverview(token: string): Promise<OverviewStats> {
  const res = await authedFetch(token, `/dashboard/overview`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a visão geral.");
  }
  return (await res.json()) as OverviewStats;
}

export async function fetchCells(token: string, pageSize = 100): Promise<Page<Cell>> {
  const items: Cell[] = [];
  let page = 1;
  let total = 0;

  do {
    const res = await authedFetch(token, `/cells?page=${page}&pageSize=${pageSize}`);
    if (!res.ok) {
      throw new ApiError(res.status, "Não foi possível carregar as células.");
    }
    const chunk = (await res.json()) as Page<Cell>;
    total = chunk.total;
    items.push(...chunk.items);
    if (chunk.items.length === 0) break;
    page += 1;
  } while (items.length < total);

  return { items, page: 1, pageSize, total };
}

// ---------------------------------------------------------------------------
// Ações
// ---------------------------------------------------------------------------
export async function queueAction(
  token: string,
  itemId: string,
  action: "assume" | "assign",
  responsavelId?: string,
): Promise<QueueActionResult> {
  const res = await authedFetch(token, `/work-queue/${itemId}/action`, {
    method: "POST",
    body: JSON.stringify({ action, responsavelId: responsavelId ?? null }),
  });

  if (res.status === 409) {
    let message = "Item já tratado por outro usuário.";
    let itemStatus: string | null = null;
    let responsible: string | null = null;
    try {
      const body = (await res.json()) as { detail?: unknown };
      const detail = body.detail;
      if (isRecord(detail)) {
        if (typeof detail.message === "string") message = detail.message;
        if (typeof detail.status === "string") itemStatus = detail.status;
        if (typeof detail.responsavelId === "string") responsible = detail.responsavelId;
      }
    } catch {
      /* mantém defaults */
    }
    throw new StaleItemError(message, itemStatus, responsible);
  }

  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível executar a ação.");
  }
  return (await res.json()) as QueueActionResult;
}

export async function sendInternalMessage(
  token: string,
  itemId: string,
  mensagem: string,
): Promise<{ status: string; messageId: string }> {
  const res = await authedFetch(token, `/work-queue/${itemId}/message`, {
    method: "POST",
    body: JSON.stringify({ mensagem }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível enviar a mensagem.");
  }
  return (await res.json()) as { status: string; messageId: string };
}

export async function linkCell(
  token: string,
  contactId: string,
  celulaId: string,
): Promise<void> {
  const res = await authedFetch(token, `/contacts/${contactId}/cell`, {
    method: "POST",
    body: JSON.stringify({ celulaId }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível conectar à célula.");
  }
}

export async function queueFonovisita(
  token: string,
  pessoaId: string,
  contexto?: string,
): Promise<{ status: string; itemId: string }> {
  const res = await authedFetch(token, `/pipeline/fonovisita`, {
    method: "POST",
    body: JSON.stringify({ pessoaId, contexto: contexto ?? null }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível agendar a fonovisita.");
  }
  return (await res.json()) as { status: string; itemId: string };
}
