import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("./dashboard-api", async () => ({
  ...await vi.importActual<typeof import("./dashboard-api")>("./dashboard-api"),
  authedFetch: mocks.fetch,
}));
import { fetchContactLookupPage, fetchCellLookupPage, fetchCellStats, fetchCellListPage } from "./lookup-api";

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
beforeEach(() => { mocks.fetch.mockReset(); });

describe("lookups paginados", () => {
  it("envia busca, página e filtro de célula ao servidor e preserva total real", async () => {
    const page = { items: [{ id: "p-901", nome: "Ana distante" }], page: 3, pageSize: 25, total: 78 };
    mocks.fetch.mockResolvedValue(response(page));
    expect(await fetchContactLookupPage("token", { q: " Ana ", page: 3, view: "pastor", celulaId: "c-2" })).toEqual(page);
    const params = new URL(`https://test${mocks.fetch.mock.calls[0]![1]}`).searchParams;
    expect(params.get("page")).toBe("3");
    expect(params.get("q")).toBe("Ana");
    expect(params.get("view")).toBe("pastor");
    expect(params.get("celulaId")).toBe("c-2");
  });
  it("fallback404 encontra pessoa após200 registros em backend sem busca", async () => {
    const first = Array.from({ length: 200 }, (_, id) => ({ id: `p-${id}`, nome: `Pessoa ${id}`, telefone: "000", celulaId: "outra" }));
    mocks.fetch.mockResolvedValueOnce(response({}, 404))
      .mockResolvedValueOnce(response({ items: first, total: 201, page: 1, pageSize: 200 }))
      .mockResolvedValueOnce(response({ items: [{ id: "p-201", nome: "Ána Remota", telefone: "123", celulaId: "c-2" }], total: 201, page: 2, pageSize: 200 }));
    const page = await fetchContactLookupPage("token", { q: "ana", celulaId: "c-2" });
    expect(page.total).toBe(1);
    expect(page.items.map((item) => item.id)).toEqual(["p-201"]);
    expect(mocks.fetch.mock.calls[2]![1]).toContain("page=2");
  });
  it.each([401, 403, 500])("não contorna erro%s com coleção legada", async (status) => {
    mocks.fetch.mockResolvedValue(response({}, status));
    await expect(fetchCellLookupPage("token")).rejects.toMatchObject({ status });
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
  });
  it("recusa coleção legada incompleta em vez de afirmar total menor", async () => {
    mocks.fetch.mockResolvedValueOnce(response({}, 404))
      .mockResolvedValueOnce(response({ items: [], total: 400, page: 1, pageSize: 200 }));
    await expect(fetchCellLookupPage("token")).rejects.toMatchObject({ status: 502 });
  });
  it("interrompe backend que repete a página anterior", async () => {
    mocks.fetch.mockResolvedValueOnce(response({}, 404))
      .mockResolvedValueOnce(response({ items: [{ id: "c-1", nome: "Célula" }], total: 5, page: 1, pageSize: 200 }))
      .mockResolvedValueOnce(response({ items: [{ id: "c-1", nome: "Célula" }], total: 5, page: 1, pageSize: 200 }));
    await expect(fetchCellLookupPage("token")).rejects.toMatchObject({ status: 502 });
    expect(mocks.fetch).toHaveBeenCalledTimes(3);
  });
  it("restaura indicadores, nomes e contagens com201+ células e Pessoas no backend antigo", async () => {
    const cells = Array.from({ length: 201 }, (_, id) => ({ id: `c-${id}`, nome: `Célula ${id}`, liderId: id === 200 ? "p-200" : null, ativo: id !== 200 }));
    const people = Array.from({ length: 202 }, (_, id) => ({ id: `p-${id}`, nome: id === 200 ? "Líder além200" : `Pessoa ${id}`, celulaId: "c-200", tipo: id === 201 ? "visitante" : "membro" }));
    mocks.fetch.mockImplementation(async (_token: string, path: string) => {
      if (path === "/cells/summary") return response({}, 404);
      const url = new URL(`https://test${path}`);
      const page = Number(url.searchParams.get("page"));
      const items = url.pathname === "/cells" ? cells : people;
      if (url.pathname === "/contacts") expect(url.searchParams.get("view")).toBe("all");
      return response({ items: items.slice((page - 1) * 200, page * 200), total: items.length, page, pageSize: 200 });
    });
    const result = await fetchCellStats("token");
    expect(result).toMatchObject({ total: 201, ativas: 200, semLider: 200, pessoasEmCelulas: 202 });
    expect(result.legacyCells?.find((cell) => cell.id === "c-200")).toMatchObject({ liderNome: "Líder além200", membros: 201, visitantes: 1 });
    expect(mocks.fetch).toHaveBeenCalledTimes(5);
  });
  it("API nova entrega os indicadores sem coleções globais", async () => {
    const summary = { total: 301, ativas: 299, semLider: 2, pessoasEmCelulas: 4000 };
    mocks.fetch.mockResolvedValue(response(summary));
    expect(await fetchCellStats("token")).toEqual(summary);
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(mocks.fetch.mock.calls[0]![1]).toBe("/cells/summary");
  });
  it.each([401, 403])("indicadores propagam%s sem ativar fallback legado", async (status) => {
    mocks.fetch.mockResolvedValue(response({}, status));
    await expect(fetchCellStats("token")).rejects.toMatchObject({ status });
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
  });
  it("fallback de indicadores propaga bloqueio de contatos e não entrega contagens parciais", async () => {
    mocks.fetch.mockImplementation(async (_token: string, path: string) => {
      if (path === "/cells/summary") return response({}, 404);
      if (path.startsWith("/contacts?")) return response({}, 403);
      return response({ items: [], page: 1, pageSize: 200, total: 0 });
    });
    await expect(fetchCellStats("token")).rejects.toMatchObject({ status: 403 });
  });
});

