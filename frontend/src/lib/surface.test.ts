import { afterEach, describe, expect, it, vi } from "vitest";

import { adminSurfaceRouteHref } from "./surface";

function locationAt(protocol: string, host: string) {
  vi.stubGlobal("window", { location: { protocol, host } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("adminSurfaceRouteHref", () => {
  it("troca app pelo subdomínio admin e preserva o deep-link em produção", () => {
    locationAt("https:", "app.igreja12.com.br");

    expect(adminSurfaceRouteHref("contatos/p1")).toBe(
      "https://admin.igreja12.com.br/#contatos/p1",
    );
  });

  it.each([
    ["http:", "localhost:3002"],
    ["https:", "pastorai-frontend-preview.vercel.app"],
  ])("usa /gestao no host sem subdomínio app (%s//%s)", (protocol, host) => {
    locationAt(protocol, host);

    expect(adminSurfaceRouteHref("#contatos/p1")).toBe(
      "/gestao#contatos/p1",
    );
  });

  it("mantém o fallback de servidor", () => {
    expect(adminSurfaceRouteHref("contatos/p1")).toBe(
      "/gestao#contatos/p1",
    );
  });
});
