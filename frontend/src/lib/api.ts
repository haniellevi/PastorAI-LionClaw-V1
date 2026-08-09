/**
 * Cliente da API FastAPI (sprint-002): api-login e /auth/me.
 * Contratos (SPEC 3.2):
 *   POST /auth/login -> { token, ...perfil }
 *   GET  /auth/me    -> { appUserId, churchId, email, nome, roles[] }
 *
 * Tratamento de erro segue US-01/US-02/US-35:
 *   - credencial inválida: erro genérico (não revela existência de e-mail);
 *   - igreja suspensa/inadimplente: bloqueio com aviso de billing;
 *   - conta sem igreja vinculada: mensagem de bloqueio dedicada;
 *   - falha de rede/Clerk indisponível: erro genérico com retry.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export interface MeResult {
  appUserId: string;
  churchId: string;
  email: string;
  nome: string;
  chatNome: string | null;
  roles: string[];
  /** Dono (admin principal) da igreja — só o dono gerencia a Assinatura (#4). */
  isOwner?: boolean;
  /** Nome da igreja (Missão 4 branding) — fallback textual quando não há logo. */
  igrejaNome?: string | null;
  /** URL pública da logo customizada da igreja (Missão 4); null = sem logo. */
  igrejaLogoUrl?: string | null;
}

export interface LoginResult extends MeResult {
  token: string;
}

export type LoginErrorKind =
  | "invalid" // credencial inválida (genérico)
  | "billing_blocked" // igreja suspensa/inadimplente
  | "no_church" // conta sem igreja vinculada
  | "rate_limited" // excesso de tentativas de autenticação
  | "network"; // Clerk/back indisponível ou timeout

export class LoginError extends Error {
  readonly kind: LoginErrorKind;
  constructor(kind: LoginErrorKind, message: string) {
    super(message);
    this.name = "LoginError";
    this.kind = kind;
  }
}

/** Sessão expirada / token inválido em uso -> redirecionar para #login. */
export class SessionExpiredError extends Error {
  constructor() {
    super("Sessão expirada");
    this.name = "SessionExpiredError";
  }
}

/** Sessão válida, mas o acesso foi revogado/bloqueado definitivamente. */
export class SessionAccessDeniedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SessionAccessDeniedError";
  }
}

/** A API não confirmou nem invalidou a sessão; o token deve ser preservado. */
export class AuthUnavailableError extends Error {
  constructor() {
    super("Serviço de autenticação temporariamente indisponível");
    this.name = "AuthUnavailableError";
  }
}

const INVALID_CREDENTIALS =
  "Não foi possível autenticar. Verifique suas credenciais e tente novamente.";
const SERVICE_UNAVAILABLE =
  "O serviço de autenticação está temporariamente indisponível. Tente novamente em instantes.";
const TOO_MANY_ATTEMPTS =
  "Muitas tentativas de acesso. Aguarde um momento e tente novamente.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseMeResult(value: unknown): MeResult | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.appUserId !== "string" ||
    !value.appUserId ||
    typeof value.churchId !== "string" ||
    !value.churchId ||
    typeof value.email !== "string" ||
    !value.email ||
    typeof value.nome !== "string" ||
    !value.nome ||
    !Array.isArray(value.roles) ||
    !value.roles.every((role) => typeof role === "string")
  ) {
    return null;
  }
  if (value.chatNome != null && typeof value.chatNome !== "string") return null;
  if (value.isOwner != null && typeof value.isOwner !== "boolean") return null;
  if (value.igrejaNome != null && typeof value.igrejaNome !== "string") return null;
  if (value.igrejaLogoUrl != null && typeof value.igrejaLogoUrl !== "string") return null;
  return {
    appUserId: value.appUserId,
    churchId: value.churchId,
    email: value.email,
    nome: value.nome,
    chatNome: value.chatNome ?? null,
    roles: value.roles,
    isOwner: typeof value.isOwner === "boolean" ? value.isOwner : undefined,
    igrejaNome: value.igrejaNome ?? null,
    igrejaLogoUrl: value.igrejaLogoUrl ?? null,
  };
}

// Cobre Clerk (até ~10s) + rate limit + banco frio sem afetar deadlines do Inbox.
const AUTH_REQUEST_TIMEOUT_MS = 20_000;

async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

