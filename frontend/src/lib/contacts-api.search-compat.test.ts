import {afterEach,expect,it,vi} from "vitest";
import {fetchContactsPage} from "./contacts-api";
import {clearAuthedResponseCache} from "./dashboard-api";
afterEach(()=>{vi.unstubAllGlobals();clearAuthedResponseCache();});
const rows=Array.from({length:201},(_,index)=>({id:`synthetic-${index}`,nome:index===200?"Pessoa Encontrável":"Pessoa sintética",telefone:index===200?"5500000000201":"5500000000000",email:index===200?"target@example.test":null}));
it("preserves legacy search beyond row200 when old server ignores q",async()=>{
 const request=vi.fn(async(input:RequestInfo|URL)=>{const query=new URL(String(input)).searchParams;const page=Number(query.get("page"));const size=Number(query.get("pageSize"));return Response.json({items:rows.slice((page-1)*size,page*size),total:201,page,pageSize:size});});vi.stubGlobal("fetch",request);
 const result=await fetchContactsPage("legacy-search",{page:1,pageSize:50,view:"membro",q:"ENCONTRÁVEL"});
 expect(result.items.map(item=>item.id)).toEqual(["synthetic-200"]);expect(result.total).toBe(1);expect(request).toHaveBeenCalledTimes(3);
 expect(request.mock.calls.slice(1).every(([input])=>{const q=new URL(String(input)).searchParams;return !q.has("q")&&q.get("view")==="membro";})).toBe(true);
});
it("uses exactly one paginated search when server advertises its capability",async()=>{
 const request=vi.fn().mockResolvedValue(Response.json({items:[rows[200]],total:1,page:1,pageSize:50,searchSupported:true}));vi.stubGlobal("fetch",request);
 expect((await fetchContactsPage("new-search",{q:"target",pageSize:50})).items).toEqual([rows[200]]);expect(request).toHaveBeenCalledTimes(1);
});
it("does not broaden unauthorized search into legacy reads",async()=>{
 const request=vi.fn().mockResolvedValue(Response.json({detail:"Access denied"},{status:403}));vi.stubGlobal("fetch",request);
 await expect(fetchContactsPage("denied-search",{q:"target"})).rejects.toMatchObject({status:403});expect(request).toHaveBeenCalledTimes(1);
});
it("rejects duplicate legacy pages rather than claiming complete search",async()=>{
 const request=vi.fn(async()=>Response.json({items:rows.slice(0,200),total:201,page:1,pageSize:200}));vi.stubGlobal("fetch",request);
 await expect(fetchContactsPage("duplicate-search",{q:"target"})).rejects.toMatchObject({status:502});
});

it("stops legacy collection after caller cancellation",async()=>{
 const controller=new AbortController();let reads=0;
 const request=vi.fn(async()=>{reads+=1;if(reads===2)controller.abort();return Response.json({items:rows.slice(0,200),total:201,page:1,pageSize:200});});vi.stubGlobal("fetch",request);
 await expect(fetchContactsPage("aborted-search",{q:"target",signal:controller.signal})).rejects.toMatchObject({name:"AbortError"});expect(request).toHaveBeenCalledTimes(2);
});
it("rejects a changing legacy total without pretending the result is complete",async()=>{
 const request=vi.fn(async(input:RequestInfo|URL)=>{const query=new URL(String(input)).searchParams;const page=Number(query.get("page"));const size=Number(query.get("pageSize"));return Response.json({items:rows.slice((page-1)*size,page*size),total:page===2?202:201,page,pageSize:size});});vi.stubGlobal("fetch",request);
 await expect(fetchContactsPage("drifting-search",{q:"target",pageSize:50})).rejects.toMatchObject({status:502});expect(request).toHaveBeenCalledTimes(3);
});
