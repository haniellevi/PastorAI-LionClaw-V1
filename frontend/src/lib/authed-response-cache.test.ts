import { describe, expect, it } from "vitest";

import { AuthedResponseCache } from "./authed-response-cache";

describe("AuthedResponseCache", () => {
  it("reaproveita uma leitura sem compartilhar o body consumido", async () => {
    let now = 1_000;
    const cache = new AuthedResponseCache(4, () => now);
    cache.set("token-a", "/events", Response.json({ value: 12 }), 5_000);

    const first = cache.get("token-a", "/events");
    const second = cache.get("token-a", "/events");

    expect(await first?.json()).toEqual({ value: 12 });
    expect(await second?.json()).toEqual({ value: 12 });
    expect(cache.size).toBe(1);

    now = 6_001;
    expect(cache.get("token-a", "/events")).toBeNull();
  });

  it("isola tokens e invalida somente os prefixos pedidos", () => {
    const cache = new AuthedResponseCache();
    cache.set("token-a", "/events?page=1", Response.json([]), 60_000);
    cache.set("token-a", "/cells?page=1", Response.json([]), 60_000);
    cache.set("token-b", "/events?page=1", Response.json([]), 60_000);

    cache.clear("token-a", ["/events"]);

    expect(cache.get("token-a", "/events?page=1")).toBeNull();
    expect(cache.get("token-a", "/cells?page=1")).not.toBeNull();
    expect(cache.get("token-b", "/events?page=1")).not.toBeNull();
  });

  it("não armazena respostas de erro e respeita o limite LRU", () => {
    const cache = new AuthedResponseCache(2);
    cache.set("token", "/erro", new Response(null, { status: 500 }), 60_000);
    cache.set("token", "/a", Response.json({}), 60_000);
    cache.set("token", "/b", Response.json({}), 60_000);
    cache.get("token", "/a");
    cache.set("token", "/c", Response.json({}), 60_000);

    expect(cache.get("token", "/erro")).toBeNull();
    expect(cache.get("token", "/a")).not.toBeNull();
    expect(cache.get("token", "/b")).toBeNull();
    expect(cache.get("token", "/c")).not.toBeNull();
  });
});
