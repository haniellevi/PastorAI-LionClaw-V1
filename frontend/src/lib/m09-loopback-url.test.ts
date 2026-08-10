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
});
