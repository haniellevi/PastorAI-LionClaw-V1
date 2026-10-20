import { expect, test } from "@playwright/test";
import { API_URL, armBrowserSafety, expectCleanBrowser, loginThroughUi, resetHarness } from "./support/helpers";

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
  expect((await request.post(`${API_URL}/__e2e/ux-inbox`, { data: { enabled: true } })).ok()).toBeTruthy();
});

for (const width of [390, 320]) {
  test(`conversas: foco, envio e retorno em ${width}px com zoom a 200%`, async ({ page }) => {
    await page.setViewportSize({ width: width * 2, height: 844 * 2 });
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    await page.goto("/#inbox");
    // CSS zoom at 200% exercises layout at 390/320 effective CSS pixels.
    await page.addStyleTag({ content: "html { zoom: 2; }" });
    const row = page.locator('.conv').filter({ hasText: "Contato A" });
    await row.click();
    await expect(page.getByRole("heading", { name: "Contato A", exact: true })).toBeFocused();
    await page.getByRole("button", { name: "Assumir atendimento", exact: true }).click();
    const composer = page.getByRole("textbox", { name: "Resposta ao contato" });
    await composer.fill("Mensagem sintética de acessibilidade");
    const send = page.getByRole("button", { name: "Enviar mensagem", exact: true });
    await send.scrollIntoViewIfNeeded();
    const bounds = await send.boundingBox();
    expect(bounds!.width).toBeGreaterThanOrEqual(44);
    expect(bounds!.height).toBeGreaterThanOrEqual(44);
    await send.click();
    await expect(page.locator('.thread-head [role="status"]')).toHaveText("Mensagem enviada.");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Voltar para a lista de conversas" }).click();
    await expect(row).toBeFocused();
    await row.press("Enter");
    await expect(page.getByRole("heading", { name: "Contato A", exact: true })).toBeFocused();
    expectCleanBrowser(safety);
  });
}
