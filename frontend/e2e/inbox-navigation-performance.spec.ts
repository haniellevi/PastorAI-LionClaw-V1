import { expect, test, type Page } from "@playwright/test";

import {
  API_URL,
  APP_URL,
  LOCAL_TOKEN,
  armBrowserSafety,
  attachJson,
  expectCleanBrowser,
  expectDashboardContextReady,
  percentile75,
  resetHarness,
} from "./support/helpers";

async function openConversation(page: Page) {
  const startedAt = await page.evaluate(() => performance.now());
  await page.getByRole("link", { name: "Conversas", exact: true }).click();
  const contact = page.getByRole("button", { name: /^Contato B\b/ });
  await expect(contact).toBeVisible();
  const listReadyAt = await page.evaluate(() => performance.now());

  await contact.click();
  await expect(page.getByRole("heading", { name: "Contato B", exact: true })).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Histórico da conversa" })
      .getByText("Mensagem sintética do atendimento B."),
  ).toBeVisible();
  const conversationReadyAt = await page.evaluate(() => performance.now());

  return {
    inboxMs: listReadyAt - startedAt,
    conversationMs: conversationReadyAt - listReadyAt,
  };
}

test("mede a abertura do painel e a primeira visita e revisita ao atendimento", async ({
  browser,
  request,
}, testInfo) => {
  test.setTimeout(90_000);
  const metrics = [
    "dashboardMs",
    "firstInboxMs",
    "firstConversationMs",
    "revisitInboxMs",
    "revisitConversationMs",
  ] as const;
  const samples: Record<(typeof metrics)[number], number>[] = [];
  for (let index = 0; index < 5; index += 1) {
    await resetHarness(request, { performance: true });
    const fixture = await request.post(`${API_URL}/__e2e/ux-inbox`, { data: { enabled: true } });
    expect(fixture.ok()).toBeTruthy();
    const page = await browser.newPage({ baseURL: APP_URL, serviceWorkers: "block" });
    try {
      const safety = await armBrowserSafety(page);
      await page.addInitScript(
        (token) => localStorage.setItem("pastorai:token", token),
        LOCAL_TOKEN,
      );
      await page.goto("/#dashboard", { waitUntil: "commit" });
      await expectDashboardContextReady(page);
      const dashboardMs = await page.evaluate(() => performance.now());
      const first = await openConversation(page);
      await page.getByRole("link", { name: "Painel de Hoje", exact: true }).click();
      await expectDashboardContextReady(page);
      const revisit = await openConversation(page);
      expectCleanBrowser(safety);
      samples.push({
        dashboardMs,
        firstInboxMs: first.inboxMs,
        firstConversationMs: first.conversationMs,
        revisitInboxMs: revisit.inboxMs,
        revisitConversationMs: revisit.conversationMs,
      });
    } finally {
      await page.close();
    }
  }

  const summary = Object.fromEntries(
    metrics.map((metric) => {
      const sorted = samples.map((sample) => sample[metric]).sort((a, b) => a - b);
      return [metric, { median: sorted[Math.floor(sorted.length / 2)], p75: percentile75(sorted) }];
    }),
  );
  await attachJson(testInfo, "inbox-navigation-synthetic", {
    browser: browser.version(),
    samples,
    summary,
  });
});
