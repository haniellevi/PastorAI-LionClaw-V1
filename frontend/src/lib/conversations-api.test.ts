// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchConversations,
  fetchInboxAgentStatus,
  fetchInboxTransferTargets,
  fetchMessages,
  MAX_MEDIA_BYTES,
  sendMedia,
} from "./conversations-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GETs do inbox", () => {
  it("propaga o AbortSignal para conversas e mensagens", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], page: 1, pageSize: 100, total: 0 }),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const conversationsController = new AbortController();
    const messagesController = new AbortController();

    await fetchConversations("token", 100, conversationsController.signal);
    await fetchMessages("token", "conversation", 200, messagesController.signal);

    const conversationsCall = fetchSpy.mock.calls.at(0);
    const messagesCall = fetchSpy.mock.calls.at(1);
    if (!conversationsCall || !messagesCall) throw new Error("GETs esperados não foram chamados");
    expect(conversationsCall[1]).toMatchObject({ signal: conversationsController.signal });
    expect(messagesCall[1]).toMatchObject({ signal: messagesController.signal });
  });

  it("lê somente o estado global mínimo do agente e propaga o AbortSignal", async () => {
    const payload = { configured: true, ativo: false, pausedByChurch: true };
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => payload,
    });
    vi.stubGlobal("fetch", fetchSpy);
    const controller = new AbortController();

    await expect(fetchInboxAgentStatus("token", controller.signal)).resolves.toEqual(
      payload,
    );
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/conversations/agent-status");
    expect(fetchSpy.mock.calls[0]?.[1]).toMatchObject({ signal: controller.signal });
  });

  it("percorre todas as páginas de destinos de transferência", async () => {
    const firstPage = Array.from({ length: 200 }, (_, index) => ({
      usuarioId: `u-${index}`,
      nome: `Responsável ${index}`,
      papeis: ["operador"],
    }));
    const lastTarget = {
      usuarioId: "u-eligible",
      nome: "Responsável da página 2",
      papeis: ["lider_celula"],
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ items: firstPage, page: 1, pageSize: 200, total: 201 }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ items: [lastTarget], page: 2, pageSize: 200, total: 201 }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchSpy);

    const result = await fetchInboxTransferTargets("token");

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(String(fetchSpy.mock.calls[1]?.[0])).toContain("page=2&pageSize=200");
    expect(result.items).toHaveLength(201);
    expect(result.items.at(-1)).toEqual(lastTarget);
  });
});

