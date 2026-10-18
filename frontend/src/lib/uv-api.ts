import { ApiError, authedFetch, readDetail } from "./dashboard-api";

export interface Turma { id: string; nome: string; encerrada: boolean }
export interface Atividade { ordem: number; tipo: "aula" | "encontro"; aula: number | null; data: string }
export interface Presenca { aula: number; presente: boolean; modalidade: "regular" | "reposicao"; registro_id: string; registrada_por: string; registrada_em: string }
export interface PresencaRevisao extends Omit<Presenca, "aula"> { anterior_id: string | null; registrada_por_nome: string }
export interface MarcoUV { id: string; turma_id: string; turma_nome: string; tipo: "encontro" | "batismo"; data: string; anterior_turma: boolean; validada_por: string; validada_em: string }
export interface ConclusaoUV { id: string; confirmada_por: string; confirmada_em: string; etapa_anterior: string | null; etapa_resultante: string; origem_aptidao: "legado" | "conclusao_uv" }
export interface MatriculaUV { id: string; pessoa_id: string; nome: string; conexao_celula_pendente: boolean; aulas_cumpridas: number[]; aulas_pendentes: number[]; presencas: Presenca[]; marcos: MarcoUV[]; conclusao: ConclusaoUV | null }
export interface TurmaDetalhe extends Turma {
  atividades: Atividade[];
  responsaveis: { usuario_id: string; nome: string | null; elegivel: boolean }[];
  matriculas: MatriculaUV[];
}
export interface UVOpcoes { pessoas: { id: string; nome: string }[]; usuarios: { id: string; nome: string }[] }

export async function uvRequest<T>(token: string, path = "", method = "GET", payload?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await authedFetch(token, `/uv/turmas${path}`, {
    method, cache: "no-store", signal,
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
  if (!response.ok) throw new ApiError(response.status, (await readDetail(response)) ?? "Não foi possível atualizar a UV.");
  return response.json() as Promise<T>;
}
