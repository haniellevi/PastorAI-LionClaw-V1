/**
 * Cliente da API de equipe e papéis acumulados (tela #equipe).
 * Consome o backend (sprint-009):
 *
 *   GET    /team                   -> Page<TeamMember>   (api-team, em dashboard-api)
 *   POST   /team/invite            -> { usuarioId, status, emailEnviado }  (api-team-invite)
 *   PUT    /team/{usuarioId}/roles -> { usuarioId, papeis }                (api-team-roles)
 *   DELETE /team/{usuarioId}       -> { usuarioId, status }                (revogar acesso, RF-04)
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - e-mail duplicado no tenant é rejeitado (409);
 *  - remover/rebaixar OU revogar o último admin ativo é bloqueado (409) — a
 *    igreja nunca fica sem administrador (F3 / RF-04);
 *  - papéis são a UNIÃO de user_roles; o convite cria um app_user `convidado`
 *    e dispara o e-mail de ativação via Resend (best-effort);
 *  - revogar é soft: o usuário fica com status `revogado` (auditoria preservada)
 *    e perde o acesso ao painel imediatamente.
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";
import type { Role } from "./roles";

export interface InviteResult {
  usuarioId: string;
  status: string; // convidado
  emailEnviado: boolean;
}

export interface RolesResult {
  usuarioId: string;
  papeis: string[];
}

export interface RevokeResult {
  usuarioId: string;
  status: string; // revogado
}

/** Conflito 409 dedicado (e-mail duplicado / último admin). */
export class TeamConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TeamConflictError";
  }
}

export async function inviteMember(
  token: string,
  payload: { nome: string; email: string; papeis: Role[] },
): Promise<InviteResult> {
  const res = await authedFetch(token, "/team/invite", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (res.status === 409) {
    const detail = await readDetail(res);
    throw new TeamConflictError(detail ?? "Já existe um usuário com este e-mail.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível enviar o convite.");
  }
  return (await res.json()) as InviteResult;
}

export async function updateRoles(
  token: string,
  usuarioId: string,
  papeis: Role[],
): Promise<RolesResult> {
  const res = await authedFetch(token, `/team/${usuarioId}/roles`, {
    method: "PUT",
    body: JSON.stringify({ papeis }),
  });
  if (res.status === 409) {
    const detail = await readDetail(res);
    throw new TeamConflictError(
      detail ?? "Não é possível remover/rebaixar o último administrador.",
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível atualizar os papéis.");
  }
  return (await res.json()) as RolesResult;
}

export async function revokeAccess(
  token: string,
  usuarioId: string,
): Promise<RevokeResult> {
  const res = await authedFetch(token, `/team/${usuarioId}`, {
    method: "DELETE",
  });
  if (res.status === 409) {
    const detail = await readDetail(res);
    throw new TeamConflictError(
      detail ?? "Não é possível revogar o último administrador.",
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível revogar o acesso.");
  }
  return (await res.json()) as RevokeResult;
}
