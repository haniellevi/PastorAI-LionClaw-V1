/**
 * Cliente da API de descendências (#g12 — organograma da Visão G12).
 * Consome o endpoint do backend (sprint-004):
 *
 *   GET /descendencias[?rootId=<id>]  -> TreeNode[]  (api-descendencias)
 *
 * A árvore é montada a partir de pessoas.lider_id: cada nó é uma pessoa e seus
 * children são os liderados diretos. Sem rootId, o backend usa a pessoa
 * vinculada ao usuário (sua linha descendente). Reaproveita o transporte
 * autenticado (authedFetch) e o tratamento de 401 do dashboard-api.
 */

import { ApiError, authedFetch } from "./dashboard-api";

/** Nó do organograma de descendências (TreeNode do backend). */
export interface TreeNode {
  id: string;
  nome: string;
  tipo: string | null;
  children: TreeNode[];
}

export async function fetchDescendencias(
  token: string,
  rootId?: string | null,
): Promise<TreeNode[]> {
  const query = rootId ? `?rootId=${encodeURIComponent(rootId)}` : "";
  const res = await authedFetch(token, `/descendencias${query}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar o organograma.");
  }
  return (await res.json()) as TreeNode[];
}

/** Conta recursivamente os liderados (descendentes) de um nó. */
export function countDescendants(node: TreeNode): number {
  return node.children.reduce(
    (sum, child) => sum + 1 + countDescendants(child),
    0,
  );
}

/** Iniciais para o avatar (até 2 letras das primeiras palavras do nome). */
export function initials(nome: string): string {
  const parts = nome.trim().split(/\s+/).filter(Boolean);
  const first = parts[0];
  if (!first) return "?";
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  const last = parts[parts.length - 1] ?? first;
  return ((first[0] ?? "") + (last[0] ?? "")).toUpperCase();
}
