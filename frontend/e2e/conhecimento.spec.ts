import { test, expect, type Route } from '@playwright/test';
import { API_URL, APP_URL, armBrowserSafety, expectCleanBrowser, loginThroughUi, resetHarness } from './support/helpers';

const versionId = '00000000-0000-4000-8000-000000000001';
const documentId = '00000000-0000-4000-8000-000000000002';
const userId = '00000000-0000-4000-8000-000000000003';
const cors = { 'Access-Control-Allow-Origin': APP_URL, 'Access-Control-Allow-Headers': 'Authorization, Content-Type', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS' };
const json = (route: Route, body: unknown) => route.fulfill({ headers: cors, contentType: 'application/json', body: JSON.stringify(body) });

test.beforeEach(async ({ request }) => { await resetHarness(request); });

test('admin cria, envia, revisa, publica, substitui e revoga com público explícito', async ({ page }) => {
  const safety = await armBrowserSafety(page);
  let state = ''; let current: string | null = null; let id = versionId;
  let content = ''; let audiences: string[] = []; let title = '';
  const history: object[] = [];
  await page.route(`${API_URL}/conhecimento/**`, async route => {
    if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: cors }); return; }
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === 'GET') {
      if (path === '/conhecimento/documentos') {
        const actions = state === 'rascunho' ? ['editar', 'enviar-revisao', 'revogar'] : state === 'em_revisao' ? ['revisar', 'publicar', 'revogar'] : state === 'publicada' ? ['editar', 'revogar'] : [];
        await json(route, { pode_criar: true, responsavel_id: userId, documentos: state ? [{ id: documentId, titulo: title, assunto: 'Institucional', vigente_id: current, versoes: [...history, { id, numero: history.length + 1, estado: state, publicos: audiences, criada_em: '2026-10-19T12:00:00Z', vigente: state === 'publicada', pode_ler: state !== 'revogada', acoes: actions }] }] : [] });
      } else await json(route, { titulo: title, conteudo: content, origem: 'Manual institucional sintético', estado: state, publicos: audiences });
      return;
    }
    const input = route.request().postDataJSON();
    expect(input.operacao_id).toBeTruthy();
    if (path === '/conhecimento/documentos' || path.endsWith('/rascunhos')) {
      if (state) history.push({ id, numero: 1, estado: 'substituida', publicos: audiences, criada_em: '2026-10-19T12:00:00Z', vigente: false, pode_ler: false, acoes: [] });
      title = input.titulo ?? title; content = input.conteudo; audiences = input.publicos; id = input.versao_id; state = 'rascunho';
      expect(input.responsavel_id ?? userId).toBe(userId);
    } else if (path.endsWith('/enviar-revisao')) state = 'em_revisao';
    else if (path.endsWith('/publicar')) { expect(input.vigente_esperada_id).toBe(current); expect(input.publicos).toEqual(audiences); current = id; state = 'publicada'; }
    else if (path.endsWith('/revogar')) { current = null; state = 'revogada'; }
    await json(route, { documento_id: documentId, versao_id: id });
  });
  await loginThroughUi(page);
  await page.goto('/gestao#conhecimento');
  await page.getByRole('button', { name: 'Criar rascunho', exact: true }).click();
  await page.getByLabel('Título', { exact: true }).fill('Guia sintético de acolhimento');
  await page.getByLabel('Assunto', { exact: true }).fill('Institucional');
  await page.getByLabel('Origem oficial').fill('Manual institucional sintético');
  await page.getByLabel('Texto do documento').fill('Orientação oficial fictícia para acolhimento.');
  await page.getByLabel('Público institucional (inclui visitantes)', { exact: true }).check();
  await page.getByRole('button', { name: 'Salvar rascunho', exact: true }).click();
  await page.getByRole('button', { name: 'Enviar rascunho salvo para revisão' }).click();
  const article = page.getByRole('article');
  const expand = async () => {
    await expect(article).toBeVisible();
    if (!await article.locator('details').evaluate(el => el.hasAttribute('open'))) await article.locator('summary').click();
  };
  await expand();
  await article.getByRole('button', { name: 'Registrar revisão', exact: true }).click();
  await page.getByRole('button', { name: 'Confirmar registrar revisão' }).click();
  await expand();
  await article.getByRole('button', { name: 'Aprovar e publicar', exact: true }).click();
  await expect(page.getByLabel('Documento selecionado')).toContainText('Público institucional');
  await page.getByRole('button', { name: 'Confirmar aprovar e publicar' }).click();
  await expect(article).toContainText('Versão vigente: versão 1');
  await expand();
  await article.getByRole('button', { name: 'Criar nova versão' }).click();
  await page.getByLabel('Texto do documento').fill('Segunda orientação oficial fictícia.');
  await page.getByRole('button', { name: 'Salvar rascunho', exact: true }).click();
  await page.getByRole('button', { name: 'Enviar rascunho salvo para revisão' }).click();
  await expand();
  await article.getByRole('button', { name: 'Aprovar e publicar', exact: true }).click();
  await page.getByRole('button', { name: 'Confirmar aprovar e publicar' }).click();
  await expect(article).toContainText('Versão vigente: versão 2');
  await expand();
  await article.getByRole('button', { name: 'Revogar versão', exact: true }).click();
  await page.getByRole('button', { name: 'Confirmar revogar versão' }).click();
  await expand();
  await expect(article).toContainText('Revogada');
  expectCleanBrowser(safety);
});

test('leitor em tela móvel busca trecho sem ações editoriais nem IDs visíveis', async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await page.route(`${API_URL}/conhecimento/**`, async route => {
    if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: cors }); return; }
    expect(route.request().method()).toBe('GET');
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/documentos')) await json(route, { pode_criar: false, responsavel_id: null, documentos: [] });
    else if (path.endsWith('/busca')) await json(route, [{ titulo: 'Guia sintético', versao_id: versionId, trecho: 'Trecho oficial fictício para acolher.', secao: '', ordem: 1 }]);
    else await json(route, { titulo: 'Guia sintético', estado: 'publicada', conteudo: 'Texto oficial fictício.', origem: 'Manual', publicos: ['institucional_publico'] });
  });
  await loginThroughUi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#conhecimento');
  await expect(page.getByRole('heading', { name: 'Conhecimento oficial', level: 2 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Criar rascunho' })).toHaveCount(0);
  await page.getByLabel('Buscar nos documentos publicados').fill('acolher');
  await page.getByRole('button', { name: 'Buscar', exact: true }).click();
  await expect(page.getByText('Trecho oficial fictício para acolher.')).toBeVisible();
  await page.getByRole('button', { name: 'Guia sintético', exact: true }).click();
  await expect(page.getByLabel('Documento selecionado')).toBeFocused();
  await expect(page.getByText('Texto oficial fictício.')).toBeVisible();
  await expect(page.locator('body')).not.toContainText(versionId);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Fechar documento' }).press('Enter');
  await expect(page.getByLabel('Documento selecionado')).toHaveCount(0);
  expectCleanBrowser(safety);
});
