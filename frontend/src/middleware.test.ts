import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "./middleware";

function request(host: string, pathname: string) {
  return new NextRequest(`https://${host}${pathname}`, {
    headers: { host },
  });
}

describe("middleware — documentos legais públicos", () => {
  it.each([
    ["admin.igreja12.com.br", "/privacidade"],
    ["admin.igreja12.com.br", "/termos"],
    ["painel.igreja12.com.br", "/privacidade"],
    ["painel.igreja12.com.br", "/termos"],
  ])("não reescreve %s%s", (host, pathname) => {
    const response = middleware(request(host, pathname));

    expect(response.headers.get("x-middleware-rewrite")).toBeNull();
    expect(response.headers.get("location")).toBeNull();
  });

  it("mantém o roteamento administrativo fora das páginas legais", () => {
    const response = middleware(request("admin.igreja12.com.br", "/"));

    expect(response.headers.get("x-middleware-rewrite")).toBe(
      "https://admin.igreja12.com.br/gestao",
    );
  });
});
