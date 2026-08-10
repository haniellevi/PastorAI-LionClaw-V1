import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

import {
  assertM09LoopbackUrl,
  resolveM09Urls,
} from "../../e2e/support/loopback-url.mjs";

const FRONTEND_ROOT = fileURLToPath(new URL("../..", import.meta.url));

describe("guard loopback do laboratorio M09", () => {
  test.each([
    ["localhost", "http://localhost:3109", "http://localhost:3109"],
    ["IPv4 loopback", "http://127.0.0.1:3109", "http://127.0.0.1:3109"],
    ["faixa IPv4 127/8", "http://127.42.0.9:65535", "http://127.42.0.9:65535"],
    ["IPv6 loopback", "http://[::1]:3109", "http://[::1]:3109"],
    ["porta HTTP padrao", "http://localhost", "http://localhost"],
    ["raiz explicita", "http://localhost:3109/", "http://localhost:3109"],
  ])("aceita %s", (_case, rawValue, expectedOrigin) => {
    expect(assertM09LoopbackUrl("M09_APP_URL", rawValue)).toMatchObject({
      origin: expectedOrigin,
    });
  });

  test.each([
    ["host publico", "http://example.com:3109"],
    ["IP privado", "http://192.168.1.10:3109"],
    ["wildcard", "http://0.0.0.0:3109"],
    ["sufixo em localhost", "http://localhost.evil:3109"],
    ["sufixo em IPv4", "http://127.0.0.1.evil:3109"],
    ["userinfo enganosa", "http://localhost@evil.example:3109"],
    ["HTTPS", "https://localhost:3109"],
    ["esquema nao HTTP", "ftp://localhost:3109"],
    ["URL invalida", "nao-e-uma-url"],
    ["credenciais", "http://user:password@localhost:3109"],
    ["porta zero", "http://localhost:0"],
    ["caminho", "http://localhost:3109/app"],
    ["query", "http://localhost:3109/?target=external"],
    ["fragmento", "http://localhost:3109/#external"],
    ["IPv6 nao loopback", "http://[::]:3109"],
    ["dot-segment simples", "http://localhost:3109/./"],
    ["dot-segment que volta a raiz", "http://localhost:3109/foo/.."],
    ["dot-segment percent-encoded", "http://localhost:3109/%2e/"],
    ["dot-segment encoded maiusculo", "http://localhost:3109/%2E%2E/"],
    ["dot-segment encoded aninhado", "http://localhost:3109/foo/%2e%2e/"],
    ["barra invertida", "http://localhost:3109\\foo"],
    ["userinfo vazio", "http://@localhost:3109"],
    ["tab no esquema", "ht\ttp://localhost:3109"],
    ["tab no hostname", "http://local\thost:3109"],
    ["controle C0", "http://local\u0001host:3109"],
    ["NUL", "\u0000http://localhost:3109"],
    ["DEL", "http://localhost:3109\u007f"],
    ["whitespace Unicode", "http://local\u00a0host:3109"],
    ["esquema nao canonico", "HTTP://localhost:3109"],
    ["hostname nao canonico", "http://LOCALHOST:3109"],
    ["IPv4 abreviado", "http://127.1:3109"],
    ["IPv4 com zeros", "http://127.000.000.001:3109"],
    ["IPv6 expandido", "http://[0:0:0:0:0:0:0:1]:3109"],
    ["porta com zeros", "http://localhost:03109"],
  ])("rejeita %s", (_case, rawValue) => {
    expect(() => assertM09LoopbackUrl("M09_APP_URL", rawValue)).toThrow(
      "[M09] M09_APP_URL invalida",
    );
  });

  test("valida as duas URLs e nao inclui o valor rejeitado no erro", () => {
    const unsafeApi = "http://token-secreto@api.example.test:8009";
    expect(() =>
      resolveM09Urls({
        M09_APP_URL: "http://127.0.0.1:3109",
        M09_API_URL: unsafeApi,
      }),
    ).toThrow("[M09] M09_API_URL invalida");

    try {
      resolveM09Urls({
        M09_APP_URL: "http://127.0.0.1:3109",
        M09_API_URL: unsafeApi,
      });
    } catch (error) {
      expect(String(error)).not.toContain(unsafeApi);
      expect(String(error)).not.toContain("token-secreto");
    }
  });

  test("erro de forma nao canonica nao reflete o valor bruto", () => {
    const rawValue = "http://localhost:3109/segredo/..";

    try {
      assertM09LoopbackUrl("M09_APP_URL", rawValue);
      throw new Error("a URL deveria ter sido rejeitada");
    } catch (error) {
      expect(String(error)).toContain("[M09] M09_APP_URL invalida");
      expect(String(error)).not.toContain(rawValue);
      expect(String(error)).not.toContain("segredo");
    }
  });

  test("build E2E falha antes de iniciar npm ou expor a URL externa", () => {
    const result = spawnSync(process.execPath, ["e2e/support/build-e2e.mjs"], {
      cwd: FRONTEND_ROOT,
      encoding: "utf8",
      env: {
        ...process.env,
        M09_APP_URL: "http://127.0.0.1:3109",
        M09_API_URL: "http://api-externa.example.test:8009",
      },
      timeout: 10_000,
    });
    const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;

    expect(result.status).toBe(1);
    expect(output).toContain("[M09] M09_API_URL invalida");
    expect(output).not.toContain("api-externa.example.test");
    expect(output).not.toContain("next build");
  });

  test("build E2E rejeita forma nao canonica antes de iniciar npm", () => {
    const rawValue = "http://127.0.0.1:8009/api/..";
    const result = spawnSync(process.execPath, ["e2e/support/build-e2e.mjs"], {
      cwd: FRONTEND_ROOT,
      encoding: "utf8",
      env: {
        ...process.env,
        M09_APP_URL: "http://127.0.0.1:3109",
        M09_API_URL: rawValue,
      },
      timeout: 10_000,
    });
    const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;

    expect(result.status).toBe(1);
    expect(output).toContain("[M09] M09_API_URL invalida");
    expect(output).not.toContain(rawValue);
    expect(output).not.toContain("next build");
  });

  test("config Playwright falha antes de iniciar os webServers", () => {
    const playwrightCli = fileURLToPath(
      new URL("../../node_modules/@playwright/test/cli.js", import.meta.url),
    );
    const result = spawnSync(process.execPath, [playwrightCli, "test", "--list"], {
      cwd: FRONTEND_ROOT,
      encoding: "utf8",
      env: {
        ...process.env,
        M09_APP_URL: "http://localhost.evil:3109",
        M09_API_URL: "http://127.0.0.1:8009",
      },
      timeout: 10_000,
    });
    const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;

    expect(result.status).toBe(1);
    expect(output).toContain("[M09] M09_APP_URL invalida");
    expect(output).not.toContain("localhost.evil");
    expect(output).not.toContain("M09 mock API");
    expect(output).not.toContain("Next production local");
  });

  test("config Playwright rejeita path normalizado antes dos webServers", () => {
    const rawValue = "http://localhost:3109/./";
    const playwrightCli = fileURLToPath(
      new URL("../../node_modules/@playwright/test/cli.js", import.meta.url),
    );
    const result = spawnSync(process.execPath, [playwrightCli, "test", "--list"], {
      cwd: FRONTEND_ROOT,
      encoding: "utf8",
      env: {
        ...process.env,
        M09_APP_URL: rawValue,
        M09_API_URL: "http://127.0.0.1:8009",
      },
      timeout: 10_000,
    });
    const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;

    expect(result.status).toBe(1);
    expect(output).toContain("[M09] M09_APP_URL invalida");
    expect(output).not.toContain(rawValue);
    expect(output).not.toContain("M09 mock API");
    expect(output).not.toContain("Next production local");
  });
});
