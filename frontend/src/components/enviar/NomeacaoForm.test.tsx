// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { NomeacaoForm } from './NomeacaoForm';
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
 await act(async()=>root.render(<NomeacaoForm token="fake" request={request}/>));
 async function click(text:string){
  const button=[...el.querySelectorAll('button')].find(b=>b.textContent===text);
  expect(button).toBeDefined();await act(async()=>button!.click());
 }
 return {el,click};
}
it('coordenação escolhe célula e candidato e cria proposta tipada sem nomear',async()=>{
 const {el,click}=await mount();
 await click('Célula sintética');await click('Candidato sintético');
 await act(async()=>el.querySelector('form')!.requestSubmit());
 expect(mocks.create).toHaveBeenCalledWith('fake',{celula_id:'cell',tipo:'nomear_lider',payload_proposto:{novo_lider_id:'person'}});
 expect(el.textContent).toContain('Solicitação enviada para aprovação');
});
it('autor ajusta o candidato por reenvio da solicitação existente',async()=>{
 const request={id:'request',celula_id:'cell',tipo:'nomear_lider'} as CellRequest;
 const {el,click}=await mount(request);
 await click('Candidato sintético');
 await act(async()=>el.querySelector('form')!.requestSubmit());
 expect(mocks.resubmit).toHaveBeenCalledWith('fake','request',{novo_lider_id:'person'});
 expect(mocks.create).not.toHaveBeenCalled();
});
