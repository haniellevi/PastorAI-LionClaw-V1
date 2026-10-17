// @vitest-environment jsdom
import {act, createElement as h} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, expect, it, vi} from 'vitest';
const api = vi.hoisted(() => ({lookupVisitorPeople: vi.fn(), registerVisitor: vi.fn()}));
vi.mock('@/lib/cell-meetings-api', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/cell-meetings-api')>(), ...api,
}));
const {VisitorsSection} = await import('./VisitorsSection');
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement;
beforeEach(() => {
  container = document.createElement('div'); document.body.append(container); root=createRoot(container);
  api.lookupVisitorPeople.mockImplementation(async (_token, _meeting, {q}) => ({items:q?.length >= 3 ? [
    {id:'p-a',nome:'Ana Sintética',telefone:'•••• 0077'},
    {id:'p-b',nome:'Ana Sintética',telefone:'•••• 0088'},
  ]:[],page:1,pageSize:20,total:q?.length >= 3 ? 2 : 0}));
  api.registerVisitor.mockResolvedValue({id:'v'});
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.clearAllMocks(); });
it('links an explicitly selected ID, never a homonym or expected name automatically', async () => {
  await act(async () => root.render(h(VisitorsSection, {token:'synthetic',reuniaoId:'meeting',
    expectations:[{id:'exp',nome_visitante:'Ana Sintética',indicado_por:'inviter',compareceu:false}],
    visitors:[],locked:false,onToast:vi.fn(),onChanged:vi.fn()})));
  const confirm = Array.from(container.querySelectorAll('button')).find(b => b.textContent?.includes('Confirmar presente'))!;
  expect(confirm.disabled).toBe(true);
  const input = container.querySelector('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input,'Ana');
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await act(async () => {await new Promise(resolve=>setTimeout(resolve,400));});
  expect(api.lookupVisitorPeople).toHaveBeenLastCalledWith('synthetic','meeting',expect.objectContaining({q:'Ana'}));
  const chosen = Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('0088'))!;
  expect(chosen).toBeDefined();
  await act(async () => chosen.click());
  await act(async () => confirm.click());
  expect(api.registerVisitor).toHaveBeenCalledWith('synthetic','meeting',expect.objectContaining({pessoa_id:'p-b',expectativa_id:'exp'}));
  expect(api.registerVisitor).not.toHaveBeenCalledWith(expect.anything(),expect.anything(),expect.objectContaining({pessoa_id:'p-a'}));
});
