// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { canSee } from '@/lib/permissions';
import { EnviarScreen } from './EnviarScreen';
const mocks=vi.hoisted(()=>({people:vi.fn(),expire:vi.fn()}));
vi.mock('@/lib/auth-context',()=>({useAuth:()=>({token:'fake',user:{roles:['pastor']},expireSession:mocks.expire})}));
vi.mock('@/lib/multiplicacoes-api',()=>({getMultiplicacoesList:async()=>({pendentes:[],registradas:[]})}));
vi.mock('@/lib/lookup-api',()=>({fetchContactLookupPage:vi.fn()}));
vi.mock('@/lib/enviar-api',()=>({getEnviarPessoas:mocks.people,getEnviarHistorico:async()=>({items:[],total:0,page:1,page_size:25})}));
vi.mock('../lookups/PaginatedLookup',()=>({PaginatedLookup:({onSelect}:{onSelect:(person:{id:string;nome:string})=>void})=><button onClick={()=>onSelect({id:'p',nome:'Sintética'})}>Selecionar pessoa sintética</button>}));
vi.mock('./AvaliacaoPanel',()=>({AvaliacaoPanel:({onSaved}:{onSaved:()=>void})=><button onClick={onSaved}>Salvar avaliação sintética</button>}));
vi.mock('./AberturaForm',()=>({AberturaForm:({onCreated}:{onCreated:()=>void})=><button onClick={onCreated}>Criar abertura sintética</button>}));
vi.mock('./NomeacaoForm',()=>({NomeacaoForm:({onCreated}:{onCreated:()=>void})=><button onClick={onCreated}>Criar nomeação sintética</button>}));
vi.mock('../minha-celula/MyRequestsList',()=>({MyRequestsList:()=>null}));
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let cleanup=()=>{};
afterEach(()=>{cleanup();vi.clearAllMocks()});
it('líder de célula alcança Enviar pelos defaults, preservando matriz customizada',()=>{
 expect(canSee('enviar',['lider_celula'])).toBe(true);
 expect(canSee('enviar',['lider_celula'],{lider_celula:['dashboard']})).toBe(false);
});
it('atualiza panorama após avaliação, abertura, nomeação e botão Atualizar',async()=>{
 mocks.people.mockResolvedValue({items:[],total:0,page:1,page_size:25});
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 cleanup=()=>{act(()=>root.unmount());el.remove()};
 await act(async()=>root.render(<EnviarScreen/>));
 await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Selecionar pessoa sintética')!.click());
 for(const label of ['Salvar avaliação sintética','Criar abertura sintética','Criar nomeação sintética',' Atualizar']){
   const before=mocks.people.mock.calls.length;
   await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent===label)!.click());
   expect(mocks.people.mock.calls.length).toBeGreaterThan(before);
 }
});
