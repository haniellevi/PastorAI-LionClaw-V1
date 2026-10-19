// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { AvaliacaoPanel } from './AvaliacaoPanel';
const api=vi.hoisted(()=>({read:vi.fn(),save:vi.fn()}));
vi.mock('@/lib/enviar-api',()=>({getAvaliacao:api.read,postAvaliacao:api.save}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const data={pessoa_id:'synthetic',nome:'Pessoa sintética',apto_lider:true,origem:'legado',pendencias:{situacao:'pendente',status_regras:'aguarda confirmação pastoral',aviso_legado:'origem legada, comprovação pendente',pendencias:[{criterio:'uv',descricao:'UV: indisponível nesta base'}]},avaliacoes:[]};
let cleanup=()=>{};
afterEach(()=>{cleanup();vi.resetAllMocks()});
it('exibe legado e exige motivo e reconhecimento explícito antes de enviar',async()=>{
 api.read.mockResolvedValue(data);api.save.mockResolvedValue({});
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);cleanup=()=>{act(()=>root.unmount());el.remove()};
 await act(async()=>root.render(<AvaliacaoPanel pessoaId="synthetic" token="fake" onExpired={()=>{}}/>));
 expect(el.textContent).toContain('origem legada, comprovação pendente');
 expect(el.querySelector('textarea')?.required).toBe(true);
 const select=el.querySelector('select')!;
 act(()=>{select.value='apto';select.dispatchEvent(new Event('change',{bubbles:true}))});
 const check=el.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
 expect(check.required).toBe(true);
 act(()=>check.click());
 const reason=el.querySelector('textarea')!;
 act(()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(reason,'Histórico conferido');reason.dispatchEvent(new Event('input',{bubbles:true}))});
 await act(async()=>el.querySelector('form')!.requestSubmit());
 expect(api.save).toHaveBeenCalledWith('fake','synthetic',expect.objectContaining({decisao:'apto',origem:'legado',motivo:'Histórico conferido'}));
});
it('mostra erro de autorização sem formulário',async()=>{
 api.read.mockRejectedValue(new Error('Acesso restrito à coordenação'));
 const el=document.createElement('div');const root=createRoot(el);cleanup=()=>act(()=>root.unmount());
 await act(async()=>root.render(<AvaliacaoPanel pessoaId="synthetic" token="fake" onExpired={()=>{}}/>));
 expect(el.textContent).toContain('Acesso restrito à coordenação');expect(el.querySelector('form')).toBeNull();
});
it('evidência revogada bloqueia novas nomeações mesmo com projeção apto',async()=>{
 api.read.mockResolvedValue({...data,pendencias:{...data.pendencias,situacao:'bloqueado',pendencias:[{criterio:'cd',descricao:'CD certificado: evidência revogada'}]}});
 const el=document.createElement('div');const root=createRoot(el);cleanup=()=>act(()=>root.unmount());
 await act(async()=>root.render(<AvaliacaoPanel pessoaId="synthetic" token="fake" onExpired={()=>{}}/>));
 expect(el.textContent).toContain('Aptidão para novas nomeações: bloqueada.');
 expect(el.textContent).toContain('CD certificado: evidência revogada');
 expect(el.querySelector('form')).toBeNull();
});
