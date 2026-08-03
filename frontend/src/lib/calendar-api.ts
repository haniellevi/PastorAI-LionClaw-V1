/**
 * Cliente da conexão com o Google Agenda (módulo de Eventos, Fase 1).
 *
 * Contratos (app/routers/calendar.py) — todos admin-only, exceto o callback:
 *   GET    /calendar/status   -> { connected, calendarId, connectionVersion }
 *   GET    /calendar/connect  -> { authUrl }   (redireciona o navegador ao Google)
 *   GET    /calendar/list     -> { calendars: [{ id, summary, primary }] }
 *   PUT    /calendar          -> { connected, calendarId, connectionVersion }
 *                               (escolher a agenda sob uma conexão específica)
 *   DELETE /calendar          -> 204                          (desconectar)
 */

import { SessionExpiredError } from "./api";
import { ApiError, authedFetch, isRecord, readDetail } from "./dashboard-api";
import type { Role } from "./roles";

/**
 * A conta Google que autorizou não é a que o admin declarou.
 *
 * Erro próprio porque é o único caso com detalhe estruturado: o painel precisa
 * mostrar as DUAS contas para o admin corrigir. `ApiError` reduziria tudo a uma
 * string.
 */
export class GoogleAccountMismatchError extends Error {
  readonly expected: string;
  readonly verified: string;
  constructor(expected: string, verified: string) {
    super("A conta Google que autorizou não é a que você informou.");
    this.name = "GoogleAccountMismatchError";
    this.expected = expected;
    this.verified = verified;
  }
}

/**
 * O mesmo endereço Google agora representa outra identidade (`sub`).
 *
 * A API nunca expõe o `sub`; o tipo separado permite manter os controles da
 * conexão atual visíveis para que o admin consiga desconectá-la antes de tentar
 * novamente.
 */
export class GoogleAccountReidentifiedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "GoogleAccountReidentifiedError";
  }
}

export interface CalendarStatus {
  connected: boolean;
  calendarId: string | null;
  /** E-mail verificado da conta conectada; `null` em conexão legada. */
  googleAccountEmail: string | null;
  /** Revisão opaca da conexão que precisa acompanhar a seleção da agenda. */
  connectionVersion: string | null;
}

export interface CalendarOption {
  id: string;
  summary: string | null;
  primary: boolean;
}

/** Conectar/gerir a agenda é restrito ao papel admin (Configuração). */
export function canManageCalendar(roles: readonly Role[]): boolean {
  return roles.includes("admin");
}

export async function fetchCalendarStatus(token: string): Promise<CalendarStatus> {
  const res = await authedFetch(token, `/calendar/status`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a conexão da agenda.");
  }
  const d = (await res.json()) as {
    connected?: boolean;
    calendarId?: string | null;
    googleAccountEmail?: string | null;
    connectionVersion?: string | null;
  };
  return {
    connected: Boolean(d.connected),
    calendarId: d.calendarId ?? null,
    googleAccountEmail: d.googleAccountEmail ?? null,
    connectionVersion:
      typeof d.connectionVersion === "string" && d.connectionVersion.length > 0
        ? d.connectionVersion
        : null,
  };
}

export interface ConnectStart {
  authUrl: string;
  flowSecret: string;
  /**
   * Instante de expiração do fluxo em epoch ms, derivado do `expires_at` que o
   * SERVIDOR gravou. O cliente nunca calcula TTL — só descarta o segredo quando
   * este instante passa. O servidor revalida `expires_at` no `finish` e segue
   * sendo a autoridade final.
   */
  expiresAt: number;
}

/**
 * Inicia o fluxo OAuth (OAUTH-CALENDAR-V1). Devolve a URL de consentimento, o
 * `flowSecret` e a expiração real do fluxo.
 *
 * `expectedGoogleEmail` é a conta que o admin DECLARA que vai conectar. Vai no
 * corpo (POST), nunca em query string, e é contra ela que o backend compara o
 * e-mail verificado no userinfo antes de persistir qualquer token.
 *
 * FAIL-CLOSED: um backend antigo responde só `{authUrl}` (ou sem `expiresAt`).
 * Sem segredo não existe quem conclua o fluxo, e sem prazo o painel guardaria um
 * segredo sem validade. Nos dois casos NÃO redirecionamos ao Google — o usuário
 * consentiria à toa e a conexão nunca completaria.
 */
