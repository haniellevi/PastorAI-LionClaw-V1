/**
 * Cliente da API de equipe e papéis acumulados (tela #equipe).
 * Consome o backend (sprint-009):
 *
 *   GET  /team                     -> Page<TeamMember>   (api-team, em dashboard-api)
 *   POST /team/invite              -> { usuarioId, status, emailEnviado }  (api-team-invite)
 *   PUT  /team/{usuarioId}/roles   -> { usuarioId, papeis }                (api-team-roles)
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - e-mail duplicado no tenant é rejeitado (409);
 *  - remover/rebaixar o último admin é bloqueado (409) — a igreja nunca fica
 *    sem administrador (F3);
 *  - o convite NÃO escolhe papéis: o convidado entra como `membro` vinculado a
 *    uma célula; o e-mail de ativação é disparado via Brevo (best-effort). Papéis
 *    são a UNIÃO de user_roles, editados depois só para pessoas já cadastradas.
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

/** Conflito 409 dedicado (e-mail duplicado / último admin). */
export class TeamConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TeamConflictError";
  }
}

export async function inviteMember(
  token: string,
  payload: { pessoaId: string; email: string; celulaId?: string },
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

/** Reenvia o e-mail de ativação para um membro convidado (best-effort). */
export async function resendInvite(
  token: string,
  usuarioId: string,
): Promise<InviteResult> {
  const res = await authedFetch(token, `/team/${usuarioId}/resend`, {
    method: "POST",
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível reenviar o convite.");
  }
  return (await res.json()) as InviteResult;
}

/** Revoga o acesso de um membro (remove o app_user; 409 no último admin). */
export async function deleteMember(token: string, usuarioId: string): Promise<void> {
  const res = await authedFetch(token, `/team/${usuarioId}`, { method: "DELETE" });
  if (res.status === 409) {
    const detail = await readDetail(res);
    throw new TeamConflictError(
      detail ?? "Não é possível remover o último administrador.",
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover o acesso.");
  }
}
