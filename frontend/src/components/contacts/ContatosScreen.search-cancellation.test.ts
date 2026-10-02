// @vitest-environment jsdom
import {act,createElement as h} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
const api=vi.hoisted(()=>({fetchContactsPage:vi.fn(),fetchCells:vi.fn()}));
const auth=vi.hoisted(()=>({token:'synthetic-token',user:{roles:['pastor'],appUserId:'synthetic-user'},expireSession:vi.fn()}));
vi.mock('@/lib/auth-context',()=>({useAuth:()=>auth}));
vi.mock('@/lib/contacts-api',async(original)=>({...await original(),fetchContactsPage:api.fetchContactsPage}));
vi.mock('@/lib/dashboard-api',async(original)=>({...await original(),fetchCells:api.fetchCells}));
const {ContatosScreen}=await import('./ContatosScreen');
let root:any,container:HTMLDivElement;
beforeEach(()=>{
 vi.useFakeTimers();globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 api.fetchContactsPage.mockReset().mockResolvedValueOnce({items:[],total:0,page:1,pageSize:50}).mockImplementation(()=>new Promise(()=>{}));
 api.fetchCells.mockResolvedValue({items:[],total:0,page:1,pageSize:200});
 vi.stubGlobal('fetch',vi.fn(()=>{throw new Error('Network forbidden');}));
 container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.unstubAllGlobals();vi.useRealTimers();});
it('changing debounced contacts search cancels the obsolete complete legacy read',async()=>{
 await act(async()=>root.render(h(ContatosScreen)));
 const input=container.querySelector<HTMLInputElement>('#people-search')!;
 const type=async(text:string)=>{
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,text);input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>vi.advanceTimersByTimeAsync(251));
 };
 await type('a');
 const first=api.fetchContactsPage.mock.calls[1]?.[1];
 expect(first?.q).toBe('a');
 await type('ab');
 expect(api.fetchContactsPage.mock.calls[2]?.[1]?.q).toBe('ab');
 expect(first?.signal?.aborted).toBe(true);
 const latest=api.fetchContactsPage.mock.calls[2]?.[1];expect(latest.signal.aborted).toBe(false);
 await act(async()=>root.render(null));expect(latest.signal.aborted).toBe(true);
});

it('obsolete aborted reads do not show an error or replace the current query',async()=>{
 api.fetchContactsPage.mockReset().mockImplementation((_token:string,params:{signal:AbortSignal})=>new Promise((_resolve,reject)=>params.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}))).mockResolvedValueOnce({items:[],total:0,page:1,pageSize:50});
 await act(async()=>root.render(h(ContatosScreen)));
 const input=container.querySelector<HTMLInputElement>('#people-search')!;
 const type=async(text:string)=>{await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,text);input.dispatchEvent(new Event('input',{bubbles:true}));});await act(async()=>vi.advanceTimersByTimeAsync(251));};
 await type('a');await type('ab');
 expect(input.value).toBe('ab');expect(container.textContent).not.toContain('Não foi possível carregar os contatos.');
 expect(api.fetchContactsPage.mock.calls[1]?.[1]?.signal.aborted).toBe(true);
 expect(api.fetchContactsPage.mock.calls[2]?.[1]?.signal.aborted).toBe(false);
});
