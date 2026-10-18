import { ApiError, authedFetch, readDetail } from "./dashboard-api";
export interface AulaCD { id: string; numero: number; nome: string }
export interface ModuloCD { id: string; numero: number; nome: string; nivel_id: string | null; aulas: AulaCD[] }
export interface CurriculoCD { id: string; versao: string; nome: string; niveis: { id: string; numero: number; nome: string }[]; modulos: ModuloCD[] }
export interface TurmaCD { id: string; nome: string; curriculo_id: string; modulo_id: string; encerrada: boolean }
export interface DetalheCD extends TurmaCD { versao: string; modulo: ModuloCD; calendario: { aula_id: string; data: string }[]; responsaveis: { usuario_id: string; nome: string; elegivel: boolean }[] }
export async function cdRequest<T>(token: string, path: string, method = "GET", payload?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await authedFetch(token, `/cd${path}`, { method, cache: "no-store", signal, ...(payload === undefined ? {} : { body: JSON.stringify(payload) }) });
  if (!response.ok) throw new ApiError(response.status, (await readDetail(response)) ?? "Não foi possível atualizar a CD.");
  return response.json() as Promise<T>;
}

export interface MatriculaCD { id: string; pessoa_id: string; nome: string; pessoa_arquivada: boolean; ativa: boolean; origem_aptidao: "legado" | "conclusao_uv"; criada_por: string; criada_em: string; cancelada_por: string | null; cancelada_em: string | null }
