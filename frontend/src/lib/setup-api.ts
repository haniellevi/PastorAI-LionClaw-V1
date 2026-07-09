/**
 * Cliente da API do checklist de configuração inicial (tela #setup).
 * Consome o backend (Missão 7B-7):
 *
 *   GET /setup/checklist -> { items: [{ id, screen, done }], pendingCount }
 *
 * Cada item aponta para a tela correspondente (`screen`, alvo de hash route
 * dentro da superfície admin) — rótulo/descrição de cada item ficam no
 * front (copy, não estado).
 */
import { ApiError, authedFetch } from "./dashboard-api";

export type SetupItemId =
  | "identidade"
  | "equipe"
  | "celulas"
  | "whatsapp"
  | "agente"
  | "assinatura";

export interface SetupItem {
  id: SetupItemId;
  screen: string;
  done: boolean;
}

export interface SetupChecklist {
  items: SetupItem[];
  pendingCount: number;
}

export async function fetchSetupChecklist(token: string): Promise<SetupChecklist> {
  const res = await authedFetch(token, "/setup/checklist");
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar o checklist de configuração.");
  }
  return (await res.json()) as SetupChecklist;
}
