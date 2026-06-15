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
