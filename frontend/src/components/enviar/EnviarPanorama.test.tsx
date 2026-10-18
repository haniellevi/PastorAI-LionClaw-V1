// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { EnviarPanorama } from './EnviarPanorama';
const mocks=vi.hoisted(()=>({people:vi.fn(),history:vi.fn()}));
vi.mock('@/lib/enviar-api',()=>({getEnviarPessoas:mocks.people,getEnviarHistorico:mocks.history}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let cleanup=()=>{};
afterEach(()=>{cleanup();vi.resetAllMocks()});
async function render(){
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 cleanup=()=>{act(()=>root.unmount());el.remove()};
 await act(async()=>root.render(<EnviarPanorama token="fake" onExpired={()=>{}} canDecide={true}/>));
 return el;
}
it('lista formação e legado, navega histórico e busca com paginação',async()=>{
 mocks.people.mockResolvedValue({items:[{id:'p',nome:'Pessoa sintética',origem:'legado',situacao:'pendente',apto_lider:false,pendencias:[{criterio:'uv',descricao:'UV indisponível'}],ultima_avaliacao:null}],total:30,page:1,page_size:25});
 mocks.history.mockResolvedValue({items:[{id:'h',tipo:'nomear_lider',status:'aprovada',criada_em:'2026-10-18T12:00:00Z',decidido_em:null,celula_id:'c'}],total:1,page:1,page_size:25});
 const el=await render();
 expect(el.textContent).toContain('origem legada, comprovação pendente');
 expect(el.textContent).toContain('UV indisponível');
 const next=[...el.querySelectorAll('button')].find(b=>b.textContent==='Próxima página')!;
 await act(async()=>next.click());
 expect(mocks.people).toHaveBeenLastCalledWith('fake',expect.objectContaining({page:2}));
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Histórico')!.click());
 expect(el.textContent).toContain('Nomeação');
 expect(el.querySelector('a[href="#central-celula"]')).not.toBeNull();
});
it('falha de leitura não mostra estado vazio; permite repetir e mostra vazio real',async()=>{
 mocks.people.mockRejectedValueOnce(new Error('Falha sintética')).mockResolvedValue({items:[],total:0,page:1,page_size:25});
 const el=await render();
 expect(el.querySelector('[role="alert"]')?.textContent).toContain('Falha sintética');
 expect(el.textContent).not.toContain('Nenhuma pessoa neste filtro.');
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Repetir consulta')!.click());
 expect(el.textContent).toContain('Nenhuma pessoa neste filtro.');
});