export async function login(email: string, password: string): Promise<LoginResult> {
  let res: Response;
  try {
    res = await authFetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new LoginError("network", SERVICE_UNAVAILABLE);
  }

  if (res.ok) {
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      throw new LoginError("network", SERVICE_UNAVAILABLE);
    }
    if (!isRecord(data) || typeof data.token !== "string" || !data.token) {
      throw new LoginError("network", SERVICE_UNAVAILABLE);
    }
    const profile = parseMeResult(data);
    if (profile) return { token: data.token, ...profile };

    // Compatibilidade durante deploy gradual: o backend antigo devolve apenas
    // {token, churchId}. O token só chega ao contexto depois que /auth/me
    // confirma e valida o perfil completo.
    if (typeof data.churchId !== "string" || !data.churchId) {
      throw new LoginError("network", SERVICE_UNAVAILABLE);
    }
    const legacyProfile = await fetchMe(data.token);
    if (legacyProfile.churchId !== data.churchId) {
      throw new LoginError("network", SERVICE_UNAVAILABLE);
    }
    return { token: data.token, ...legacyProfile };
  }

  if (res.status === 403) {
    // Bloqueio de billing / igreja suspensa (detalhe estruturado do backend).
    let message =
      "Acesso bloqueado por pendência de assinatura. Contate o administrador da igreja.";
    let kind: LoginErrorKind = "billing_blocked";
    try {
      const body = (await res.json()) as { detail?: unknown };
      const detail = body.detail;
      if (isRecord(detail)) {
        if (typeof detail.message === "string") message = detail.message;
        if (detail.error === "no_church") kind = "no_church";
      }
    } catch {
      /* mantém defaults */
    }
    throw new LoginError(kind, message);
  }

  if (res.status === 429) {
    const retryAfter = Number.parseInt(res.headers.get("Retry-After") ?? "", 10);
    const message =
      Number.isFinite(retryAfter) && retryAfter > 0 && retryAfter <= 3600
        ? `Muitas tentativas de acesso. Aguarde ${retryAfter} segundos e tente novamente.`
        : TOO_MANY_ATTEMPTS;
    throw new LoginError("rate_limited", message);
  }

  if (res.status >= 500) {
    throw new LoginError("network", SERVICE_UNAVAILABLE);
  }

  // 401, 422 e demais recusas do cliente: resposta genérica para não revelar
  // se o e-mail existe nem detalhes internos da validação.
  throw new LoginError("invalid", INVALID_CREDENTIALS);
}

export async function fetchMe(token: string): Promise<MeResult> {
  let res: Response;
  try {
    res = await authFetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new AuthUnavailableError();
  }
  if (res.status === 401) {
    throw new SessionExpiredError();
  }
  if (res.status === 403 || (res.status >= 400 && res.status < 500 && res.status !== 429)) {
    let message = "Seu acesso não está disponível. Contate o administrador.";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      if (isRecord(body.detail) && typeof body.detail.message === "string") {
        message = body.detail.message;
      }
    } catch {
      /* mantém mensagem segura */
    }
    throw new SessionAccessDeniedError(message);
  }
  if (!res.ok) {
    throw new AuthUnavailableError();
  }
  try {
    const profile = parseMeResult(await res.json());
    if (!profile) throw new AuthUnavailableError();
    return profile;
  } catch {
    throw new AuthUnavailableError();
  }
}

/**
 * Pede o envio do link de redefinição de senha (fluxo "esqueci a senha").
 * Best-effort: a resposta é sempre tratada como "enviado" — o backend nunca
 * revela se o e-mail existe (US-01), e falha de rede é silenciada de propósito.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
  } catch {
    /* silencioso */
  }
}

/** Define a nova senha a partir do token do link de redefinição. */
export async function resetPassword(token: string, password: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password }),
    });
  } catch {
    throw new LoginError("network", "Falha de conexão. Tente novamente.");
  }
  if (!res.ok) {
    let message = "Link inválido ou expirado. Peça um novo.";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* mantém default */
    }
    throw new LoginError("invalid", message);
  }
}

export interface InviteInfo {
  nome: string;
  email: string;
  igreja: string;
  /** Parte B: o convidado completa o cadastro (telefone) na ativação. */
  precisaCadastro: boolean;
}

async function detailMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* mantém o fallback */
  }
  return fallback;
}

/** Valida o token do convite e retorna os dados para a tela de ativação. */
export async function fetchInvite(token: string): Promise<InviteInfo> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/invite/${encodeURIComponent(token)}`);
  } catch {
    throw new LoginError("network", "Falha de conexão. Tente novamente.");
  }
  if (res.ok) return (await res.json()) as InviteInfo;
  throw new LoginError(
    "invalid",
    await detailMessage(res, "Convite inválido ou expirado. Peça um novo."),
  );
}

/**
 * Ativa o convite definindo a senha (cria o acesso e vincula ao Clerk). Na
 * Parte B (precisaCadastro), o telefone é obrigatório: a ativação completa o
 * cadastro e cria a Pessoa-membro na célula.
 */
export async function activateInvite(
  token: string,
  password: string,
  telefone?: string,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/activate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password, telefone: telefone ?? null }),
    });
  } catch {
    throw new LoginError("network", "Falha de conexão. Tente novamente.");
  }
  if (res.ok) return;
  throw new LoginError(
    "invalid",
    await detailMessage(res, "Não foi possível ativar o acesso. Tente novamente."),
  );
}

/**
 * Atualiza o próprio perfil — nome da conta e/ou nome de exibição no chat.
 * Semântica PATCH: só os campos enviados mudam. `chatNome: ""` limpa a
 * assinatura (volta a usar o nome da conta). Retorna o /me atualizado.
 */
export async function updateMe(
  token: string,
  fields: { nome?: string; chatNome?: string },
): Promise<MeResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/me`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(fields),
    });
  } catch {
    throw new LoginError("network", "Falha de conexão. Tente novamente.");
  }
  if (res.status === 401) throw new SessionExpiredError();
  if (res.ok) return (await res.json()) as MeResult;
  throw new LoginError("invalid", await detailMessage(res, "Não foi possível salvar o perfil."));
}

/** Troca a própria senha (exige a senha atual). */
export async function changePassword(
  token: string,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/change-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ currentPassword, newPassword }),
    });
  } catch {
    throw new LoginError("network", "Falha de conexão. Tente novamente.");
  }
  if (res.status === 401) throw new SessionExpiredError();
  if (res.ok) return;
  throw new LoginError("invalid", await detailMessage(res, "Não foi possível alterar a senha."));
}
