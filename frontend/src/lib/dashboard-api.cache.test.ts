import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authedFetch, clearAuthedResponseCache } from "./dashboard-api";

describe("authedFetch navigation cache", () => {
  beforeEach(() => {
    vi.stubEnv("NODE_ENV", "production");
    clearAuthedResponseCache();
  });

  afterEach(() => {
    clearAuthedResponseCache();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
  });

  it("deduplica leituras simultâneas e entrega bodies independentes", async () => {
    const fetchMock = vi.fn(async () => Response.json({ items: ["agenda"] }));
    vi.stubGlobal("fetch", fetchMock);

    const path = "/events?page=1&pageSize=200";
    const [first, second] = await Promise.all([
      authedFetch("token-a", path),
      authedFetch("token-a", path),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await first.json()).toEqual({ items: ["agenda"] });
    expect(await second.json()).toEqual({ items: ["agenda"] });

    const cached = await authedFetch("token-a", path);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await cached.json()).toEqual({ items: ["agenda"] });
  });

  it("não cruza sessões e permite refresh explícito por prefixo", async () => {
    const fetchMock = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const path = "/cells?page=1&pageSize=100";

    await authedFetch("token-a", path);
    await authedFetch("token-b", path);
    await authedFetch("token-a", path);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    clearAuthedResponseCache("token-a", ["/cells?"]);
    await authedFetch("token-a", path);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("não deixa uma leitura invalidada sobrescrever o cache mais novo", async () => {
    let resolveOld!: (response: Response) => void;
    const oldDeferred = new Promise<Response>((resolve) => {
      resolveOld = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => oldDeferred)
      .mockResolvedValueOnce(Response.json({ version: "new" }));
    vi.stubGlobal("fetch", fetchMock);

    const token = "token-a";
    const path = "/dashboard/overview";
    const oldPending = authedFetch(token, path);

    clearAuthedResponseCache(token, ["/dashboard/overview"]);
    const fresh = await authedFetch(token, path);
    expect(await fresh.json()).toEqual({ version: "new" });

    resolveOld(Response.json({ version: "old" }));
    const stale = await oldPending;
    expect(await stale.json()).toEqual({ version: "old" });

    const cached = await authedFetch(token, path);
    expect(await cached.json()).toEqual({ version: "new" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("não guarda endpoints fora da lista de prefetch", async () => {
    const fetchMock = vi.fn(async () => Response.json({ status: "online" }));
    vi.stubGlobal("fetch", fetchMock);

    await authedFetch("token-a", "/whatsapp/connection");
    await authedFetch("token-a", "/whatsapp/connection");

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});


describe("authedFetch bounded freshness", () => {
  afterEach(() => { clearAuthedResponseCache(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); });

  it("cancela só o consumidor sem abortar outra leitura compartilhada", async () => {
    vi.stubEnv("NODE_ENV", "production");
    let resolve!: (response: Response) => void;
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => new Promise<Response>((done) => { resolve = done; }));
    vi.stubGlobal("fetch", fetchMock);
    const firstController = new AbortController();
    const first = authedFetch("actor", "/dashboard/overview", { signal: firstController.signal });
    const second = authedFetch("actor", "/dashboard/overview");
    const cancelled = expect(first).rejects.toMatchObject({ name: "AbortError" });
    firstController.abort();
    await cancelled;
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(false);
    resolve(Response.json({ version: "shared" }));
    expect(await (await second).json()).toEqual({ version: "shared" });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("invalida após commit uma leitura iniciada durante a escrita", async () => {
    vi.stubEnv("NODE_ENV", "production");
    let commit!: (response: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((done) => { commit = done; }))
      .mockResolvedValueOnce(Response.json({ version: "before-commit" }))
      .mockResolvedValueOnce(Response.json({ version: "committed" }));
    vi.stubGlobal("fetch", fetchMock);
    const mutation = authedFetch("actor", "/contacts/one", { method: "PUT", body: "{}" });
    await authedFetch("actor", "/dashboard/overview");
    commit(Response.json({ saved: true }));
    await mutation;
    const fresh = await authedFetch("actor", "/dashboard/overview");
    expect(await fresh.json()).toEqual({ version: "committed" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("encerra request geral pendente com deadline, mesmo se fetch ignorar abort", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    const pending = authedFetch("actor", "/roles/permissions");
    const failed = expect(pending).rejects.toMatchObject({ status: 408 });
    await vi.advanceTimersByTimeAsync(20_000);
    await failed;
  });
});
