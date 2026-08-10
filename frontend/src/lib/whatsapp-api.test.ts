import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchConnection } from "./whatsapp-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchConnection", () => {
  it("propaga o AbortSignal para o GET da conexão", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ numero: null, status: "online", ultimaSync: null }),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const controller = new AbortController();

    await fetchConnection("token", controller.signal);

    const call = fetchSpy.mock.calls.at(0);
    if (!call) throw new Error("GET da conexão não foi chamado");
    expect(call[1]).toMatchObject({ signal: controller.signal });
  });
});
