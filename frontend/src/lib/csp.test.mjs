import { describe, expect, it } from "vitest";

import { apiOrigin, buildContentSecurityPolicy, generateNonce } from "./csp.mjs";

function directives(policy) {
  return Object.fromEntries(
    policy.split("; ").map((part) => {
      const [name, ...sources] = part.split(" ");
      return [name, sources];
    }),
  );
}

describe("buildContentSecurityPolicy", () => {
  it("só libera dados para o próprio painel e para a origem da API", () => {
    const csp = directives(buildContentSecurityPolicy({ apiUrl: "https://api.example.test/v1/" }));

    expect(csp["connect-src"]).toEqual(["'self'", "https://api.example.test"]);
    expect(csp["default-src"]).toEqual(["'self'"]);
  });

  it("fecha plugins, frames, base e envio de formulários para fora", () => {
    const csp = directives(buildContentSecurityPolicy({ apiUrl: "https://api.example.test" }));

    expect(csp["object-src"]).toEqual(["'none'"]);
    expect(csp["frame-src"]).toEqual(["'none'"]);
    expect(csp["frame-ancestors"]).toEqual(["'none'"]);
    expect(csp["base-uri"]).toEqual(["'self'"]);
    expect(csp["form-action"]).toEqual(["'self'"]);
  });

  it("aceita eval só no modo de desenvolvimento", () => {
    const prod = directives(buildContentSecurityPolicy({ apiUrl: "https://api.example.test" }));
    const dev = directives(
      buildContentSecurityPolicy({ apiUrl: "https://api.example.test", dev: true }),
    );

    expect(prod["script-src"]).not.toContain("'unsafe-eval'");
    expect(dev["script-src"]).toContain("'unsafe-eval'");
  });

  it("deixa logo e mídia do armazenamento https e das prévias locais", () => {
    const csp = directives(buildContentSecurityPolicy({ apiUrl: "http://127.0.0.1:8100" }));

    expect(csp["img-src"]).toEqual(["'self'", "data:", "blob:", "https:", "http://127.0.0.1:8100"]);
    expect(csp["media-src"]).toEqual(["'self'", "blob:", "https:", "http://127.0.0.1:8100"]);
  });
});

describe("nonce dos scripts", () => {
  it("troca 'unsafe-inline' pelo nonce e por 'strict-dynamic'", () => {
    const csp = directives(
      buildContentSecurityPolicy({ apiUrl: "https://api.example.test", nonce: "abc123+/=" }),
    );

    expect(csp["script-src"]).toEqual(["'self'", "'nonce-abc123+/='", "'strict-dynamic'"]);
  });

  it("cai no modo antigo sem nonce ou com nonce inválido", () => {
    for (const nonce of [undefined, "", "a b", "x';script-src *"]) {
      const csp = directives(
        buildContentSecurityPolicy({ apiUrl: "https://api.example.test", nonce }),
      );
      expect(csp["script-src"]).toEqual(["'self'", "'unsafe-inline'"]);
    }
  });

  it("aceita <style> só do painel ou com o nonce e deixa inline só nos atributos", () => {
    const csp = directives(
      buildContentSecurityPolicy({ apiUrl: "https://api.example.test", nonce: "abc123+/=" }),
    );

    expect(csp["style-src-elem"]).toEqual(["'self'", "'nonce-abc123+/='"]);
    expect(csp["style-src-attr"]).toEqual(["'unsafe-inline'"]);
    // Reserva para navegadores sem CSP nível 3.
    expect(csp["style-src"]).toEqual(["'self'", "'unsafe-inline'"]);
  });

  it("sem nonce, <style> volta a aceitar inline em vez de quebrar o painel", () => {
    const csp = directives(buildContentSecurityPolicy({ apiUrl: "https://api.example.test" }));

    expect(csp["style-src-elem"]).toEqual(["'self'", "'unsafe-inline'"]);
  });

  it("gera nonces de 128 bits, válidos e diferentes a cada chamada", () => {
    const nonces = new Set(Array.from({ length: 50 }, generateNonce));

    expect(nonces.size).toBe(50);
    for (const nonce of nonces) {
      expect(nonce).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    }
  });
});

describe("apiOrigin", () => {
  it("usa a API local quando a variável não existe, como o painel", () => {
    expect(apiOrigin(undefined)).toBe("http://localhost:8000");
    expect(apiOrigin("  ")).toBe("http://localhost:8000");
  });

  it("ignora um endereço inválido em vez de quebrar a política", () => {
    expect(apiOrigin("não-é-url")).toBeNull();
    expect(directives(buildContentSecurityPolicy({ apiUrl: "não-é-url" }))["connect-src"]).toEqual([
      "'self'",
    ]);
  });
});
