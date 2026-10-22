import { expect, test } from "@playwright/test";
import {
  API_URL,
  E2E_USER,
  armBrowserSafety,
  expectCleanBrowser,
  harnessRequests,
  loginThroughUi,
  resetHarness,
} from "./support/helpers";

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
});

test("admin vê contagens sintéticas da memória privada em Hoje", async ({ page, request }) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);

  const indicator = page.getByRole("region", { name: "Memória privada" });
  await expect(indicator).toContainText("2 pedidos de exclusão pendentes");
  await expect(indicator).toContainText("1 atendidos e 0 recusados");

  const requests = await harnessRequests(request);
  expect(requests.some((entry) =>
    entry.method === "GET" && entry.path === "/operations/private-memory" && entry.status === 200,
  )).toBe(true);
  expectCleanBrowser(safety);
});

test("pastor sem papel admin não vê o indicador nem consulta contagens privadas", async ({ page, request }) => {
  const safety = await armBrowserSafety(page);
  await page.route(`${API_URL}/auth/login`, async (route) => {
    const response = await route.fetch();
    const profile = await response.json() as Record<string, unknown>;
    await route.fulfill({ response, json: { ...profile, roles: ["pastor"], isOwner: false } });
  });

  await page.goto("/#login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Entre na sua igreja" })).toBeVisible();
  await page.getByLabel("E-mail").fill(E2E_USER.email);
  await page.getByRole("textbox", { name: "Senha", exact: true }).fill(E2E_USER.password);
  await page.getByRole("button", { name: "Entrar" }).click();

  await expect(page.locator(".screen.dashboard")).toBeVisible();
  await expect(page.getByRole("region", { name: "Memória privada" })).toHaveCount(0);
  const requests = await harnessRequests(request);
  expect(requests.some((entry) => entry.path === "/operations/private-memory")).toBe(false);
  expectCleanBrowser(safety);
});
