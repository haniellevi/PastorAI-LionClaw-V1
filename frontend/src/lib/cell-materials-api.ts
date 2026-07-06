/**
 * Cliente da API de materiais de célula (Minha Célula — Central publica, todos leem).
 * Consome os endpoints do backend (cell_materials.py):
 *
 *   POST   /cell-materials          -> Material       (Central; url obrigatória)
 *   GET    /cell-materials          -> MaterialPage   (paginado; leitura de todos)
 *   DELETE /cell-materials/{id}     -> Material       (Central inativa)
 *
 * Contrato snake_case (`publicado_em`). Líder e discípulo têm somente leitura
 * (E14). Reaproveita o transporte autenticado (authedFetch) do dashboard-api.
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

/** Material de apoio da igreja (MaterialOut). */
export interface Material {
  id: string;
  titulo: string;
  descricao: string | null;
  /** URL do material (http/https). */
  url: string | null;
  tipo: string | null;
  ativo: boolean;
  /** ISO-8601 ou null. */
  publicado_em: string | null;
}

/** Página de materiais (MaterialPage). */
export interface MaterialPage {
  items: Material[];
  page: number;
  page_size: number;
  total: number;
}

/** Payload de criação (CreateMaterialRequest). */
export interface CreateMaterialInput {
  titulo: string;
  /** URL obrigatória iniciando com http:// ou https://. */
  url: string;
  descricao?: string | null;
  tipo?: string | null;
}

/** Publica um material (somente Central). */
export async function createMaterial(
  token: string,
  input: CreateMaterialInput,
): Promise<Material> {
  const res = await authedFetch(token, `/cell-materials`, {
    method: "POST",
    body: JSON.stringify({
      titulo: input.titulo,
      url: input.url,
      descricao: input.descricao ?? null,
      tipo: input.tipo ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível publicar o material.");
  }
  return (await res.json()) as Material;
}

/** Lista os materiais ativos da igreja (leitura de líder e discípulo). */
export async function listMaterials(
  token: string,
  page = 1,
  pageSize = 50,
): Promise<MaterialPage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await authedFetch(token, `/cell-materials?${query.toString()}`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os materiais.");
  }
  return (await res.json()) as MaterialPage;
}

/** Inativa (ativo=false) um material (somente Central). */
export async function deleteMaterial(
  token: string,
  materialId: string,
): Promise<Material> {
  const res = await authedFetch(token, `/cell-materials/${materialId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover o material.");
  }
  return (await res.json()) as Material;
}
