import { ApiError, authedFetch, readDetail } from './dashboard-api';
export interface Versao {
  id: string; numero: number; estado: string; publicos: string[];
  criada_em: string; publicada_em: string | null; revisada_em: string | null;
  vigente: boolean; pode_ler: boolean; acoes: string[];
}
export interface Documento { id: string; titulo: string; assunto: string; vigente_id: string | null; versoes: Versao[] }
export interface Painel { pode_criar: boolean; responsavel_id: string | null; documentos: Documento[] }
export interface Leitura { titulo: string; assunto: string; conteudo: string; origem: string; publicos: string[]; estado: string }
export interface Trecho { titulo: string; versao_id: string; secao: string; trecho: string; ordem: number }
export interface Recibo { documento_id: string; versao_id: string; acao: string }
export async function conhecimento<T>(token: string, path: string, payload?: object, signal?: AbortSignal): Promise<T> {
  const res = await authedFetch(token, `/conhecimento/${path}`, {
    cache: 'no-store', method: payload ? 'POST' : 'GET', body: payload ? JSON.stringify(payload) : undefined, signal,
  });
  if (!res.ok) throw new ApiError(res.status, await readDetail(res) ?? 'Não foi possível concluir. Atualize e tente novamente.');
  return res.json();
}
export const PUBLICOS: Record<string, string> = {
  institucional_publico: 'Público institucional (inclui visitantes)', membros: 'Pessoas com vínculo ativo de membro',
  'papel:admin': 'Administradores', 'papel:pastor': 'Pastores', 'papel:lider_g12': 'Líderes G12',
  'papel:lider_consol': 'Líderes de consolidação', 'papel:lider_celula': 'Líderes de célula',
  'papel:lider_mult': 'Líderes de multiplicação', 'papel:operador': 'Operadores', 'papel:membro': 'Papel de membro',
};
export const ESTADOS: Record<string, string> = { rascunho: 'Rascunho', em_revisao: 'Em revisão', publicada: 'Publicada', substituida: 'Substituída', revogada: 'Revogada' };
export const publicoTexto = (values: string[]) => values.map(v => PUBLICOS[v] ?? 'Público não reconhecido').join('; ') || 'Não definido — publicação bloqueada';
