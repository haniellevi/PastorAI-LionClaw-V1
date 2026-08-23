import { describe, expect, it } from "vitest";

import {
  buildPublicAuthRedirectUrl,
  isPublicAuthFlowRoute,
  PUBLIC_AUTH_RESPONSE_HEADERS,
  resolveRootSurface,
} from "./public-auth-flow";

describe("fluxos públicos de ativação e recuperação", () => {
  it.each([
    "ativar",
    "ativar/header.payload.signature",
    "redefinir-senha",
    "redefinir-senha/header.payload.signature",
  ])("reconhece %s como fluxo público", (route) => {
    expect(isPublicAuthFlowRoute(route)).toBe(true);
  });

  it.each(["", "login", "dashboard", "central-celula"])(
    "não trata %s como fluxo público",
    (route) => {
      expect(isPublicAuthFlowRoute(route)).toBe(false);
    },
  );

  it("prioriza ativação sobre uma sessão autenticada de outro tenant", () => {
    expect(
      resolveRootSurface("authenticated", "ativar/header.payload.signature"),
    ).toBe("login");
    expect(resolveRootSurface("authenticated", "dashboard")).toBe("app");
  });

  it("converte o caminho em hash somente no domínio próprio", () => {
    const destination = buildPublicAuthRedirectUrl(
      "https://app.igreja12.com.br/ativar/header.payload.signature?tracker=1",
      "ativar",
      "header.payload.signature",
    );

    expect(destination.href).toBe(
      "https://app.igreja12.com.br/#ativar/header.payload.signature",
    );
  });

  it("protege a resposta contra cache, referer e indexação", () => {
    expect(PUBLIC_AUTH_RESPONSE_HEADERS).toEqual({
      "Cache-Control": "no-store",
      "Referrer-Policy": "no-referrer",
      "X-Robots-Tag": "noindex, nofollow",
    });
  });
});
