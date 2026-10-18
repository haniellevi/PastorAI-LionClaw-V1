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
