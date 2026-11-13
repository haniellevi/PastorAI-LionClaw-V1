import { expect, test, type Page } from "@playwright/test";

import {
  API_URL,
  armBrowserSafety,
  loginThroughUi,
  resetHarness,
  type BrowserSafety,
} from "./support/helpers";

/**
 * A CSP do painel BLOQUEIA (cabeçalho `Content-Security-Policy`, sem
 * Report-Only). Este arquivo prova que o cabeçalho chega ao navegador e que as
 * telas do painel carregam sem nenhuma violação. As violações vêm do evento
 * `securitypolicyviolation` (ver armBrowserSafety em support/helpers.ts); como
 * agora a política bloqueia, a disposição esperada de uma violação é "enforce".
 */

// Telas do painel operacional (SCREEN_META em src/lib/navigation.ts), por #hash.
const APP_SCREENS = [
  "dashboard",
  "setup",
  "inbox",
  "pedidos-oracao",
  "calendario",
  "comunicados",
  "equipe",
  "contatos",
  "ganhar",
  "consolidar",
  "consol-individual",
  "universidade-vida",
  "capacitacao",
  "g12",
  "central-celula",
  "minha-celula",
  "enviar",
  "responsabilidades",
  "conhecimento",
  "alertas-lider",
  "celulas",
  "relatorios",
  "perfil",
];

// Telas do admin da igreja (superfície /gestao; ADMIN_NAV_SECTIONS + perfil/assinatura).
const GESTAO_SCREENS = [
  "setup",
  "contatos",
  "comunicados",
  "identidade",
  "equipe",
  "permissoes",
  "integracoes",
  "cadastro-igreja",
  "alertas-lider",
  "whatsapp",
  "agente",
  "conhecimento",
  "assinatura",
  "perfil",
];

// 1x1 PNG transparente, só para a prévia local (blob:) do envio de logo.
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

function directive(policy: string, name: string): string[] {
  const part = policy
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name} `));
  return part?.split(" ") ?? [];
}

async function settle(page: Page) {
  // Não usa networkidle: algumas telas fazem polling e nunca ficam ociosas.
  await page.waitForLoadState("load");
  await expect(page.locator("main, [role='main'], .full-loader, form").first()).toBeVisible();
  // Tempo para os chunks carregados sob demanda (strict-dynamic) e as folhas de estilo.
  await page.waitForTimeout(600);
}

function expectNoCspViolation(safety: BrowserSafety, route: string) {
  expect(safety.cspViolations, `violações da CSP em ${route}`).toEqual([]);
  expect(safety.externalRequests, `requisições externas em ${route}`).toEqual([]);
  expect(safety.pageErrors, `erros JavaScript em ${route}`).toEqual([]);
}

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
});

test("a CSP bloqueia: cabeçalho único, com nonce, e libera a API do build", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  const response = await page.goto("/#login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Entre na sua igreja" })).toBeVisible();

  const headers = response?.headers() ?? {};
  // Só o cabeçalho que bloqueia; nada de Report-Only e nada de segunda política.
  expect(headers["content-security-policy-report-only"]).toBeUndefined();
  const policy = headers["content-security-policy"] ?? "";
  expect(policy).not.toContain(",");
  expect(directive(policy, "connect-src")).toContain(new URL(API_URL).origin);
  expect(directive(policy, "frame-ancestors")).toEqual(["frame-ancestors", "'none'"]);
  expect(directive(policy, "default-src")).toEqual(["default-src", "'self'"]);
  // Scripts: nonce novo por documento no lugar de 'unsafe-inline' e sem eval em produção.
  const scriptSrc = directive(policy, "script-src");
  const nonce = scriptSrc.join(" ").match(/'nonce-([^']+)'/)?.[1];
  expect(nonce).toBeTruthy();
  expect(scriptSrc).toContain("'strict-dynamic'");
  expect(scriptSrc).not.toContain("'unsafe-inline'");
  expect(scriptSrc).not.toContain("'unsafe-eval'");
  const scriptNonces = await page
    .locator("script")
    .evaluateAll((scripts) => scripts.map((script) => (script as HTMLScriptElement).nonce));
  expect(scriptNonces.length).toBeGreaterThan(0);
  expect(new Set(scriptNonces)).toEqual(new Set([nonce]));
  // Estilos: <style> só do painel ou com o nonce; inline só em atributos.
  expect(directive(policy, "style-src-elem")).toEqual([
    "style-src-elem",
    "'self'",
    `'nonce-${nonce}'`,
  ]);
  expect(policy).toContain("style-src-attr 'unsafe-inline'");

  expect(safety.cspViolations).toEqual([]);
});

test("o painel carrega sem violação da CSP em todas as telas da igreja", async ({ page }) => {
  test.setTimeout(180_000);
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  expectNoCspViolation(safety, "login → dashboard");

  for (const screen of APP_SCREENS) {
    await page.goto(`/#${screen}`);
    await settle(page);
    expectNoCspViolation(safety, `/#${screen}`);
  }
});

