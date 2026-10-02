import { expect, test } from "@playwright/test";

import {
  API_URL,
  armBrowserSafety,
  attachJson,
  expectCleanBrowser,
  loginThroughUi,
  resetHarness,
} from "./support/helpers";

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
  const fixture = await request.post(`${API_URL}/__e2e/ux-inbox`);
  expect(fixture.ok()).toBeTruthy();
});

test("Hoje apresenta ação principal e permite descobrir as demais por teclado", async ({ page }, testInfo) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);

  const item = page.locator(".dh-item").first();
  await expect(item.getByRole("button", { name: /Conectar à célula/ })).toBeVisible();
  await expect(item.getByRole("button", { name: /Atribuir responsável/ })).toBeHidden();
  const more = item.locator("summary");
  await page.keyboard.press("Tab");
  await more.focus();
  await page.screenshot({ path: testInfo.outputPath("hoje-foco-teclado.png"), fullPage: true });
  await page.keyboard.press("Enter");
  await expect(item.getByRole("button", { name: /Atribuir responsável/ })).toBeVisible();
  await item.getByRole("button", { name: /Atribuir responsável/ }).click();
  await expect(page.getByRole("dialog", { name: "Atribuir responsável" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(item.getByRole("button", { name: /Atribuir responsável/ })).toBeFocused();
  await item.getByRole("button", { name: /Enviar mensagem/ }).click();
  await expect(page.getByRole("dialog", { name: "Mensagem interna (WhatsApp)" })).toBeVisible();
  await expect(page.getByLabel("Mensagem", { exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(item.getByRole("button", { name: /Enviar mensagem/ })).toBeFocused();

  await expect(page.locator(".dh-support-more")).not.toHaveAttribute("open");
  await page.locator(".dh-support-more > summary").click();
  await expect(page.getByRole("heading", { name: "Pendências por responsável" })).toBeVisible();
  const conversations = page.getByRole("link", { name: "Abrir conversas" });
  await conversations.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Conversas", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Assumir atendimento", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ver pessoa", exact: true })).toBeVisible();
  expectCleanBrowser(safety);
});

test("no celular o atendimento preserva busca e rascunho ao voltar à lista", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  await page.getByRole("link", { name: "Abrir conversas" }).click();
  await page.getByRole("searchbox", { name: "Buscar conversa" }).fill("Contato B");
  await page.locator(".conv").filter({ has: page.getByText("Contato B", { exact: true }) }).click();
  await expect(page.getByText("Responsável: você", { exact: true })).toBeVisible();
  const composer = page.locator('.thread-foot input[type="text"]');
  await composer.fill("Rascunho sintético preservado");
  await page.getByRole("button", { name: "Ver pessoa", exact: true }).click();
  await expect(page.locator(".conv-panel")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(composer).toHaveValue("Rascunho sintético preservado");
  await page.getByRole("button", { name: "Voltar para a lista de conversas" }).click();
  await expect(page.getByRole("searchbox", { name: "Buscar conversa" })).toHaveValue("Contato B");
  await page.locator(".conv").filter({ has: page.getByText("Contato B", { exact: true }) }).click();
  await expect(composer).toHaveValue("Rascunho sintético preservado");
  expectCleanBrowser(safety);
});

test("contraste renderizado e composição não perdem controles nas quatro larguras", async ({ page }, testInfo) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  const measurements = [];
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/#dashboard");
    await expect(page.locator(".dh-item").first()).toBeVisible();
    const contrast = await page.locator(".dh-item-meta").first().evaluate((el) => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const ctx = canvas.getContext("2d")!;
      const luminance = (color: string) => {
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, 1, 1);
        const rgb = ctx.getImageData(0, 0, 1, 1).data;
        const channel = (index: number) => {
          const s = rgb[index]! / 255;
          return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
        };
        return channel(0) * 0.2126 + channel(1) * 0.7152 + channel(2) * 0.0722;
      };
      const fg = getComputedStyle(el).color;
      const bg = getComputedStyle(el.closest(".dh-workboard")!).backgroundColor;
      const ratio = (first: string, second: string) => {
        const a = luminance(first);
        const b = luminance(second);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      };
      const root = getComputedStyle(document.documentElement);
      const lead = document.querySelector<HTMLElement>(".dh-lead")!;
      const hero = document.querySelector<HTMLElement>(".dh-hero")!;
      const selected = document.querySelector<HTMLElement>(".sidebar .nav-item.active");
      return {
        fg, bg, ratio: ratio(fg, bg), fontSize: getComputedStyle(el).fontSize,
        actionRatio: ratio(root.getPropertyValue("--text-on-action"), root.getPropertyValue("--action-primary")),
        focusRatio: ratio(root.getPropertyValue("--focus-ring"), bg),
        heroLeadRatio: ratio(getComputedStyle(lead).color, getComputedStyle(hero).backgroundColor),
        selectedNavRatio: selected ? ratio(getComputedStyle(selected).color, getComputedStyle(selected).backgroundColor) : null,
        heroHeight: hero.getBoundingClientRect().height,
        heroTitleSize: getComputedStyle(hero.querySelector(".dh-title")!).fontSize,
      };
    });
    expect(contrast.ratio).toBeGreaterThanOrEqual(4.5);
    expect(contrast.actionRatio).toBeGreaterThanOrEqual(4.5);
    expect(contrast.focusRatio).toBeGreaterThanOrEqual(3);
    expect(contrast.heroLeadRatio).toBeGreaterThanOrEqual(4.5);
    if (contrast.selectedNavRatio !== null) expect(contrast.selectedNavRatio).toBeGreaterThanOrEqual(4.5);
    expect(contrast.fontSize).toBe("14px");
    expect(contrast.heroTitleSize).toBe(width <= 860 ? "28px" : "32px");
    if (width >= 1024) expect(contrast.heroHeight).toBeLessThanOrEqual(160);
    const activeFilter = page.locator(".dh-filter-btn.active").first();
    await activeFilter.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(activeFilter).toBeFocused();
    const outline = await activeFilter.evaluate((el) => ({
      width: getComputedStyle(el).outlineWidth,
      style: getComputedStyle(el).outlineStyle,
      keyboardVisible: el.matches(":focus-visible"),
    }));
    expect(outline).toEqual({ width: "2px", style: "solid", keyboardVisible: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`hoje-${width}.png`), fullPage: true });
    await page.getByRole("link", { name: "Abrir conversas" }).click();
    await expect(page.getByRole("searchbox", { name: "Buscar conversa" })).toBeVisible();
    if (width < 860) await page.locator(".conv").first().click();
    const person = page.getByRole("button", { name: "Ver pessoa", exact: true });
    await expect(person).toBeVisible();
    const bounds = await person.boundingBox();
    expect(bounds!.width).toBeGreaterThanOrEqual(44);
    expect(bounds!.height).toBeGreaterThanOrEqual(44);
    const placeholder = await page.locator('.thread-foot input[type="text"]').evaluate((el) => {
      const input = el as HTMLInputElement;
      const style = getComputedStyle(input);
      const ctx = document.createElement("canvas").getContext("2d")!;
      ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      return {
        text: ctx.measureText(input.placeholder).width,
        available: input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
      };
    });
    expect(placeholder.text).toBeLessThanOrEqual(placeholder.available);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`conversas-${width}.png`), fullPage: true });
    measurements.push({ width, contrast });
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".thread-head")).toBeVisible();
  const reducedTransition = await page.locator(".conv").first().evaluate((el) =>
    getComputedStyle(el).transitionDuration.split(",").map((duration) => parseFloat(duration)),
  );
  expect(Math.max(...reducedTransition)).toBeLessThanOrEqual(0.001);
  await attachJson(testInfo, "rendered-contrast", measurements);
  expectCleanBrowser(safety);
});
