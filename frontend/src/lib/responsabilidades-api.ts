import { ApiError, authedFetch, readDetail } from './dashboard-api';

export const SETORES = {
  atendimento: 'Atendimento', consolidacao: 'Consolidação', central_celulas: 'Central de Células',
  universidade_vida: 'Universidade da Vida', capacitacao_destino: 'Capacitação Destino',
  agenda: 'Agenda', conhecimento_oficial: 'Conhecimento oficial',
} as const;
export type Setor = keyof typeof SETORES;
export interface Responsabilidade {
  id: string; pessoa_id: string; setor: Setor; inicio: string; fim: string | null;
  encerrada_em: string | null;
}
export interface Atribuicao { pessoa_id: string; setor: Setor; inicio: string; fim: string | null }
export const PAGE_SIZE = 25;
async function request<T>(token: string, path: string, options?: RequestInit): Promise<T> {
  const res = await authedFetch(token, `/responsabilidades${path}`, options);
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) ?? 'Não foi possível consultar responsabilidades.');
  return res.json();
}
export function listarResponsabilidades(token: string, query: { setor: Setor | ''; offset: number }, signal?: AbortSignal) {
  // One extra row tells the UI whether there is another page without a total endpoint.
  const params = new URLSearchParams({ limit: String(PAGE_SIZE + 1), offset: String(query.offset) });
  if (query.setor) params.set('setor', query.setor);
  return request<Responsabilidade[]>(token, `?${params}`, { signal });
}
export const atribuirResponsabilidade = (token: string, input: Atribuicao) =>
  request<Responsabilidade>(token, '', { method: 'POST', body: JSON.stringify(input) });
export const encerrarResponsabilidade = (token: string, id: string, fim: string) =>
  request<Responsabilidade>(token, `/${encodeURIComponent(id)}/encerrar`, { method: 'POST', body: JSON.stringify({ fim }) });

export function hojeSaoPaulo(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const get = (type: string) => parts.find(p => p.type === type)!.value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}
export function vigencia(row: Responsabilidade, hoje: string): string {
  if (row.fim && row.fim <= hoje) return 'Encerrada';
  return row.inicio > hoje ? 'Programada' : 'Vigente';
}
