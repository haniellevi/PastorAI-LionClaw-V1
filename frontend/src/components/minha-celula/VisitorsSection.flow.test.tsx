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
async function renderSection() {
  await act(async () => root.render(h(VisitorsSection, {token:'synthetic',reuniaoId:'meeting',
    expectations:[{id:'exp',nome_visitante:'Maria Sintética',indicado_por:'inviter',compareceu:false}],
    visitors:[],locked:false,onToast:vi.fn(),onChanged:vi.fn()})));
}
async function fill(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input,value);
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
}
async function choose(input: HTMLInputElement) {
  await fill(input,'Ana');
  await act(async () => {await new Promise(resolve=>setTimeout(resolve,400));});
  const chosen = Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('0088'))!;
  await act(async () => chosen.click());
}
it('does not reuse the general Person B selection to confirm Maria by name', async () => {
  await renderSection();
  await choose(container.querySelector('input[id="visit-person-meeting"]')!);
  const confirm = Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Confirmar Maria Sintética só pelo nome'))!;
  expect(confirm).toBeDefined();
  await act(async () => confirm.click());
  expect(api.registerVisitor).toHaveBeenCalledWith('synthetic','meeting',{
    nome_visitante:'Maria Sintética',expectativa_id:'exp',
  });
});
it('requires a separate explicit choice and shows both names before linking Maria to Person B', async () => {
  await renderSection();
  await choose(container.querySelector('input[id="visit-expected-exp"]')!);
  const confirm = Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.includes('Confirmar Maria Sintética como Ana Sintética'))!;
  expect(api.registerVisitor).not.toHaveBeenCalled();
  await act(async () => confirm.click());
  expect(api.registerVisitor).toHaveBeenCalledWith('synthetic','meeting',{
    pessoa_id:'p-b',nome_visitante:'Ana Sintética',expectativa_id:'exp',
  });
});
it('registers a new visitor by name and observation without a Person ID', async () => {
  await renderSection();
  await act(async () => Array.from(container.querySelectorAll('input')).find(i=>i.value==='name')!.click());
  await fill(container.querySelector('input[id="vis-name-meeting"]')!,'Nova Sintética');
  await act(async () => {
    const obs=container.querySelector('textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(obs,'Primeira visita');
    obs.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await act(async () => container.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.registerVisitor).toHaveBeenCalledWith('synthetic','meeting',{
    nome_visitante:'Nova Sintética',observacao:'Primeira visita',
  });
});
