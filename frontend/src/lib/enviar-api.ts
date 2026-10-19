import { ApiError, authedFetch, readDetail } from './dashboard-api';

export interface Avaliacao {
  id: string;
  decisao: 'apto' | 'nao_apto';
  origem: 'avaliacao' | 'legado' | 'csim';
  motivo: string;
  autor_id: string;
  criada_em: string;
  versao_regras: string;
  evidencias: Record<string, { estado: string; referencia: string | null }>;
}
export interface AvaliacaoPessoa {
  pessoa_id: string;
  nome: string;
  apto_lider: boolean;
  revisao_pastoral_pendente?: boolean;
  origem: string | null;
  pendencias: {
    situacao: string;
    status_regras: string;
    aviso_legado: string | null;
    motivo: string | null;
    pendencias: { criterio: string; descricao: string }[];
  };
  avaliacoes: Avaliacao[];
}
export interface DecisaoInput {
  id: string;
  decisao: 'apto' | 'nao_apto';
  origem: 'avaliacao' | 'legado';
  motivo: string;
}
export async function getAvaliacao(token: string, pessoaId: string): Promise<AvaliacaoPessoa> {
  const res = await authedFetch(token, `/enviar/pessoas/${encodeURIComponent(pessoaId)}/avaliacoes`);
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) ?? 'Não foi possível carregar a avaliação.');
  return res.json();
}
export async function postAvaliacao(token: string, pessoaId: string, input: DecisaoInput): Promise<Avaliacao> {
  const res = await authedFetch(token, `/enviar/pessoas/${encodeURIComponent(pessoaId)}/avaliacoes`, { method: 'POST', body: JSON.stringify(input) });
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) ?? 'Não foi possível registrar a avaliação.');
  return res.json();
}

export interface EnviarPessoa {
  id: string;
  nome: string;
  situacao: 'apto_para_avaliacao' | 'pendente' | 'bloqueado';
  origem: string | null;
  apto_lider: boolean;
  pendencias: { criterio: string; estado: string; descricao: string }[];
  ultima_avaliacao: Pick<Avaliacao, 'id' | 'decisao' | 'criada_em' | 'versao_regras'> | null;
}
export interface EnviarHistorico {
  id: string;
  tipo: 'nomear_lider' | 'abrir_celula' | 'multiplicacao';
  status: string;
  criada_em: string;
  decidido_em: string | null;
  celula_id: string | null;
}
export interface EnviarPage<T> { items: T[]; total: number; page: number; page_size: number }
export interface EnviarQuery { q: string; page: number; grupo?: 'todos' | 'aptos' | 'pendentes' }
async function getEnviarPage<T>(token: string, path: string, query: EnviarQuery): Promise<EnviarPage<T>> {
  const params = new URLSearchParams({ q: query.q, page: String(query.page), page_size: '25' });
  if (query.grupo) params.set('grupo', query.grupo);
  const res = await authedFetch(token, `/enviar/${path}?${params}`);
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) ?? 'Não foi possível consultar Enviar.');
  return res.json();
}
export const getEnviarPessoas = (token: string, query: EnviarQuery) => getEnviarPage<EnviarPessoa>(token, 'pessoas', query);
export const getEnviarHistorico = (token: string, query: EnviarQuery) => getEnviarPage<EnviarHistorico>(token, 'historico', query);