describe("sendMedia", () => {
  it("rejeita arquivo acima de 16 MB antes de ler ou chamar a rede", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const oversized = { size: MAX_MEDIA_BYTES + 1 } as File;

    await expect(sendMedia("token", "conversation", oversized)).rejects.toThrow(
      "Arquivo excede o limite de 16 MB.",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});


it("lê janela recente sem aguardar URLs de mídia e reaproveita cursor opaco", async () => {
  const { fetchMessageWindow, fetchMessageMediaUrls } = await import("./conversations-api");
  const request = vi.fn().mockResolvedValueOnce(Response.json({ items: [], page: 1, pageSize: 50, total: 400, nextBefore: "before-token", nextAfter: "after-token" }))
    .mockResolvedValueOnce(Response.json({ urls: { "message-1": "https://example.com/synthetic" } }));
  vi.stubGlobal("fetch", request);
  const page = await fetchMessageWindow("token", "conversation", { after: "cursor-token" });
  expect(page.cursorSupported).toBe(true);
  expect(request.mock.calls[0]?.[0]).toContain("includeMedia=false&after=cursor-token");
  expect(await fetchMessageMediaUrls("token", "conversation", ["message-1"])).toEqual({ "message-1": "https://example.com/synthetic" });
});


it("reconciles a delayed confirmation behind more than 50 newer messages and removes a deleted loaded row", async () => {
  const {fetchLoadedMessageRange} = await import("./conversations-api");
  const make = (n: number,text: string) => ({id:`m${String(n).padStart(3,"0")}`,criadoEm:`2026-10-02T12:${String(Math.floor(n/60)).padStart(2,"0")}:${String(n%60).padStart(2,"0")}Z`,tipo:"texto",texto:text,mediaUrl:null});
  const loaded = Array.from({length:70},(_,n)=>make(n,n===0?"PENDING":"already loaded"));
  const current = Array.from({length:71},(_,n)=>make(n,n===0?"CONFIRMED":"newer")).filter(row=>row.id!=="m001");
  const request = vi.fn(async(input: RequestInfo | URL)=> {
    const query = new URL(String(input)).searchParams;
    if (!query.has("before")) return Response.json({items:current.slice(-50),total:70,page:1,pageSize:50,nextBefore:"older-window",nextAfter:"newest"});
    return Response.json({items:current.slice(0,-50),total:70,page:1,pageSize:50,nextBefore:null,nextAfter:"old-page-newest"});
  });
  vi.stubGlobal("fetch",request);
  const range = await fetchLoadedMessageRange("token","conversation",loaded as never);
  expect(range.items.find(row=>row.id==="m000")?.texto).toBe("CONFIRMED");
  expect(range.items.some(row=>row.id==="m001")).toBe(false);
  expect(range.items.at(-1)?.id).toBe("m070");
  expect(range.items).toHaveLength(70);
  expect(request).toHaveBeenCalledTimes(2);
  expect(range.nextAfter).toBe("newest");
  expect(range.rangeReconciled).toBe(true);
});

it("fully loaded history rechecks the prefix newly published before its former oldest row",async()=>{
 const {fetchLoadedMessageRange}=await import("./conversations-api");
 const make=(id:string,criadoEm:string)=>({id,criadoEm,tipo:"texto",texto:"CONFIRMED",mediaUrl:null});
 const loaded=[make("m102","2026-10-02T12:00:02Z"),make("m103","2026-10-02T12:00:03Z")];
 const prefix=make("m101","2026-10-02T12:00:01Z");
 const request=vi.fn().mockResolvedValueOnce(Response.json({items:loaded,total:3,page:1,pageSize:50,nextBefore:"new-prefix",nextAfter:"m103"})).mockResolvedValueOnce(Response.json({items:[prefix],total:3,page:1,pageSize:50,nextBefore:null,nextAfter:"m101"}));vi.stubGlobal("fetch",request);
 const result=await fetchLoadedMessageRange("prefix-token","conversation",loaded as never,undefined,true);
 expect(result.items.map(item=>item.id)).toEqual(["m101","m102","m103"]);expect(result.nextBefore).toBeNull();expect(request).toHaveBeenCalledTimes(2);
});

it("reconciles 50 loaded and 150 newer rows instead of repeating an undersized budget",async()=>{
 const {fetchLoadedMessageRange}=await import("./conversations-api");
 const rows=Array.from({length:200},(_,n)=>({id:`m${String(n).padStart(3,"0")}`,criadoEm:new Date(Date.UTC(2026,9,2,12,0,n)).toISOString(),tipo:"texto",texto:n===0?"CONFIRMED":"text",mediaUrl:null}));
 const request=vi.fn(async(input:RequestInfo | URL)=>{const before=new URL(String(input)).searchParams.get("before");const end=before?Number(before):200;const start=Math.max(0,end-50);return Response.json({items:rows.slice(start,end),total:200,page:1,pageSize:50,nextBefore:start?String(start):null,nextAfter:String(end-1)});});vi.stubGlobal("fetch",request);
 const result=await fetchLoadedMessageRange("grown-token","conversation",rows.slice(0,50) as never);
 expect(result.items).toHaveLength(200);expect(result.items[0]?.texto).toBe("CONFIRMED");expect(request).toHaveBeenCalledTimes(4);
});

it("splits media signing into authorized batches of at most200 IDs",async()=>{
 const {fetchMessageMediaUrls}=await import("./conversations-api");
 const ids=Array.from({length:205},(_,n)=>`synthetic-${n}`);
 const request=vi.fn(async(input:RequestInfo | URL)=>{const batch=new URL(String(input)).searchParams.get("ids")!.split(",");expect(batch.length).toBeLessThanOrEqual(200);return Response.json({urls:Object.fromEntries(batch.map(id=>[id,`https://example.test/${id}`]))});});vi.stubGlobal("fetch",request);
 const urls=await fetchMessageMediaUrls("media-token","conversation",ids);expect(Object.keys(urls)).toHaveLength(205);expect(request).toHaveBeenCalledTimes(2);
});

it("stops media batches when the caller cancels during the first request",async()=>{
 const {fetchMessageMediaUrls}=await import("./conversations-api");
 const controller=new AbortController();const ids=Array.from({length:205},(_,n)=>`synthetic-cancel-${n}`);
 const request=vi.fn(async()=>{controller.abort();return Response.json({urls:{}});});vi.stubGlobal("fetch",request);
 await expect(fetchMessageMediaUrls("cancel-media-token","conversation",ids,controller.signal)).rejects.toMatchObject({name:"AbortError"});expect(request).toHaveBeenCalledTimes(1);
});
it("does not continue media batches or use a compatibility fallback after denial",async()=>{
 const {fetchMessageMediaUrls}=await import("./conversations-api");const ids=Array.from({length:205},(_,n)=>`synthetic-denied-${n}`);
 const request=vi.fn(async()=>Response.json({detail:"Denied"},{status:403}));vi.stubGlobal("fetch",request);
 await expect(fetchMessageMediaUrls("denied-media-token","conversation",ids)).rejects.toMatchObject({status:403});expect(request).toHaveBeenCalledTimes(1);
});
