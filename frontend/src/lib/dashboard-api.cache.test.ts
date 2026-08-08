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

  it("não guarda endpoints fora da lista de prefetch", async () => {
    const fetchMock = vi.fn(async () => Response.json({ status: "online" }));
    vi.stubGlobal("fetch", fetchMock);

    await authedFetch("token-a", "/whatsapp/connection");
    await authedFetch("token-a", "/whatsapp/connection");

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