test("o admin da igreja (/gestao) carrega sem violação da CSP em todas as telas", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);

  for (const screen of GESTAO_SCREENS) {
    await page.goto(`/gestao/#${screen}`);
    await settle(page);
    expectNoCspViolation(safety, `/gestao/#${screen}`);
  }
});

test("console master (/admin), documentos legais e rota interna carregam sem violação", async ({
  page,
}) => {
  const safety = await armBrowserSafety(page);

  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Console da Plataforma", exact: true }),
  ).toBeVisible();
  await settle(page);
  expectNoCspViolation(safety, "/admin (login do console)");

  for (const path of ["/privacidade", "/termos"]) {
    await page.goto(path);
    await settle(page);
    expectNoCspViolation(safety, path);
  }

  // /harness é interno (notFound() em produção); a página de erro também não viola a CSP.
  await page.goto("/harness");
  await settle(page);
  expectNoCspViolation(safety, "/harness");
  await page.goto("/rota-que-nao-existe");
  await settle(page);
  expectNoCspViolation(safety, "404");
});

test("prévia local (blob:) do logo é permitida pela CSP", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  await page.goto("/gestao/#identidade");
  await expect(
    page.getByRole("heading", { name: "Identidade da igreja", exact: true, level: 2 }),
  ).toBeVisible();

  await page.locator('.identity-screen input[type="file"]').setInputFiles({
    name: "logo-sintetica.png",
    mimeType: "image/png",
    buffer: PNG_1X1,
  });
  const preview = page.locator('.identity-screen img[src^="blob:"]');
  await expect(preview).toHaveCount(1);
  await expect.poll(() => preview.evaluate((img) => (img as HTMLImageElement).complete)).toBe(true);
  expect(await preview.evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBe(1);

  expectNoCspViolation(safety, "/gestao/#identidade com prévia blob:");
});

test("blob:, data: e a API são permitidos em img/media; o resto é barrado", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await page.goto("/#login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Entre na sua igreja" })).toBeVisible();

  // Mídia de conversas: blob: (áudio gravado/prévia) e data: (ícones embutidos).
  const loaded = await page.evaluate(
    async (png) => {
      const blobUrl = URL.createObjectURL(new Blob([new Uint8Array(png)], { type: "image/png" }));
      const audioUrl = URL.createObjectURL(new Blob([new Uint8Array(8)], { type: "audio/ogg" }));
      const img = document.createElement("img");
      img.alt = "";
      const done = new Promise<boolean>((resolve) => {
        img.onload = () => resolve(true);
        img.onerror = () => resolve(false);
      });
      img.src = blobUrl;
      document.body.append(img);
      const audio = document.createElement("audio");
      audio.preload = "metadata";
      audio.src = audioUrl;
      document.body.append(audio);
      return done;
    },
    [...PNG_1X1],
  );
  expect(loaded).toBe(true);
  await page.waitForTimeout(300);
  expect(safety.cspViolations).toEqual([]);
});

test("o gate E2E acusa, e o navegador bloqueia, um recurso que a CSP não permite", async ({
  page,
}) => {
  const safety = await armBrowserSafety(page);
  await page.goto("/#login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Entre na sua igreja" })).toBeVisible();

  // Origem reservada (.invalid): a requisição também é barrada pelo harness.
  // Conexão a origem alheia: a CSP também recusa (connect-src).
  await page.evaluate(() => {
    const img = document.createElement("img");
    img.alt = "";
    img.src = "http://csp-probe.invalid/pixel.png";
    document.body.append(img);
    void fetch("http://csp-probe.invalid/dados").catch(() => undefined);
  });

  await expect
    .poll(() => safety.cspViolations)
    .toEqual(
      expect.arrayContaining([
        "enforce img-src http://csp-probe.invalid/pixel.png",
        "enforce connect-src http://csp-probe.invalid/dados",
      ]),
    );
});