export async function fetchConnectUrl(
  token: string,
  expectedGoogleEmail: string,
): Promise<ConnectStart> {
  const res = await authedFetch(token, `/calendar/connect`, {
    method: "POST",
    body: JSON.stringify({ expectedGoogleEmail }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível iniciar a conexão com o Google.");
  }
  const d = (await res.json()) as {
    authUrl?: string;
    flowSecret?: string;
    expiresAt?: string;
  };
  if (!d.authUrl) throw new ApiError(502, "O Google não retornou a URL de consentimento.");
  const expiresAt = Date.parse(d.expiresAt ?? "");
  if (!d.flowSecret || !Number.isFinite(expiresAt)) {
    throw new ApiError(
      409,
      "Conexão indisponível no momento. Atualize a página e tente novamente.",
    );
  }
  return { authUrl: d.authUrl, flowSecret: d.flowSecret, expiresAt };
}

export interface FinishResult {
  /** `conectado` (200), ou callback/finish ainda pendente (202). */
  status: "conectado" | "aguardando_callback" | "processando";
  connected: boolean;
  calendarId: string | null;
  /** E-mail verificado da conta conectada; `null` enquanto não há conexão. */
  googleAccountEmail: string | null;
  /** Revisão opaca da conexão criada/confirmada pelo finish. */
  connectionVersion: string | null;
}

/**
 * Conclui o fluxo: consome o flow, troca o code com o `code_verifier` guardado
 * no servidor e persiste a conexão. Só quem tem o `flowSecret` conclui.
 *
 * O segredo é OBRIGATÓRIO e a guarda abaixo é fail-closed: sem ele não sai
 * requisição nenhuma. Não existe caminho por identidade — identidade prova
 * apenas QUEM finaliza, nunca QUAL conta Google consentiu, e um `state` vazado
 * viraria vinculação silenciosa de conta.
 *
 * 202 = callback ainda não estacionou o code OU outro finish do mesmo fluxo
 * ainda está processando. É recuperável e não deve virar polling.
 */
export async function finishConnection(
  token: string,
  flowSecret: string,
): Promise<FinishResult> {
  if (!flowSecret) {
    throw new ApiError(409, "Não foi possível concluir a conexão com o Google.");
  }
  const res = await authedFetch(token, `/calendar/connect/finish`, {
    method: "POST",
    body: JSON.stringify({ flowSecret }),
  });
  if (!res.ok) {
    // O corpo é lido UMA vez. `readDetail` não serve aqui: ele reduz o detail a
    // string/message e jogaria fora `expected`/`verified` da conta divergente.
    let detail: unknown = null;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      /* corpo não-JSON */
    }
    if (
      isRecord(detail) &&
      detail.code === "conta_divergente" &&
      typeof detail.expected === "string" &&
      typeof detail.verified === "string"
    ) {
      throw new GoogleAccountMismatchError(detail.expected, detail.verified);
    }
    if (
      isRecord(detail) &&
      detail.code === "conta_reidentificada" &&
      typeof detail.message === "string"
    ) {
      throw new GoogleAccountReidentifiedError(detail.message);
    }
    const message =
      typeof detail === "string"
        ? detail
        : isRecord(detail) && typeof detail.message === "string"
          ? detail.message
          : null;
    throw new ApiError(
      res.status,
      message ?? "Não foi possível concluir a conexão com o Google.",
    );
  }
  const d = (await res.json()) as {
    status?: string;
    connected?: boolean;
    calendarId?: string | null;
    googleAccountEmail?: string | null;
    connectionVersion?: string | null;
  };
  return {
    status:
      d.status === "conectado"
        ? "conectado"
        : d.status === "processando"
          ? "processando"
          : "aguardando_callback",
    connected: Boolean(d.connected),
    calendarId: d.calendarId ?? null,
    googleAccountEmail: d.googleAccountEmail ?? null,
    connectionVersion:
      typeof d.connectionVersion === "string" && d.connectionVersion.length > 0
        ? d.connectionVersion
        : null,
  };
}

export async function fetchCalendarList(token: string): Promise<CalendarOption[]> {
  const res = await authedFetch(token, `/calendar/list`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível listar as agendas.");
  }
  const d = (await res.json()) as { calendars?: CalendarOption[] };
  return d.calendars ?? [];
}

export async function selectCalendar(
  token: string,
  calendarId: string,
  connectionVersion: string,
): Promise<CalendarStatus> {
  const res = await authedFetch(token, `/calendar`, {
    method: "PUT",
    body: JSON.stringify({ calendarId, connectionVersion }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível selecionar a agenda.");
  }
  const d = (await res.json()) as {
    connected?: boolean;
    calendarId?: string | null;
    googleAccountEmail?: string | null;
    connectionVersion?: string | null;
  };
  return {
    connected: Boolean(d.connected),
    calendarId: d.calendarId ?? null,
    googleAccountEmail: d.googleAccountEmail ?? null,
    connectionVersion:
      typeof d.connectionVersion === "string" && d.connectionVersion.length > 0
        ? d.connectionVersion
        : null,
  };
}

export async function disconnectCalendar(token: string): Promise<void> {
  const res = await authedFetch(token, `/calendar`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível desconectar a agenda.");
  }
}

// EVT-6 PR6.4 -------------------------------------------------------------
export interface ImportResult {
  created: number;
  skipped: number;
}

/**
 * Importa os eventos do Google da igreja (POST /calendar/import). O backend lê a
 * janela padrão (now→+90d), persiste como `a_confirmar`/`origem='google'` e
 * deduplica — nada é enviado. Os eventos aparecem na aba "A confirmar" da agenda.
 * 409 quando a agenda não está conectada.
 */
export async function importEvents(token: string): Promise<ImportResult> {
  const res = await authedFetch(token, `/calendar/import`, { method: "POST" });
  if (res.status === 409) {
    throw new ApiError(409, "Conecte a agenda do Google antes de importar.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível importar os eventos.");
  }
  const d = (await res.json()) as { created?: number; skipped?: number };
  return { created: d.created ?? 0, skipped: d.skipped ?? 0 };
}

// EVT-7 PR2 — destinatários de alerta da Agenda -----------------------------
/**
 * Destinatário de avisos internos da Agenda por WhatsApp (admin-only).
 * Contrato (app/routers/calendar.py, /calendar/recipients):
 *   GET    /calendar/recipients        -> { recipients: AlertRecipient[] }
 *   POST   /calendar/recipients        -> AlertRecipient   (409 se telefone dup ativo)
 *   PUT    /calendar/recipients/{id}   -> AlertRecipient   (parcial; 409 dup)
 *   DELETE /calendar/recipients/{id}   -> 204
 * Estes endpoints só CONFIGURAM — nada é enviado aqui.
 */
export interface AlertRecipient {
  id: string;
  nome: string;
  telefone: string;
  ativo: boolean;
}

export async function fetchAlertRecipients(token: string): Promise<AlertRecipient[]> {
  const res = await authedFetch(token, `/calendar/recipients`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os destinatários.");
  }
  const d = (await res.json()) as { recipients?: AlertRecipient[] };
  return d.recipients ?? [];
}

export async function createAlertRecipient(
  token: string,
  nome: string,
  telefone: string,
): Promise<AlertRecipient> {
  const res = await authedFetch(token, `/calendar/recipients`, {
    method: "POST",
    body: JSON.stringify({ nome, telefone }),
  });
  if (res.status === 409) {
    throw new ApiError(409, "Já existe um destinatário ativo com esse telefone.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível adicionar o destinatário.");
  }
  return (await res.json()) as AlertRecipient;
}

export async function updateAlertRecipient(
  token: string,
  id: string,
  patch: { nome?: string; telefone?: string; ativo?: boolean },
): Promise<AlertRecipient> {
  const res = await authedFetch(token, `/calendar/recipients/${id}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
  if (res.status === 409) {
    throw new ApiError(409, "Já existe um destinatário ativo com esse telefone.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível atualizar o destinatário.");
  }
  return (await res.json()) as AlertRecipient;
}

export async function deleteAlertRecipient(token: string, id: string): Promise<void> {
  const res = await authedFetch(token, `/calendar/recipients/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover o destinatário.");
  }
}

export { ApiError, SessionExpiredError };
