import { expect, test } from '@playwright/test';
import { API_URL, APP_URL, armBrowserSafety, expectCleanBrowser, loginThroughUi, resetHarness } from './support/helpers';

// All identities and records are synthetic. No external providers or database.
for (const width of [390, 1440]) {
  test(`atribui e encerra responsabilidade com histórico em ${width}px`, async ({ page, request }) => {
    await resetHarness(request);
    const safety = await armBrowserSafety(page);
    await page.setViewportSize({ width, height: 900 });
    let rows: Record<string, unknown>[] = [];
    const cors = { 'Access-Control-Allow-Origin': APP_URL, 'Access-Control-Allow-Headers': 'Authorization, Content-Type', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS' };
    await page.route(url => url.origin === API_URL && url.pathname.startsWith('/responsabilidades'), async route => {
      const req = route.request();
      if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
      if (req.method() === 'POST') {
        const input = req.postDataJSON();
        if (new URL(req.url()).pathname.endsWith('/encerrar')) {
          rows = [{ ...rows[0], fim: input.fim, encerrada_em: '2026-10-21T12:00:00Z' }];
        } else rows = [{ id: '00000000-0000-4000-8000-000000000088', ...input, encerrada_em: null }];
      }
      await route.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: JSON.stringify(req.method() === 'GET' ? rows : rows[0]) });
    });
    await page.route(url => url.origin === API_URL && /^\/contacts(?:\/|$)/.test(url.pathname), async route => {
      if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
      const pessoa = { id: '00000000-0000-4000-8000-000000000077', nome: 'Pessoa sintética', arquivada: false };
      await route.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: JSON.stringify(new URL(route.request().url()).pathname.endsWith('/lookup') ? { items: [pessoa], total: 1, page: 1, pageSize: 25 } : pessoa) });
    });
    await loginThroughUi(page);
    await page.goto('/#responsabilidades');
    await expect(page.getByRole('heading', { name: 'Responsabilidades', exact: true })).toBeVisible();
    await expect(page.getByText('Nenhuma responsabilidade encontrada neste filtro.')).toBeVisible();
    await page.getByRole('button', { name: 'Nova atribuição' }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { name: 'Atribuir responsabilidade' })).toBeFocused();
    await page.getByRole('button', { name: 'Pessoa sintética', exact: true }).click();
    await page.getByLabel('Setor', { exact: true }).selectOption('agenda');
    await page.getByLabel('Início', { exact: true }).fill('2026-01-01');
    await page.getByRole('button', { name: 'Atribuir', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Atribuição registrada' })).toBeVisible();
    await expect(page.getByRole('article')).toContainText('Vigente');
    await page.getByRole('button', { name: 'Encerrar', exact: true }).click();
    await page.getByLabel('Fim (confirmar encerramento)').fill('2099-01-01');
    await page.getByRole('button', { name: 'Confirmar encerramento' }).click();
    await expect(page.getByRole('article')).toContainText('Encerramento registrado');
    await expect(page.getByRole('article')).toContainText('Pessoa sintética');
    await expect(page.getByRole('button', { name: 'Encerrar', exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expectCleanBrowser(safety);
  });
}
test('recusa do servidor oculta ações mesmo com papel local autorizado', async ({ page, request }) => {
  await resetHarness(request);
  await armBrowserSafety(page);
  await page.route(`${API_URL}/responsabilidades?**`, route => route.fulfill({ status: 403, headers: { 'Access-Control-Allow-Origin': APP_URL }, contentType: 'application/json', body: '{"detail":"Sem permissão"}' }));
  await loginThroughUi(page);
  await page.goto('/#responsabilidades');
  await expect(page.getByRole('alert').filter({ hasText: 'Acesso restrito' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Nova atribuição' })).toHaveCount(0);
});
