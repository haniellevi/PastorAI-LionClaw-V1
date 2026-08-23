import { describe, expect, it } from "vitest";

import { GET as activate } from "./ativar/[token]/route";
import { GET as resetPassword } from "./redefinir-senha/[token]/route";

const TOKEN = "header.payload.signature";

async function call(
  handler: typeof activate,
  path: "ativar" | "redefinir-senha",
) {
  return handler(
    new Request(`https://app.igreja12.com.br/${path}/${TOKEN}?tracker=1`),
    { params: Promise.resolve({ token: TOKEN }) },
  );
}

describe("rotas de entrada dos e-mails de autenticação", () => {
  it.each([
    ["ativar", activate, `https://app.igreja12.com.br/#ativar/${TOKEN}`],
    [
      "redefinir-senha",
      resetPassword,
      `https://app.igreja12.com.br/#redefinir-senha/${TOKEN}`,
    ],
  ] as const)("redireciona %s no próprio domínio", async (path, handler, location) => {
    const response = await call(handler, path);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(location);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    expect(response.headers.get("x-robots-tag")).toBe("noindex, nofollow");
  });
});
