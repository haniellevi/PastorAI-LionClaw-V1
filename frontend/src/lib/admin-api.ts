/**
 * Cliente da API do console Super-Admin (plano de plataforma, rotas `/admin/*`).
 *
 * Sessão e token são SEPARADOS do painel da igreja (ver admin-auth-context):
 * o backend gateia tudo por get_platform_admin (allowlist platform_admins),
 * cross-tenant, fora do RLS por igreja. O login em si reutiliza POST /auth/login
 * (lib/api.ts) — o admin é um app_user normal; o que o eleva é o /admin/me.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export interface AdminMe {
  appUserId: string;
  email: string;
  nome: string;
}

export interface AdminIgreja {
  id: string;
  nome: string;
  status: string;
  plano: string | null;
  membros: number;
  pessoas: number;
  createdAt: string | null;
}

export type AdminAuthErrorKind = "forbidden" | "network";

/** Token recusado pelo gate de plataforma (não é admin) ou falha de rede. */
export class AdminAuthError extends Error {
  readonly kind: AdminAuthErrorKind;
  constructor(kind: AdminAuthErrorKind, message: string) {
    super(message);
    this.name = "AdminAuthError";
    this.kind = kind;
  }
}

/** Sessão expirada / token inválido em uso -> voltar ao login do console. */
export class AdminSessionExpiredError extends Error {
  constructor() {
    super("Sessão expirada");
    this.name = "AdminSessionExpiredError";
  }
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

async function asJson<T>(res: Response): Promise<T> {
  return (await res.json()) as T;
}

/**
 * Login dedicado do console master (POST /admin/login). Isento do gate de
 * billing do tenant: o master entra mesmo que a própria igreja-casa esteja
 * suspensa. Qualquer falha (credencial inválida OU conta sem acesso) volta como
 * AdminAuthError("forbidden") — o backend não distingue os casos.
 */
export async function adminLogin(
  email: string,
  password: string,
): Promise<{ token: string }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/admin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new AdminAuthError("network", "Falha de conexão com o servidor.");
  }
  if (res.status === 401 || res.status === 403) {
    throw new AdminAuthError(
      "forbidden",
      "E-mail/senha inválidos ou conta sem acesso à administração da plataforma.",
    );
  }
  if (!res.ok) throw new AdminAuthError("network", "Não foi possível entrar no console.");
  return asJson<{ token: string }>(res);
}

/** Confirma que o token pertence a um platform admin e devolve sua identidade. */
export async function fetchAdminMe(token: string): Promise<AdminMe> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/admin/me`, { headers: authHeaders(token) });
  } catch {
    throw new AdminAuthError("network", "Falha de conexão com o servidor.");
  }
  if (res.status === 401) throw new AdminSessionExpiredError();
  if (res.status === 403) {
    throw new AdminAuthError(
      "forbidden",
      "Esta conta não tem acesso à administração da plataforma.",
    );
  }
  if (!res.ok) throw new AdminAuthError("network", "Não foi possível validar a sessão.");
  return asJson<AdminMe>(res);
}

/** Lista todas as igrejas (cross-tenant) com contadores de membros/pessoas. */
export async function listIgrejas(token: string): Promise<AdminIgreja[]> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/admin/igrejas`, { headers: authHeaders(token) });
  } catch {
    throw new AdminAuthError("network", "Falha de conexão com o servidor.");
  }
  if (res.status === 401) throw new AdminSessionExpiredError();
  if (res.status === 403) {
    throw new AdminAuthError("forbidden", "Acesso negado.");
  }
  if (!res.ok) throw new AdminAuthError("network", "Não foi possível carregar as igrejas.");
  return asJson<AdminIgreja[]>(res);
}

export interface CreateIgrejaInput {
  nome: string;
  plano: string | null;
  admin: { nome: string; email: string };
}

export interface CreateIgrejaResult {
  igrejaId: string;
  adminUsuarioId: string;
  emailEnviado: boolean;
}

export interface UpdateIgrejaInput {
  status?: string;
  plano?: string;
}

/** Erro de validação/regra de negócio numa ação de escrita do console. */
export class AdminRequestError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "AdminRequestError";
    this.status = status;
  }
}

/** Extrai uma mensagem do corpo de erro do FastAPI (detail string ou lista). */
function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === "string") return first.msg;
    }
  }
  return fallback;
}

async function throwMutationError(res: Response, fallback: string): Promise<never> {
  if (res.status === 401) throw new AdminSessionExpiredError();
  if (res.status === 403) throw new AdminAuthError("forbidden", "Acesso negado.");
  let message = fallback;
  try {
    message = extractDetail(await res.json(), fallback);
  } catch {
    /* mantém o fallback */
  }
  throw new AdminRequestError(res.status, message);
}

function jsonHeaders(token: string): HeadersInit {
  return { ...authHeaders(token), "Content-Type": "application/json" };
}

/** Provisiona uma igreja + admin inicial (convite por e-mail, US-43). */
export async function createIgreja(
  token: string,
  input: CreateIgrejaInput,
): Promise<CreateIgrejaResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/admin/igrejas`, {
      method: "POST",
      headers: jsonHeaders(token),
      body: JSON.stringify(input),
    });
  } catch {
    throw new AdminAuthError("network", "Falha de conexão com o servidor.");
  }
  if (!res.ok) await throwMutationError(res, "Não foi possível provisionar a igreja.");
  return asJson<CreateIgrejaResult>(res);
}

/** Altera status e/ou plano de uma igreja (US-42). */
export async function updateIgreja(
  token: string,
  id: string,
  input: UpdateIgrejaInput,
): Promise<AdminIgreja> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/admin/igrejas/${id}`, {
      method: "PATCH",
      headers: jsonHeaders(token),
      body: JSON.stringify(input),
    });
  } catch {
    throw new AdminAuthError("network", "Falha de conexão com o servidor.");
  }
  if (!res.ok) await throwMutationError(res, "Não foi possível atualizar a igreja.");
  return asJson<AdminIgreja>(res);
}