describe("cell list legacy search",()=>{
 const cells=Array.from({length:201},(_,n)=>({id:`synthetic-cell-${n}`,nome:n===200?"Célula distante":"Célula sintética",liderId:n===200?"synthetic-person-200":null,ativo:true}));
 const people=Array.from({length:202},(_,n)=>({id:`synthetic-person-${n}`,nome:n===200?"Líder Encontrável":"Pessoa sintética",celulaId:n>=200?"synthetic-cell-200":null,tipo:n===201?"visitante":"membro"}));
 const legacy=async(_token:string,path:string)=>{
  const url=new URL(`https://test${path}`);if(url.pathname==="/cells/lookup")return response({},404);
  const rows=url.pathname==="/cells"?cells:people;const page=Number(url.searchParams.get("page"));
  if(url.pathname==="/contacts")expect(url.searchParams.get("view")).toBe("all");
  expect(url.searchParams.has("q")).toBe(false);
  return response({items:rows.slice((page-1)*200,page*200),total:rows.length,page,pageSize:200});
 };
 it("finds leader-only match beyond200 cells and people while preserving counts",async()=>{
  mocks.fetch.mockImplementation(legacy);
  const result=await fetchCellListPage("token",{q:"lider encontravel",pageSize:25});
  expect(result.total).toBe(1);expect(result.items).toHaveLength(1);
  expect(result.items[0]).toMatchObject({id:"synthetic-cell-200",liderNome:"Líder Encontrável",membros:1,visitantes:1});
  expect(mocks.fetch).toHaveBeenCalledTimes(5);
 });
 it("keeps cell-name search, confirmed empty search and reset on the legacy view",async()=>{
  mocks.fetch.mockImplementation(legacy);
  expect((await fetchCellListPage("token",{q:"distante"})).items.map(item=>item.id)).toEqual(["synthetic-cell-200"]);
  expect((await fetchCellListPage("token",{q:"absent"}))).toMatchObject({items:[],total:0});
  expect((await fetchCellListPage("token",{pageSize:25}))).toMatchObject({total:201});
 });
 it.each([401,403])("does not read legacy people after lookup denial%s",async(status)=>{
  mocks.fetch.mockResolvedValue(response({},status));await expect(fetchCellListPage("token",{q:"leader"})).rejects.toMatchObject({status});expect(mocks.fetch).toHaveBeenCalledTimes(1);
 });
 it("rejects drifting legacy cell totals rather than silently omitting matches",async()=>{
  mocks.fetch.mockImplementation(async(token:string,path:string)=>{
   const url=new URL(`https://test${path}`);if(url.pathname==="/cells"&&url.searchParams.get("page")==="2")return response({items:[cells[200]],total:202,page:2,pageSize:200});return legacy(token,path);
  });
  await expect(fetchCellListPage("token",{q:"leader"})).rejects.toMatchObject({status:502});
 });
 it("finds explicitly leaderless cells without labeling unreadable leader IDs as leaderless",async()=>{
  const rows=[...cells,{id:"synthetic-unreadable-cell",nome:"Célula com líder não enumerável",liderId:"synthetic-unreadable-person",ativo:true}];
  mocks.fetch.mockImplementation(async(token:string,path:string)=>{
   const url=new URL(`https://test${path}`);if(url.pathname!=="/cells")return legacy(token,path);
   const page=Number(url.searchParams.get("page"));return response({items:rows.slice((page-1)*200,page*200),total:rows.length,page,pageSize:200});
  });
  const result=await fetchCellListPage("token",{q:"Sem líder",page:8,pageSize:25});
  expect(result.total).toBe(200);expect(result.items).toHaveLength(25);
  expect(result.items.every(cell=>cell.liderId===null)).toBe(true);
  expect(result.items.map(cell=>cell.id)).toEqual(Array.from({length:25},(_,n)=>`synthetic-cell-${175+n}`));
 });
 it("cancels legacy search before starting the next pages",async()=>{
  const controller=new AbortController();mocks.fetch.mockImplementation(async(token:string,path:string)=>{const result=await legacy(token,path);if(path.startsWith("/cells?page=1"))controller.abort();return result;});
  await expect(fetchCellListPage("token",{q:"leader",signal:controller.signal})).rejects.toMatchObject({name:"AbortError"});
  expect(mocks.fetch.mock.calls.some(([,path])=>String(path).includes("page=2"))).toBe(false);
 });
});
