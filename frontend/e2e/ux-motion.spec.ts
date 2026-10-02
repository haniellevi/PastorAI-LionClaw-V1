import { expect, test } from "@playwright/test";

import { armBrowserSafety, expectCleanBrowser } from "./support/helpers";

test("a decoração acompanha mouse sem mover campos e estabiliza durante digitação", async ({ page }, testInfo) => {
  const safety = await armBrowserSafety(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const email = page.getByLabel("E-mail", { exact: true });
  await expect(email).toBeVisible();
  const art = page.locator(".mineral-backdrop");
  const before = await email.boundingBox();
  await page.mouse.move(20, 20);
  await expect.poll(() => art.evaluate((el) => parseFloat((el as HTMLElement).style.getPropertyValue("--mineral-x")))).toBeLessThan(0);
  const offset = await art.evaluate((el) => ["--mineral-x", "--mineral-y"].map((key) => parseFloat((el as HTMLElement).style.getPropertyValue(key))));
  expect(offset.every((value) => Math.abs(value) <= 6)).toBeTruthy();
  expect(await email.boundingBox()).toEqual(before);
  await email.focus();
  await email.fill("rascunho.visual@example.test");
  await page.mouse.move(1300, 750);
  await expect.poll(() => art.evaluate((el) => (el as HTMLElement).style.getPropertyValue("--mineral-x"))).toBe("0px");
  await expect(email).toBeFocused();
  await expect(email).toHaveValue("rascunho.visual@example.test");
  expect(await art.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
  await page.screenshot({ path: testInfo.outputPath("acesso-v3-desktop.png"), fullPage: true });
  expectCleanBrowser(safety);
});

test("reduced motion e toque mantêm arte estática e formulário utilizável", async ({ browser }, testInfo) => {
  for (const mode of ["reduce", "touch"] as const) {
    const context = await browser.newContext({
      viewport: mode === "touch" ? { width: 390, height: 844 } : { width: 1440, height: 900 },
      hasTouch: mode === "touch",
      isMobile: mode === "touch",
      reducedMotion: mode === "reduce" ? "reduce" : "no-preference",
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    const safety = await armBrowserSafety(page);
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Entrar", exact: true })).toBeVisible();
    await page.mouse.move(30, 30);
    await expect(page.locator(".mineral-backdrop")).not.toHaveAttribute("data-tracking");
    expect(await page.locator(".mineral-facet").first().evaluate((el) => getComputedStyle(el).transform)).toBe("none");
    const input = page.getByLabel("E-mail", { exact: true });
    await input.fill("teste.visual@example.test");
    await expect(input).toHaveValue("teste.visual@example.test");
    const bounds = await input.boundingBox();
    expect(bounds!.height).toBeGreaterThanOrEqual(48);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`acesso-v3-${mode}.png`), fullPage: true });
    expectCleanBrowser(safety);
    await context.close();
  }
});

test("apoio revela uma vez com scroll nativo, sem esconder conteúdo essencial", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await page.setViewportSize({ width: 390, height: 500 });
  await page.goto("/");
  await expect(page.getByLabel("E-mail", { exact: true })).toBeVisible();
  const support = page.locator(".support-reveal");
  expect(await support.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
  await page.evaluate(() => {
    const el = document.querySelector<HTMLElement>(".support-reveal")!;
    el.dataset.animationCount = "0";
    el.addEventListener("animationstart", () => { el.dataset.animationCount = String(Number(el.dataset.animationCount) + 1); });
  });
  await page.mouse.wheel(0, 700);
  await expect(page.getByRole("link", { name: "Privacidade", exact: true })).toBeVisible();
  await expect(support).toHaveAttribute("data-revealed", "true");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await page.mouse.wheel(0, -700);
  await page.mouse.wheel(0, 700);
  await expect(support).toHaveAttribute("data-animation-count", "1");
  expectCleanBrowser(safety);
});
