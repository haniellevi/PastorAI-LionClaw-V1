// @vitest-environment jsdom
import { act, createElement as h } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const auth = vi.hoisted(() => ({ token: 'synthetic', status: 'authenticated', user: { roles: ['admin'], appUserId: 'admin', churchId: 'church' }, expireSession: vi.fn() }));
const api = vi.hoisted(() => ({ fetchConversations: vi.fn(), fetchInboxAgentStatus: vi.fn(), fetchMessageWindow: vi.fn(), fetchMessageMediaUrls: vi.fn(), fetchConversationPhoto: vi.fn() }));
const request = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-context', () => ({ useAuth: () => auth }));
vi.mock('@/lib/conversations-api', async original => ({ ...await original<typeof import('@/lib/conversations-api')>(), ...api }));
vi.mock('@/lib/dashboard-api', async original => ({ ...await original<typeof import('@/lib/dashboard-api')>(), authedFetch: request }));
vi.mock('./ContactPanel', () => ({ ContactPanel: ({ onResetPrivateContent }: { onResetPrivateContent: () => void }) => h('button', { onClick: onResetPrivateContent }, 'Reset sintético') }));
import { InboxScreen } from './InboxScreen';
let root: Root, el: HTMLDivElement;
const conversation = { id: 'conv', nome: 'Contato sintético', telefone: '5500000000000', pessoaId: 'person', estado: 'ia', ultimaMensagem: 'Prévia sintética', naoLidas: 0, assumidoPor: null, assumidoPorNome: null, assumidoEm: null, esperaDesde: null, atualizadoEm: null, tipo: null, semInteresse: false };
function button(text: string) { return [...el.querySelectorAll('button')].find(b => b.textContent?.includes(text))!; }
async function click(text: string) { await act(async () => button(text).click()); }
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; vi.clearAllMocks();
  api.fetchConversations.mockResolvedValue({ items: [conversation, { ...conversation, id: 'conv-2' }, { ...conversation, id: 'other', pessoaId: 'other-person', nome: 'Outro contato' }], total: 3, page: 1, pageSize: 100 });
  api.fetchInboxAgentStatus.mockResolvedValue({ configured: true, ativo: false });
  api.fetchMessageWindow.mockImplementation(async (_token: string, id: string) => ({ items: [{ id: `msg-${id}`, direcao: 'in', autor: 'contato', texto: id === 'other' ? 'Conteúdo sintético preservado' : 'Conteúdo sintético removível', tipo: 'texto' }], cursorSupported: false }));
  api.fetchMessageMediaUrls.mockResolvedValue({}); api.fetchConversationPhoto.mockResolvedValue(null);
  request.mockResolvedValue(Response.json({ status: 'disconnected' }));
  vi.stubGlobal('matchMedia', (media: string) => ({ matches: false, media, addEventListener() {}, removeEventListener() {} }));
  el = document.createElement('div'); document.body.append(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); vi.unstubAllGlobals(); });
it('remove todas as conversas da pessoa, mantém outra pessoa e preserva o recibo após desmontar o painel', async () => {
  await act(async () => root.render(h(InboxScreen)));
  await act(async () => el.querySelector<HTMLButtonElement>('button.conv')!.click());
  expect(el.textContent).toContain('Conteúdo sintético removível');
  await act(async () => el.querySelector<HTMLButtonElement>('[aria-label="Ver pessoa"]')!.click());
  await click('Reset sintético');
  const input = el.querySelector<HTMLInputElement>('[role="dialog"] input')!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'EXCLUIR CONTEUDO PRIVADO'); input.dispatchEvent(new Event('input', { bubbles: true })); });
  request.mockResolvedValue(Response.json({ id: 'receipt', estado: 'pendente_envio', camadas: {} }));
  await click('Confirmar exclusão');
  expect(el.textContent).not.toContain('Conteúdo sintético removível');
  expect(el.querySelectorAll('button.conv')).toHaveLength(1);
  expect(el.textContent).toContain('Outro contato');
  expect(el.querySelector('[role="dialog"]')?.textContent).toContain('Recibo: receipt');
  expect(el.querySelector('[role="dialog"]')?.textContent).toContain('Envio em andamento');
});
