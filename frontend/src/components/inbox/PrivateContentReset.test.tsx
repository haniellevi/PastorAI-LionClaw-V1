// @vitest-environment jsdom
import { act, createElement as h } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PrivateContentReset } from './PrivateContentReset';
import { SessionExpiredError } from '@/lib/api';
const fetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/dashboard-api', async original => ({ ...await original<typeof import('@/lib/dashboard-api')>(), authedFetch: fetch }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let el: HTMLDivElement, root: Root;
const erased = vi.fn(), close = vi.fn(), expire = vi.fn();
const receipt = { id: 'receipt-1', estado: 'pendente', camadas: { midias: { encontradas: 1, apagadas: 0, pendentes: 1, falhas: 0 } } };
async function flush() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); }
function button(text: string) { return [...el.querySelectorAll('button')].find(b => b.textContent?.includes(text))!; }
async function render(open = true) { await act(async () => root.render(h(PrivateContentReset, { open, token: 'synthetic', personId: 'person-1', personName: 'Contato sintético', onClose: close, onErased: erased, expireSession: expire }))); }
async function confirm() {
  const input = el.querySelector('input')!;
  act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'EXCLUIR CONTEUDO PRIVADO'); input.dispatchEvent(new Event('input', { bubbles: true })); });
  await flush();
  act(() => button('Confirmar exclusão').click()); await flush();
}
beforeEach(() => { vi.clearAllMocks(); el = document.createElement('div'); document.body.append(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });
it('exige confirmação digitada e permite cancelar sem chamar o servidor', async () => {
  await render(); expect(button('Confirmar exclusão').disabled).toBe(true);
  expect(el.textContent).toContain('Contato sintético');
  act(() => button('Cancelar').click()); expect(close).toHaveBeenCalledOnce(); expect(fetch).not.toHaveBeenCalled();
});
it('exclui pelo contrato existente e acompanha o recibo sem repetir DELETE', async () => {
  fetch.mockResolvedValueOnce(Response.json(receipt)).mockResolvedValueOnce(Response.json({ ...receipt, estado: 'concluido' }));
  await render(); await confirm();
  expect(fetch.mock.calls[0]![1]).toBe('/contacts/person-1/private-content');
  const options = fetch.mock.calls[0]![2]; expect(options.method).toBe('DELETE');
  expect(JSON.parse(options.body)).toEqual({ operation_id: expect.any(String), confirmacao: 'EXCLUIR CONTEUDO PRIVADO' });
  expect(erased).toHaveBeenCalledOnce(); expect(el.textContent).toContain('Limpeza externa pendente');
  expect(el.textContent).toContain('backups'); expect(el.textContent).toContain('receipt-1');
  act(() => button('Atualizar recibo').click()); await flush();
  expect(fetch.mock.calls[1]![1]).toBe('/igreja/private-deletions/receipt-1');
  expect(el.textContent).toContain('concluída no alcance operacional'); expect(erased).toHaveBeenCalledOnce();
});
it('repete a mesma operação após resultado ambíguo e não anuncia sucesso antes do recibo', async () => {
  fetch.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(Response.json(receipt));
  await render(); await confirm(); expect(erased).not.toHaveBeenCalled(); expect(el.querySelector('[role="alert"]')).not.toBeNull();
  act(() => button('Confirmar exclusão').click()); await flush();
  expect(fetch.mock.calls[1]![2].body).toBe(fetch.mock.calls[0]![2].body); expect(erased).toHaveBeenCalledOnce();
});
it('recusa 403 sem sucesso e trata sessão expirada', async () => {
  fetch.mockResolvedValueOnce(new Response('', { status: 403 })).mockRejectedValueOnce(new SessionExpiredError());
  await render(); await confirm(); expect(erased).not.toHaveBeenCalled();
  act(() => button('Confirmar exclusão').click()); await flush(); expect(expire).toHaveBeenCalledOnce();
});
it('bloqueia fechar e envio duplicado enquanto ocupado', async () => {
  fetch.mockReturnValue(new Promise(() => {})); await render(); await confirm();
  expect(button('Cancelar').disabled).toBe(true);
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(close).not.toHaveBeenCalled(); expect(fetch).toHaveBeenCalledOnce();
});

it('conserva a operação ao fechar e reabrir e rejeita recibo inválido', async () => {
  fetch.mockResolvedValueOnce(Response.json({ estado: 'concluido' })).mockResolvedValueOnce(Response.json(receipt));
  await render(); await confirm(); expect(erased).not.toHaveBeenCalled();
  await render(false); await render();
  act(() => button('Confirmar exclusão').click()); await flush();
  expect(fetch.mock.calls[1]![2].body).toBe(fetch.mock.calls[0]![2].body);
  expect(erased).toHaveBeenCalledOnce();
});
it('não aplica resposta antiga após desmontar por troca de sessão/pessoa', async () => {
  let resolve!: (response: Response) => void;
  fetch.mockReturnValue(new Promise<Response>(done => { resolve = done; }));
  await render(); await confirm();
  act(() => root.render(null));
  await act(async () => resolve(Response.json(receipt)));
  expect(erased).not.toHaveBeenCalled();
});

it('retém todas as camadas e exibe apenas rótulos seguros e contagens', async () => {
  const counts = { encontradas: 9, apagadas: 6, pendentes: 2, falhas: 1, texto: 'Conteúdo privado sintético' };
  const payload = { ...receipt, camadas: { entradas_audio: counts, 'chave com PII sintética': counts, __proto__: null } };
  fetch.mockResolvedValueOnce(Response.json(payload));
  await render(); await confirm();
  expect(el.textContent).toContain('Entradas de áudio');
  expect(el.textContent).toContain('Outra camada privada');
  expect(el.textContent).not.toContain('chave com PII');
  expect(el.textContent).not.toContain('Conteúdo privado sintético');
  expect(el.querySelectorAll('[aria-label="Recibo de exclusão privada"] li')).toHaveLength(2);
  expect(el.textContent?.match(/6 apagadas; 2 pendentes; 1 falhas/g)).toHaveLength(2);
});
