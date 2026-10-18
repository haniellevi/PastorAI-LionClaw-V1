// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { AberturaForm } from './AberturaForm';
import type { CellRequest } from '@/lib/cell-requests-api';
const mocks=vi.hoisted(()=>({create:vi.fn(),resubmit:vi.fn()}));
vi.mock('@/lib/auth-context',()=>({useAuth:()=>({expireSession:vi.fn()})}));
vi.mock('@/lib/cell-requests-api',()=>({createRequest:mocks.create,resubmitRequest:mocks.resubmit}));
vi.mock('@/lib/lookup-api',()=>({
 fetchCellLookupPage:async()=>({items:[{id:'cell',nome:'Célula sintética',ativo:true}],page:1,pageSize:25,total:1}),
 fetchContactLookupPage:async()=>({items:[{id:'person',nome:'Candidato sintético'}],page:1,pageSize:25,total:1}),
}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let dispose=()=>{};
afterEach(()=>{dispose();vi.clearAllMocks()});
async function mount(request?:CellRequest){
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 dispose=()=>{act(()=>root.unmount());el.remove()};
 await act(async()=>root.render(<AberturaForm token="fake" request={request}/>));
 async function click(text:string){
  const button=[...el.querySelectorAll('button')].find(b=>b.textContent===text);
  expect(button).toBeDefined();await act(async()=>button!.click());
 }
 return {el,click};
}
it('envia abertura sem origem com candidato, nome e cobertura',async()=>{
 const request={id:'request',tipo:'abrir_celula',payload_proposto:{nome:'Nova sintética',cobertura_espiritual:'Cobertura'}} as unknown as CellRequest;
 const {el,click}=await mount(request);
 await click('Candidato sintético');
 await act(async()=>el.querySelector('form')!.requestSubmit());
 expect(mocks.resubmit).toHaveBeenCalledWith('fake','request',expect.objectContaining({nome:'Nova sintética',cobertura_espiritual:'Cobertura',novo_lider_id:'person'}));
 expect(mocks.create).not.toHaveBeenCalled();
});
it('cria proposta sem celula_id e não envia sem os obrigatórios',async()=>{
 const {el,click}=await mount();
 const submit=el.querySelector('button[type="submit"]') as HTMLButtonElement;
 expect(submit.disabled).toBe(true);
 const inputs=el.querySelectorAll('input[maxlength="200"]');
 const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!;
 await act(async()=>{
  setter.call(inputs[0],'Nova sintética'); inputs[0]!.dispatchEvent(new Event('input',{bubbles:true}));
  setter.call(inputs[1],'Cobertura'); inputs[1]!.dispatchEvent(new Event('input',{bubbles:true}));
 });
 await click('Candidato sintético');
 await act(async()=>el.querySelector('form')!.requestSubmit());
 expect(mocks.create).toHaveBeenCalledWith('fake',{tipo:'abrir_celula',payload_proposto:{nome:'Nova sintética',cobertura_espiritual:'Cobertura',novo_lider_id:'person'}});
});
