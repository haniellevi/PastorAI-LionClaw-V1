import { describe, expect, it } from "vitest";

import { resolveApiBase } from "./api-base";

describe("resolveApiBase", () => {
  it("usa o endereço configurado, sem barra final", () => {
    expect(resolveApiBase("https://api.example.test/", "production")).toBe(
      "https://api.example.test",
    );
  });

  it("falha no build de produção sem o endereço da API", () => {
    expect(() => resolveApiBase(undefined, "production")).toThrow(
      "NEXT_PUBLIC_API_URL",
    );
    expect(() => resolveApiBase("   ", "production")).toThrow(
      "NEXT_PUBLIC_API_URL",
    );
  });

  it("usa a API local em desenvolvimento e testes", () => {
    expect(resolveApiBase(undefined, "development")).toBe("http://localhost:8000");
    expect(resolveApiBase(undefined, "test")).toBe("http://localhost:8000");
  });
});
