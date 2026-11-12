import { expect, test } from "@playwright/test";

import { API_URL, armBrowserSafety, expectCleanBrowser, resetHarness } from "./support/helpers";

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
});

test("CSP em modo de teste chega ao navegador e libera a API do build", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  const response = await page.goto("/#login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Entre na sua igreja" })).toBeVisible();

  const reportOnly = response?.headers()["content-security-policy-report-only"] ?? "";
  const connectSrc = reportOnly
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("connect-src "));
  expect(connectSrc?.split(" ")).toContain(new URL(API_URL).origin);
  // Modo de teste: o cabeçalho que bloqueia continua só com frame-ancestors.
  expect(response?.headers()["content-security-policy"]).toBe("frame-ancestors 'none'");

  expectCleanBrowser(safety);
});

test("o gate E2E acusa um recurso que a CSP não permite", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await page.goto("/#login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Entre na sua igreja" })).toBeVisible();

  // Origem reservada (.invalid): a requisição também é barrada pelo harness.
  await page.evaluate(() => {
    const img = document.createElement("img");
    img.alt = "";
    img.src = "http://csp-probe.invalid/pixel.png";
    document.body.append(img);
  });

  await expect
    .poll(() => safety.cspViolations)
    .toContainEqual("report img-src http://csp-probe.invalid/pixel.png");
  // Report-Only não bloqueia: quem barrou a requisição foi o harness.
  expect(safety.externalRequests).toEqual(["http://csp-probe.invalid/pixel.png"]);
});
