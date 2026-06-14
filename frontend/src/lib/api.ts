/**
 * Cliente da API FastAPI (sprint-002): api-login e /auth/me.
 * Contratos (SPEC 3.2):
 *   POST /auth/login -> { token, churchId }
 *   GET  /auth/me    -> { appUserId, churchId, email, nome, roles[] }
 *
 * Tratamento de erro segue US-01/US-02/US-35:
 *   - credencial inválida: erro genérico (não revela existência de e-mail);
 *   - igreja suspensa/inadimplente: bloqueio com aviso de billing;
 *   - conta sem igreja vinculada: mensagem de bloqueio dedicada;
 *   - falha de rede/Clerk indisponível: erro genérico com retry.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export interface LoginResult {
  token: string;
  churchId: string;
}

export interface MeResult {
  appUserId: string;
  churchId: string;
  email: string;
  nome: string;
  roles: string[];
}

export type LoginErrorKind =
  | "invalid" // credencial inválida (genérico)
  | "billing_blocked" // igreja suspensa/inadimplente
  | "no_church" // conta sem igreja vinculada
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

const GENERIC = "Não foi possível autenticar. Verifique suas credenciais e tente novamente.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export async function login(email: string, password: string): Promise<LoginResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new LoginError("network", GENERIC);
  }

  if (res.ok) {
    const data = (await res.json()) as LoginResult;
    return { token: data.token, churchId: data.churchId };
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

  // 401 e demais: mensagem genérica (não revela se o e-mail existe).
  throw new LoginError("invalid", GENERIC);
}

export async function fetchMe(token: string): Promise<MeResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new SessionExpiredError();
  }
  if (res.status === 401) {
    throw new SessionExpiredError();
  }
  if (!res.ok) {
    throw new SessionExpiredError();
  }
  return (await res.json()) as MeResult;
}
