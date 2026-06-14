/**
 * Cliente da API de gerentes de sistema / operadores (tela #gerentes).
 * Consome o backend (sprint-009):
 *
 *   GET    /system-managers        -> SystemManager[]      (api-system-managers)
 *   POST   /system-managers        -> SystemManager        (201)
 *   DELETE /system-managers/{id}   -> 204
 *
 * São papéis OPERACIONAIS do sistema (admin_sistema / operador), distintos dos
 * cargos ministeriais (user_roles). Telas de Configuração são admin-only
 * (delta-005). E-mail duplicado é rejeitado (409).
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

export type OperationalRole = "admin_sistema" | "operador";

export interface SystemManager {
  id: string;
  nome: string;
  email: string;
  papelOperacional: OperationalRole | null;
}

/** Conflito 409 dedicado (e-mail duplicado). */
export class ManagerConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ManagerConflictError";
  }
}

export const OPERATIONAL_ROLE_LABEL: Record<OperationalRole, string> = {
  admin_sistema: "Administrador",
  operador: "Operador",
};

export async function fetchManagers(token: string): Promise<SystemManager[]> {
  const res = await authedFetch(token, "/system-managers");
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar os gerentes de sistema.");
  }
  return (await res.json()) as SystemManager[];
}

export async function createManager(
  token: string,
  payload: { nome: string; email: string; papelOperacional: OperationalRole },
): Promise<SystemManager> {
  const res = await authedFetch(token, "/system-managers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (res.status === 409) {
    const detail = await readDetail(res);
    throw new ManagerConflictError(detail ?? "Já existe um gerente com este e-mail.");
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível adicionar o gerente.");
  }
  return (await res.json()) as SystemManager;
}

export async function deleteManager(token: string, managerId: string): Promise<void> {
  const res = await authedFetch(token, `/system-managers/${managerId}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover o gerente.");
  }
}
