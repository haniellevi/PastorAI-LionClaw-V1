// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { canSee } from '@/lib/permissions';
import { EnviarScreen } from './EnviarScreen';
const mocks=vi.hoisted(()=>({lookup:vi.fn(),read:vi.fn(),expire:vi.fn()}));
vi.mock('@/lib/auth-context',()=>({useAuth:()=>({token:'fake',user:{roles:['pastor']},expireSession:mocks.expire})}));
vi.mock('@/lib/multiplicacoes-api',()=>({getMultiplicacoesList:async()=>({pendentes:[],registradas:[]})}));
vi.mock('@/lib/lookup-api',()=>({fetchContactLookupPage:mocks.lookup,fetchCellLookupPage:async()=>({items:[],page:1,pageSize:25,total:0})}));
vi.mock('@/lib/cell-requests-api',()=>({listRequests:async()=>({items:[],page:1,pageSize:25,total:0})}));
vi.mock('@/lib/enviar-api',()=>({getAvaliacao:mocks.read,getEnviarPessoas:async()=>({items:[],total:0,page:1,page_size:25}),getEnviarHistorico:async()=>({items:[],total:0,page:1,page_size:25})}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let cleanup=()=>{};
afterEach(()=>{cleanup();vi.resetAllMocks()});
it('pastor sem admin acessa Enviar e seleciona pessoa para avaliação',async()=>{
 expect(canSee('contatos',['pastor'])).toBe(false);
 expect(canSee('enviar',['pastor'])).toBe(true);
 mocks.lookup.mockResolvedValue({items:[{id:'synthetic',nome:'Pessoa sintética'}],page:1,pageSize:25,total:1});
 mocks.read.mockResolvedValue({pessoa_id:'synthetic',nome:'Pessoa sintética',apto_lider:false,origem:null,pendencias:{situacao:'pendente',status_regras:'aguarda confirmação pastoral',pendencias:[]},avaliacoes:[]});
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);cleanup=()=>{act(()=>root.unmount());el.remove()};
 await act(async()=>root.render(<EnviarScreen/>));
 const candidate=[...el.querySelectorAll('button')].find(b=>b.textContent==='Pessoa sintética');
 expect(candidate).toBeDefined();
 await act(async()=>candidate!.click());
 expect(mocks.read).toHaveBeenCalledWith('fake','synthetic');
 expect(el.querySelector('form')).not.toBeNull();
 expect(el.textContent).toContain('Decisão da coordenação');
});
