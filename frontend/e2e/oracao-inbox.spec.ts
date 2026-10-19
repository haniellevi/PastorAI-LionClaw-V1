import { expect, test } from '@playwright/test';
import { API_URL, APP_URL, armBrowserSafety, expectCleanBrowser, loginThroughUi, resetHarness } from './support/helpers';

const marker = 'Mensagem pastoral protegida';
const headers = { 'Access-Control-Allow-Origin': APP_URL, 'Access-Control-Allow-Headers': 'Authorization, Content-Type', 'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS' };

test('inbox protege prévia, busca e páginas após handoff e acompanha exclusão privada', async ({ page, request }) => {
  await resetHarness(request);
  await request.post(`${API_URL}/__e2e/ux-inbox`);
  const safety = await armBrowserSafety(page);
  let human = false;
  let deleted = false;
  let completed = false;
  const cursors: string[] = [];
  const receipt = () => ({ id: 'synthetic-receipt', estado: completed ? 'concluido' : 'pendente', camadas: { midias: { encontradas: 1, apagadas: completed ? 1 : 0, pendentes: completed ? 0 : 1, falhas: 0 } } });
  await page.route(`${API_URL}/conversations**`, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    let body: unknown;
    if (method === 'OPTIONS') { await route.fulfill({ status:204, headers }); return; }
    if (path === '/conversations') body = { items: deleted ? [] : [{ id:'prayer-synthetic', telefone:'5500000000000', nome:'Contato oração fictício', pessoaId:null, estado:human?'humano':'ia', ultimaMensagem:marker, naoLidas:0, assumidoPor:human?'00000000-0000-4000-8000-000000000001':null, assumidoPorNome:human?'Você':null, semInteresse:false }], page:1, pageSize:100, total:deleted?0:1 };
    else if (path.endsWith('/photo')) body = {url:null};
    else if (path.endsWith('/handoff')) { human = true; body = { estado:'humano', assumidoPor:'00000000-0000-4000-8000-000000000001' }; }
    else if (path.endsWith('/messages')) {
      const older = url.searchParams.has('before');
      cursors.push(url.search);
      body = { items:[{ id:older?'old-protected':'new-protected', tipo:'texto', direcao:'in', autor:'contato', autorNome:null, texto:marker, mediaUrl:null, mediaMime:null, mediaNome:null, criadoEm:older?'2026-10-18T12:00:00Z':'2026-10-19T12:00:00Z' }], page:1,pageSize:50,total:2,nextBefore:older?null:'older-cursor',nextAfter:'latest-cursor' };
    } else if (path.endsWith('/deletion-receipt')) { completed = true; body = receipt(); }
    else if (method === 'DELETE') { deleted = true; body = receipt(); }
    else { await route.fallback(); return; }
    await route.fulfill({ headers, contentType:'application/json', body:JSON.stringify(body) });
  });
  await loginThroughUi(page);
  await page.goto('/#inbox');
  await expect(page.locator('.snippet')).toHaveText(marker);
  await page.locator('button.conv').click();
  await expect(page.getByRole('note', {name:marker})).toHaveCount(1);
  await page.getByRole('button', {name:'Carregar mensagens anteriores'}).click();
  await expect(page.getByRole('note', {name:marker})).toHaveCount(2);
  expect(cursors.some(cursor=>cursor.includes('before=older-cursor'))).toBe(true);
  await page.getByRole('button', {name:'Assumir atendimento',exact:true}).click();
  await expect(page.getByRole('note', {name:marker})).toHaveCount(2);
  const search = page.getByRole('searchbox', {name:'Buscar conversa'});
  await search.fill('conteúdo pastoral fictício ausente');
  await expect(page.locator('button.conv')).toHaveCount(0);
  await search.fill('');
  await page.locator('button.conv').click();
  await page.locator('.ib-more-actions > summary').click();
  await page.getByRole('button', {name:'Excluir conversa',exact:true}).click();
  const dialog = page.getByRole('dialog', {name:'Excluir conversa'});
  await dialog.getByRole('button', {name:'Excluir conversa',exact:true}).click();
  await expect(dialog.getByRole('status')).toContainText('Exclusão pendente: limpeza de mídia');
  await dialog.getByRole('button', {name:'Atualizar recibo'}).click();
  await expect(dialog.getByRole('status')).toContainText('Exclusão concluída');
  await expect(page.locator('body')).not.toContainText('conteúdo pastoral fictício ausente');
  expectCleanBrowser(safety);
});
