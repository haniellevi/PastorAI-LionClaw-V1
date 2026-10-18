// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { RequestDecisionPanel } from './RequestDecisionPanel';
import { RequestsPanel } from './RequestsPanel';
import type { CellRequest } from '@/lib/cell-requests-api';
const mocks=vi.hoisted(()=>({approve:vi.fn(),list:vi.fn()}));
vi.mock('@/lib/cell-requests-api',()=>({approveRequest:mocks.approve,listRequests:mocks.list}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
it('nomeação exige confirmação explícita e envia a versão exibida',async()=>{
 const request={id:'req',tipo:'nomear_lider',status:'aguardando',versao_proposta:3,payload_proposto:{novo_lider_id:'candidate'}} as unknown as CellRequest;
 mocks.approve.mockResolvedValue({...request,status:'aprovada'});
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try {
  await act(async()=>root.render(<RequestDecisionPanel token="fake" request={request} onDecided={vi.fn()} onToast={vi.fn()}/>));
  const approve=[...el.querySelectorAll('button')].find(b=>b.textContent?.includes('Aprovar'))!;
  expect(approve.disabled).toBe(true);
  const checkbox=el.querySelector('input[type="checkbox"]') as HTMLInputElement;
  expect(checkbox).not.toBeNull();
  await act(async()=>checkbox.click());
  await act(async()=>approve.click());
  expect(mocks.approve).toHaveBeenCalledWith('fake','req',undefined,{confirmar_execucao:true,versao_proposta:3});
 } finally {await act(async()=>root.unmount());el.remove()}
});

it('trocar a solicitação selecionada exige uma nova confirmação',async()=>{
 const base={tipo:'nomear_lider',status:'aguardando',versao_proposta:1,payload_proposto:{novo_lider_id:'candidate'}};
 mocks.list.mockResolvedValue({items:[{...base,id:'first'},{...base,id:'second'}]});
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try {
  await act(async()=>root.render(<RequestsPanel token="fake" onToast={vi.fn()}/>));
  await act(async()=>(el.querySelectorAll('.req-row')[0] as HTMLButtonElement).click());
  await act(async()=>(el.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
  expect((el.querySelector('input[type="checkbox"]') as HTMLInputElement).checked).toBe(true);
  await act(async()=>(el.querySelectorAll('.req-row')[1] as HTMLButtonElement).click());
  expect((el.querySelector('input[type="checkbox"]') as HTMLInputElement).checked).toBe(false);
 } finally {await act(async()=>root.unmount());el.remove()}
});
