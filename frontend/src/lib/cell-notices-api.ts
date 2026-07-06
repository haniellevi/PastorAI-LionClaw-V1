/**
 * Cliente da API de avisos de célula (Minha Célula — Discípulo, Líder e Central).
 * Consome os endpoints do backend (cell_discipulo.py + cell_notices.py):
 *
 *   GET    /cells/me/notices        -> DiscipleNotice[]   (leitura do discípulo)
 *   POST   /cell-notices            -> Notice             (líder/Central publicam)
 *   GET    /cell-notices            -> NoticePage         (paginado)
 *   DELETE /cell-notices/{id}       -> Notice             (inativa)
 *
 * Contrato snake_case, espelhando os schemas do backend (`publicado_em`,
 * `notificado_em`, `celula_id`). Origem `celula` (azul) vs `central`/`igreja`
 * (vermelho) é derivada na UI. Reaproveita o transporte autenticado.
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

/** Aviso na leitura do discípulo (cell_discipulo.NoticeOut). */
export interface DiscipleNotice {
  id: string;
  /** `igreja` | `celula`. */
  origem: string;
  /** `igreja` | `celula`. */
  escopo: string;
  titulo: string;
  conteudo: string;
  /** ISO-8601. */
  publicado_em: string;
}

/** Aviso completo (cell_notices.NoticeOut). */
export interface Notice {
  id: string;
  origem: string;
  escopo: string;
  celula_id: string | null;
  titulo: string;
  conteudo: string;
  ativo: boolean;
  /** ISO-8601 ou null. */
  publicado_em: string | null;
  /** ISO-8601 ou null (intenção de notificação persistida). */
  notificado_em: string | null;
}

/** Página de avisos (NoticePage). */
export interface NoticePage {
  items: Notice[];
  page: number;
  page_size: number;
  total: number;
}

/** Payload de criação (CreateNoticeRequest). */
export interface CreateNoticeInput {
  titulo: string;
  conteudo: string;
  /** `celula` (líder) ou `celula`/`igreja` (Central). */
  escopo?: string | null;
  celula_id?: string | null;
}

/**
 * Avisos que o discípulo pode ler: da igreja (broadcast) + da sua célula ativa.
 * Recente → antigo (o backend já ordena por `publicado_em` desc).
 */
export async function getMyNotices(token: string): Promise<DiscipleNotice[]> {
  const res = await authedFetch(token, `/cells/me/notices`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os avisos.");
  }
  return (await res.json()) as DiscipleNotice[];
}

/** Publica um aviso (líder: escopo `celula`; Central: `celula` ou `igreja`). */
export async function createNotice(
  token: string,
  input: CreateNoticeInput,
): Promise<Notice> {
  const res = await authedFetch(token, `/cell-notices`, {
    method: "POST",
    body: JSON.stringify({
      titulo: input.titulo,
      conteudo: input.conteudo,
      escopo: input.escopo ?? null,
      celula_id: input.celula_id ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível publicar o aviso.");
  }
  return (await res.json()) as Notice;
}

/** Lista paginada de avisos visíveis ao usuário autenticado. */
export async function listNotices(
  token: string,
  page = 1,
  pageSize = 50,
): Promise<NoticePage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await authedFetch(token, `/cell-notices?${query.toString()}`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os avisos.");
  }
  return (await res.json()) as NoticePage;
}

/** Inativa (ativo=false) um aviso do próprio autor compatível. */
export async function deleteNotice(
  token: string,
  noticeId: string,
): Promise<Notice> {
  const res = await authedFetch(token, `/cell-notices/${noticeId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover o aviso.");
  }
  return (await res.json()) as Notice;
}
