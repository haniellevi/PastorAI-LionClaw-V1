// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PainelConhecimento } from './ConhecimentoScreen';
import { ApiError } from '@/lib/dashboard-api';
import type { Painel } from '@/lib/conhecimento-api';
const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('@/lib/conhecimento-api', async original => ({ ...await original<typeof import('@/lib/conhecimento-api')>(), conhecimento: mocks.api }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let dispose = () => {};
const doc = { id: 'internal-document', titulo: 'Orientação sintética', assunto: 'Institucional', vigente_id: 'internal-version', versoes: [{ id: 'internal-version', numero: 2, estado: 'publicada', publicos: ['institucional_publico'], criada_em: '2026-10-19T12:00:00Z', publicada_em: null, revisada_em: null, vigente: true, pode_ler: true, acoes: [] as string[] }] };
const panel = (edit = false): Painel => ({ pode_criar: edit, responsavel_id: edit ? 'internal-user' : null, documentos: [doc] });
beforeEach(() => { mocks.api.mockResolvedValue(panel()); });
afterEach(() => { dispose(); vi.resetAllMocks(); });
async function mount() {
 const el = document.createElement('div'); document.body.append(el); const root = createRoot(el);
 dispose = () => { act(() => root.unmount()); el.remove(); };
 await act(async () => root.render(<PainelConhecimento token="synthetic" onExpired={vi.fn()} />));
 async function click(label: string) {
   const button = [...el.querySelectorAll('button')].find(b => b.textContent === label);
   expect(button, label).toBeDefined(); await act(async () => button!.click());
 }
 async function input(selector: string, value: string) {
   const field = el.querySelector(selector) as HTMLInputElement;
   const proto = field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
   field.focus();
   await act(async () => { Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(field, value); field.dispatchEvent(new Event('input', { bubbles: true })); });
   expect(document.activeElement).toBe(field);
 }
 return { el, click, input };
}
it('leitor usa ações do servidor, texto seguro e nenhum ID visível', async () => {
 const { el, click } = await mount();
 expect(el.textContent).toContain('Versão vigente: versão 2');
 expect(el.textContent).not.toContain('Criar rascunho'); expect(el.textContent).not.toContain('internal-');
 mocks.api.mockResolvedValueOnce({ titulo: doc.titulo, conteudo: '<script>não executar</script>', origem: 'Manual aprovado', estado: 'publicada', publicos: ['institucional_publico'] });
 await click('Ler versão 2');
 expect(el.querySelector('script')).toBeNull(); expect(el.textContent).toContain('<script>não executar</script>');
 expect(document.activeElement?.getAttribute('aria-label')).toBe('Documento selecionado');
});
it('busca mostra trecho e revalida a leitura de resultado revogado', async () => {
 const { el, click, input } = await mount();
 mocks.api.mockResolvedValueOnce([{ titulo: 'Resultado sintético', versao_id: 'result-internal', trecho: 'Trecho autorizado' }]);
 await input('#conhecimento-busca', 'orientação');
 await act(async () => el.querySelector('form')!.requestSubmit());
 expect(mocks.api).toHaveBeenLastCalledWith('synthetic', 'busca?q=orienta%C3%A7%C3%A3o', undefined, expect.any(AbortSignal));
 expect(el.textContent).toContain('Trecho autorizado'); expect(el.textContent).not.toContain('result-internal');
 mocks.api.mockRejectedValueOnce(new ApiError(404, 'Versão não encontrada'));
 await click('Resultado sintético');
 expect(el.querySelector('[role=alert]')?.textContent).toContain('Versão não encontrada'); expect(el.querySelector('.conhecimento-text')).toBeNull();
});
it('cria com responsável do servidor e envia recibo sem reler rascunho', async () => {
 mocks.api.mockResolvedValue(panel(true));
 const { el, click, input } = await mount(); await click('Criar rascunho');
 await input('#conhecimento-titulo', 'Título fictício'); await input('#conhecimento-assunto', 'Assunto');
 await input('#conhecimento-origem', 'Documento aprovado'); await input('#conhecimento-texto', 'Conteúdo fictício');
 mocks.api.mockResolvedValueOnce({ documento_id: 'new-doc', versao_id: 'new-version' }).mockResolvedValueOnce(panel(true));
 await act(async () => el.querySelector<HTMLFormElement>('.conhecimento-detail form')!.requestSubmit());
 const created = mocks.api.mock.calls.find(call => call[1] === 'documentos' && call[2]);
 expect(created?.[2]).toMatchObject({ titulo: 'Título fictício', conteudo: 'Conteúdo fictício', responsavel_id: 'internal-user', publicos: [] });
 expect(mocks.api.mock.calls.some(call => String(call[1]).startsWith('versoes/'))).toBe(false);
 mocks.api.mockResolvedValueOnce({}).mockResolvedValueOnce(panel(true)); await click('Enviar rascunho salvo para revisão');
 expect(mocks.api.mock.calls.some(call => call[1] === 'documentos/new-doc/enviar-revisao' && call[2].versao_id === 'new-version')).toBe(true);
});
it('confirma substituição com público e vigência e repete payload idempotente', async () => {
 const editable = panel(true); editable.documentos = [{ ...doc, versoes: [{ ...doc.versoes[0]!, estado: 'em_revisao', vigente: false, acoes: ['publicar'] }] }];
 mocks.api.mockResolvedValue(editable); const { el, click } = await mount();
 await click('Aprovar e publicar'); expect(el.textContent).toContain('substitui a versão vigente');
 expect(mocks.api.mock.calls.filter(c => c[2])).toHaveLength(0);
 mocks.api.mockRejectedValueOnce(new TypeError('offline')); await click('Confirmar aprovar e publicar');
 const failed = mocks.api.mock.calls.find(call => call[1].endsWith('/publicar'));
 expect(failed?.[2]).toMatchObject({ publicos: ['institucional_publico'], vigente_esperada_id: 'internal-version' });
 mocks.api.mockResolvedValueOnce({}).mockResolvedValueOnce(panel()); await click('Repetir operação');
 const attempts = mocks.api.mock.calls.filter(call => call[1].endsWith('/publicar')); expect(attempts[1]?.[2]).toEqual(attempts[0]?.[2]);
});
it('recusa por papel remove conteúdo e capacidades antigos', async () => {
 const editable = panel(true); editable.documentos = [{ ...doc, versoes: [{ ...doc.versoes[0]!, acoes: ['revogar'] }] }];
 mocks.api.mockResolvedValue(editable); const { el, click } = await mount(); await click('Revogar versão');
 mocks.api.mockRejectedValueOnce(new ApiError(403, 'Sem permissão editorial')).mockResolvedValueOnce({ pode_criar: false, responsavel_id: null, documentos: [] });
 await click('Confirmar revogar versão'); expect(el.textContent).not.toContain('Criar rascunho'); expect(el.textContent).not.toContain('Orientação sintética');
 expect(el.querySelector('[role=alert]')?.textContent).toContain('Sem permissão editorial');
});

it('substitui publicação restrita com texto novo sem consultar conteúdo não autorizado', async () => {
 const editable = panel(true);
 editable.documentos = [{ ...doc, versoes: [{ ...doc.versoes[0]!, pode_ler: false, acoes: ['editar', 'revogar'] }] }];
 mocks.api.mockResolvedValue(editable);
 const { el, click } = await mount();
 await click('Criar nova versão');
 expect(el.textContent).toContain('não tem acesso ao texto vigente');
 expect((el.querySelector('#conhecimento-texto') as HTMLTextAreaElement).value).toBe('');
 expect(mocks.api.mock.calls.some(call => String(call[1]).startsWith('versoes/'))).toBe(false);
});

it('retoma envio depois de recarregar sem revelar o rascunho nem seus IDs', async () => {
 mocks.api.mockResolvedValue({ pode_criar: true, responsavel_id: 'internal-user', documentos: [], pendentes: [{ documento_id: 'pending-doc', versao_id: 'pending-version' }] });
 const { el, click } = await mount();
 expect(el.textContent).toContain('Rascunho pendente 1');
 expect(el.textContent).not.toContain('pending-doc'); expect(el.textContent).not.toContain('pending-version');
 mocks.api.mockResolvedValueOnce({}).mockResolvedValueOnce(panel(true));
 await click('Enviar rascunho salvo para revisão');
 expect(mocks.api.mock.calls.some(call => call[1] === 'documentos/pending-doc/enviar-revisao' && call[2].versao_id === 'pending-version')).toBe(true);
 expect(mocks.api.mock.calls.some(call => String(call[1]).startsWith('versoes/'))).toBe(false);
});
it('carrega outra página e preserva versões já recebidas sem duplicar documentos', async () => {
 mocks.api.mockResolvedValue({ ...panel(), pagina: 1, tem_mais: true });
 const { el, click } = await mount();
 mocks.api.mockResolvedValueOnce({ ...panel(), documentos: [{ ...doc, versoes: [{ ...doc.versoes[0]!, id: 'older-version', numero: 1, estado: 'substituida', vigente: false, pode_ler: false }] }], pagina: 2, tem_mais: false });
 await click('Carregar mais documentos e versões');
 expect(el.querySelectorAll('article')).toHaveLength(1);
 expect(el.textContent).toContain('Versão 1'); expect(el.textContent).toContain('Versão 2');
 expect(el.textContent).not.toContain('Carregar mais documentos e versões');
});

it('exclui documento só com capacidade do servidor e confirmação explícita', async () => {
 const editable = panel(true); editable.documentos = [{ ...doc, pode_excluir: true }];
 mocks.api.mockResolvedValue(editable); const { el, click } = await mount();
 await click('Excluir documento');
 expect(el.textContent).toContain('Todas as versões e trechos serão apagados');
 expect(mocks.api.mock.calls.filter(c => c[2])).toHaveLength(0);
 mocks.api.mockResolvedValueOnce({ estado: 'concluido', versoes: 2, trechos: 3 }).mockResolvedValueOnce({ ...panel(), documentos: [] });
 await click('Confirmar excluir documento');
 expect(mocks.api.mock.calls.find(c => c[1].endsWith('/excluir'))?.[2]).toMatchObject({ confirmacao: 'EXCLUIR DOCUMENTO' });
 expect(el.textContent).not.toContain(doc.titulo);
});
