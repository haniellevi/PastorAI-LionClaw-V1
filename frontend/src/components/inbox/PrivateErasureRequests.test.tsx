// @vitest-environment jsdom
import { act, createElement as h } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const mocks=vi.hoisted(()=>({fetch:vi.fn()}));
vi.mock('@/lib/dashboard-api',()=>({authedFetch:mocks.fetch}));
import { PrivateErasureRequests } from './PrivateErasureRequests';
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let container:HTMLDivElement,root:Root;
const pending={id:'request-a',state:'pendente',created_at:'2026-10-20T12:00:00Z',receipt:null};
beforeEach(()=>{mocks.fetch.mockReset();container=document.createElement('div');document.body.append(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
function render(person='person-a') {root.render(h(PrivateErasureRequests,{token:'synthetic',personId:person,expireSession:vi.fn()}));}
function button(label:string){return Array.from(container.querySelectorAll('button')).find(b=>b.textContent===label)!;}
it('requires confirmation and shows durable pending receipt',async()=>{
 mocks.fetch.mockResolvedValueOnce(Response.json({items:[pending]}));
 await act(async()=>render());
 expect(container.textContent).toContain('memória suspenso');
 await act(async()=>button('Aprovar exclusão').click());
 expect(mocks.fetch).toHaveBeenCalledTimes(1);
 mocks.fetch.mockResolvedValueOnce(Response.json({...pending,state:'aprovado',receipt:{estado:'pendente',fora_do_alcance:'backups'}}));
 await act(async()=>button('Confirmar exclusão').click());
 expect(mocks.fetch.mock.calls[1]![1]).toBe('/private-erasure-requests/request-a/decision');
 expect(JSON.parse(mocks.fetch.mock.calls[1]![2].body).decision).toBe('aprovado');
 expect(container.textContent).toContain('Limpeza externa pendente');
});
it('keeps failed decision available for retry',async()=>{
 mocks.fetch.mockResolvedValueOnce(Response.json({items:[pending]}));
 await act(async()=>render());
 await act(async()=>button('Recusar pedido').click());
 mocks.fetch.mockRejectedValueOnce(new Error('network'));
 await act(async()=>button('Confirmar recusa').click());
 expect(container.querySelector('[role=alert]')?.textContent).toContain('Não foi possível');
 expect(button('Confirmar recusa')).toBeDefined();
});
it('ignores stale reads after contact changes',async()=>{
 let resolve!:(r:Response)=>void;
 mocks.fetch.mockImplementationOnce(()=>new Promise<Response>(r=>{resolve=r;}));
 await act(async()=>render());
 mocks.fetch.mockResolvedValueOnce(Response.json({items:[]}));
 await act(async()=>render('person-b'));
 await act(async()=>resolve(Response.json({items:[pending]})));
 expect(container.textContent).not.toContain('Aprovar exclusão');
});
