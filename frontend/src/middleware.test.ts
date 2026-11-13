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

describe("middleware — CSP com nonce", () => {
  const HEADER = "content-security-policy";

  function nonceOf(policy: string | null) {
    return policy?.match(/'nonce-([^']+)'/)?.[1];
  }

  it.each([
    ["app.igreja12.com.br", "/"],
    ["admin.igreja12.com.br", "/"],
    ["painel.igreja12.com.br", "/igrejas"],
    ["admin.igreja12.com.br", "/termos"],
  ])("entrega o mesmo nonce ao Next e ao navegador em %s%s", (host, pathname) => {
    const response = middleware(request(host, pathname));
    const toBrowser = response.headers.get(HEADER);
    const toNext = response.headers.get(`x-middleware-request-${HEADER}`);

    expect(nonceOf(toBrowser)).toBeTruthy();
    expect(toNext).toBe(toBrowser);
    expect(response.headers.get("x-middleware-override-headers")).toContain(HEADER);
    expect(toBrowser).toContain("'strict-dynamic'");
    expect(toBrowser).not.toContain("'unsafe-inline' 'strict-dynamic'");
  });

  it("bloqueia (não usa Report-Only) e traz frame-ancestors na própria política", () => {
    const response = middleware(request("app.igreja12.com.br", "/"));

    expect(response.headers.get("content-security-policy-report-only")).toBeNull();
    expect(response.headers.get(HEADER)).toContain("frame-ancestors 'none'");
  });

  it("gera um nonce novo a cada documento", () => {
    const first = nonceOf(middleware(request("app.igreja12.com.br", "/")).headers.get(HEADER));
    const second = nonceOf(middleware(request("app.igreja12.com.br", "/")).headers.get(HEADER));

    expect(first).not.toBe(second);
  });
});
