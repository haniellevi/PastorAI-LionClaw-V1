import { expect, test, type Page } from "@playwright/test";

import type { CellSummary, Reuniao, NextMeetingBody, CellMember } from "../src/lib/cells-api";
import type { ReportOut } from "../src/lib/cell-meetings-api";
import type { CentralDashboard } from "../src/lib/cell-central-api";
import type { EventItem } from "../src/lib/events-api";
import type { TreeNode } from "../src/lib/g12-api";
import type { ReportItem } from "../src/lib/reports-api";
import type { MeResult } from "../src/lib/api";
import type { Contact, ContactDetail } from "../src/lib/contacts-api";
import type { Page as ApiPage, TeamMember } from "../src/lib/dashboard-api";
import type { PermissionMatrix } from "../src/lib/permissions";
import { API_URL, APP_URL, armBrowserSafety, expectCleanBrowser, loginThroughUi, resetHarness } from "./support/helpers";

const cell: CellSummary = { id: "ops-cell-A", nome: "Célula de exemplo com nome longo para encontrar e acompanhar", liderId: "ops-leader", diaReuniao: "Quarta-feira", horario: "19:30", coberturaEspiritual: "Cobertura de exemplo", ativo: true };
const otherCell: CellSummary = { ...cell, id: "ops-cell-B", nome: "Célula de exemplo B" };
const members: CellMember[] = [{ pessoa_id: "ops-person-1", nome: "Pessoa de exemplo com nome composto", ativo: true }];
const meetings: Reuniao[] = [
  { id: "ops-meeting-A", celulaId: cell.id, data: "2026-09-30", hora: "19:30", tema: "Tema de exemplo A", status: "planejada" },
  { id: "ops-meeting-B", celulaId: cell.id, data: "2026-09-23", hora: "19:30", tema: "Tema de exemplo B", status: "realizada" },
];
const meeting: NextMeetingBody = { id: meetings[0]!.id, celula_id: cell.id, data: meetings[0]!.data, hora: "19:30", local: "Local fictício", tema: meetings[0]!.tema, minha_presenca: "nao_confirmou" };
const tree: TreeNode[] = [{ id: "ops-root", nome: "Liderança de exemplo", tipo: "pastor", children: [{ id: "ops-branch", nome: "Responsável de exemplo com nome longo", tipo: "membro", children: [{ id: "ops-leaf", nome: "Pessoa da descendência", tipo: "membro", children: [] }] }] }];
const dashboard: CentralDashboard = { relatorios_pendentes: 0, solicitacoes_aguardando: 0, celulas_com_alerta: 0, multiplicacoes_pendentes: 1, avisos_recentes: 0, materiais_recentes: 0 };
const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "America/Sao_Paulo" }).format(new Date());
const initialEvent: EventItem = { id: "ops-event", titulo: "Evento de exemplo aguardando confirmação", data: today, hora: "19:00", descricao: "Detalhes fictícios para a revisão", googleEventId: "ops-google", sincronizado: true, status: "a_confirmar", origem: "google", tipo: "reuniao" };
const pendingReport: ReportItem = { id: "ops-meeting-B", celulaId: cell.id, celulaNome: cell.nome, semana: "2026-W40", status: "pendente", dataReuniao: "2026-09-23", presentes: null, visitantes: null, decisoes: null, oferta: null, observacoes: null };

function pageOf<T>(items: T[]): ApiPage<T> { return { items, page: 1, pageSize: 200, total: items.length }; }

const permissions: PermissionMatrix = {
  lider_celula: ["dashboard", "minha-celula", "calendario"],
  membro: ["dashboard", "minha-celula", "calendario"],
};

async function fixtures(page: Page) {
  const writes: Array<{ path: string; body: unknown }> = [];
  const reportQueries: string[] = [];
  const reports = new Map<string, ReportOut>(meetings.map((item) => [item.id, { meeting_id: item.id, data: item.data, tema: item.tema, relatorio_status: "rascunho", oferta_valor: null, observacoes: null, presencas: [], visitantes: [], records: [] }]));
  let event = { ...initialEvent };
  const controls = { leader: false, member: false, failReports: false, failEnviar: false };
  await page.route(`${API_URL}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    let data: unknown;
    let status = 200;
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: { "Access-Control-Allow-Origin": APP_URL, "Access-Control-Allow-Headers": "Authorization, Content-Type", "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS" } });
      return;
    }
    if (path === "/auth/me" && (controls.leader || controls.member)) data = { appUserId: "00000000-0000-4000-8000-000000000001", churchId: "00000000-0000-4000-8000-000000000002", email: "admin.e2e@example.test", nome: controls.leader ? "Líder de exemplo" : "Membro de exemplo", chatNome: controls.leader ? "Líder" : "Membro", roles: [controls.leader ? "lider_celula" : "membro"], isOwner: false, igrejaNome: "Igreja Laboratório", igrejaLogoUrl: null } satisfies MeResult;
    else if (method === "GET" && path === "/roles/permissions") data = { matriz: permissions };
    else if (method === "GET" && path === "/contacts") data = pageOf<Contact>([{id:"ops-leader",nome:"Líder sintético de exemplo",telefone:"5500000000000",email:null,genero:null,tipo:"membro",etapa:"discipular",subetapa:null,acompanhamento:null,semInteresse:false,semInteresseMotivo:null,presencasCelula:0,aceitouJesus:false,celulaId:null,liderId:null,aptoLider:true,liderDeCelula:true}]);
    else if (method === "GET" && path === "/contacts/ops-leader") data = {id:"ops-leader",nome:"Líder sintético de exemplo",telefone:"5500000000000",email:null,genero:null,tipo:"membro",etapa:"discipular",subetapa:null,acompanhamento:null,semInteresse:false,semInteresseMotivo:null,presencasCelula:0,aceitouJesus:false,celulaId:null,liderId:null,aptoLider:true,liderDeCelula:true,faixaEtaria:null,endereco:null,celulaNome:null,liderNome:null,arquivada:false,consentimento:false,optout:false,origem:null,primeiroContato:null,criadoEm:null} satisfies ContactDetail;
    else if (method === "GET" && path === "/team") data = pageOf<TeamMember>([]);
    else if (method === "GET" && path === "/cells") data = pageOf([cell, otherCell]);
    else if (method === "GET" && path === "/cells/me/leading") data = [{ id: cell.id, nome: cell.nome }];
    else if (method === "GET" && path === "/cells/me/next-meeting") data = { meeting };
    else if (method === "GET" && path === "/cells/me/history") data = { items: [{ data: "2026-09-23", tema: "Histórico de exemplo", minha_presenca: "participou", meus_visitantes_indicados: [] }], page: 1, page_size: 20, total: 1 };
    else if (method === "GET" && path === "/cells/me/notices") data = [];
    else if (method === "GET" && (path === `/cells/${cell.id}` || path === `/cells/${otherCell.id}`)) data = { ...(path.endsWith(otherCell.id) ? otherCell : cell), alerts: [] };
    else if (method === "GET" && path === `/cells/${cell.id}/members`) data = { members };
    else if (method === "GET" && path === `/cells/${cell.id}/membros`) data = [];
    else if (method === "GET" && path === `/cells/${cell.id}/reunioes`) data = meetings;
    else if (method === "GET" && path === "/descendencias") data = tree;
    else if (method === "GET" && path === "/cell-central/dashboard") data = dashboard;
    else if (method === "GET" && path === "/cell-central/pending-reports") data = { items: [], page: 1, page_size: 20 };
    else if (method === "GET" && path === "/cell-central/health") data = { cells: [] };
    else if (method === "GET" && ["/cell-requests", "/cell-materials", "/cell-notices"].includes(path)) data = pageOf([]);
    else if (method === "GET" && path === "/multiplicacoes") {
      if (controls.failEnviar) { status = 500; data = { detail: "Falha fictícia ao carregar multiplicações." }; }
      else data = { pendentes: [{ id: "ops-mult", celula_id: cell.id, solicitante_id: null, tipo: "multiplicacao", status: "aguardando", payload_proposto: { nome_nova_celula: "Nova célula de exemplo" }, created_at: "2026-09-29T12:00:00Z" }], registradas: [] };
    }
    else if (method === "GET" && path === "/events") data = pageOf([event]);
    else if (method === "GET" && path === "/reports") {
      reportQueries.push(url.search);
      if (controls.failReports) { status = 500; data = { detail: "Falha fictícia ao carregar relatórios." }; }
      else data = pageOf([pendingReport, { ...pendingReport, id: "ops-received", status: "recebido", presentes: 1, visitantes: 0, decisoes: 0, oferta: 0 }]);
    }
    else {
      const reportMatch = path.match(/^\/cell-meetings\/(ops-meeting-[AB])\/report$/);
      const attendanceMatch = path.match(/^\/cell-meetings\/(ops-meeting-[AB])\/attendance$/);
      const submitMatch = path.match(/^\/cell-meetings\/(ops-meeting-[AB])\/report\/submit$/);
      if (method === "GET" && reportMatch) data = reports.get(reportMatch[1]!);
      else if (method === "GET" && /^\/cell-meetings\/ops-meeting-[AB]\/visitor-expectations$/.test(path)) data = { expectations: [] };
      else if (method === "PUT" && attendanceMatch) {
        const body = request.postDataJSON() as { presencas: Array<{ pessoa_id: string; compareceu: boolean }> };
        writes.push({ path, body });
        const report = reports.get(attendanceMatch[1]!)!;
        report.presencas = body.presencas.map((item) => ({ pessoa_id: item.pessoa_id, estado: item.compareceu ? "compareceu" : "faltou", origem: "lider" }));
        data = { meeting_id: report.meeting_id, presencas: body.presencas };
      } else if (method === "POST" && submitMatch) {
        writes.push({ path, body: null });
        reports.get(submitMatch[1]!)!.relatorio_status = "enviado";
        data = { meeting_id: submitMatch[1], relatorio_status: "enviado" };
      } else if (method === "POST" && path === `/cell-meetings/${meeting.id}/attendance/confirm`) {
        writes.push({ path, body: null });
        data = { reuniao_id: meeting.id, minha_presenca: "confirmou" };
      } else if (method === "POST" && path === `/events/${event.id}/confirm`) {
        writes.push({ path, body: request.postData() ? request.postDataJSON() : null });
        event = { ...event, status: "confirmado" };
        data = event;
      } else { await route.fallback(); return; }
    }
    await route.fulfill({ status, headers: { "Access-Control-Allow-Origin": APP_URL, "Cache-Control": "no-store" }, contentType: "application/json", body: JSON.stringify(data) });
  });
  // Reinicia o cache local aquecido pelo dashboard com as rotas fictícias instaladas.
  await page.reload();
  return { controls, writes, reportQueries };
}

test.beforeEach(async ({ request }) => resetHarness(request));

test("uma resposta atrasada da célula anterior não substitui a seleção atual", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  await fixtures(page);
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`${API_URL}/cells/${cell.id}`, async (route) => {
    await pending;
    await route.fulfill({ status: 200, headers: { "Access-Control-Allow-Origin": APP_URL }, contentType: "application/json", body: JSON.stringify({ ...cell, alerts: [] }) });
  });
  try {
    await page.goto("/#celulas");
    await page.getByRole("button", { name: `Abrir célula ${cell.nome}`, exact: true }).click();
    await page.getByRole("button", { name: `Abrir célula ${otherCell.nome}`, exact: true }).click();
    await expect(page.locator(".dash-side h3")).toHaveText(otherCell.nome);
    const response = page.waitForResponse(`${API_URL}/cells/${cell.id}`);
    release();
    await (await response).finished();
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.locator(".dash-side h3")).toHaveText(otherCell.nome);
    expectCleanBrowser(safety);
  } finally { release(); }
});

for (const width of [390, 1440]) {
  test(`células permite localizar, abrir e voltar à lista em ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    await fixtures(page);
    await page.goto("/#celulas");
    const search = page.getByRole("searchbox", { name: "Buscar célula ou líder" });
    await search.fill("nome longo");
    const trigger = page.getByRole("button", { name: `Abrir célula ${cell.nome}`, exact: true });
    await trigger.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".dash-side h3")).toHaveText(cell.nome);
    await page.getByRole("button", { name: "Voltar à lista de células", exact: true }).click();
    await expect(search).toHaveValue("nome longo");
    await expect(trigger).toBeFocused();
    await search.fill("sem correspondência");
    await expect(page.getByText("Nenhuma célula corresponde à busca.")).toBeVisible();
    await page.getByRole("button", { name: "Limpar busca", exact: true }).click();
    await expect(page.getByRole("button", { name: `Abrir célula ${otherCell.nome}`, exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`celulas-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });

  test(`rede G12 abre a descendência e retorna pelo caminho em ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    await fixtures(page);
    await page.goto("/#g12");
    const branch = page.getByRole("button", { name: "Abrir descendência de Responsável de exemplo com nome longo", exact: true });
    await branch.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("navigation", { name: "Descendência atual" })).toBeFocused();
    await expect(page.getByRole("button", { name: "Pessoa da descendência, sem liderados", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Liderança de exemplo", exact: true }).click();
    await expect(branch).toBeVisible();
    await page.getByRole("button", { name: "Indicadores", exact: true }).click();
    await expect(page.getByRole("button", { name: "Indicadores", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("table")).toBeVisible();
    await page.emulateMedia({ reducedMotion: "reduce" });
    const motion = await page.locator(".ops-v2").evaluate((el) => getComputedStyle(el).animationDuration.split(",").map(parseFloat));
    expect(Math.max(...motion)).toBeLessThanOrEqual(0.001);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`g12-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });

  test(`membro confirma presença na própria reunião e encontra histórico em ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    const fixture = await fixtures(page);
    fixture.controls.member = true;
    await page.goto("/#minha-celula");
    await page.reload();
    await expect(page.locator(".meeting-tema")).toContainText("Tema de exemplo A");
    const attendance = page.getByRole("button", { name: "Confirmar presença", exact: true });
    await attendance.click();
    await expect(page.locator(".meeting-actions button[aria-pressed='true']")).toBeVisible();
    expect(fixture.writes.map((item) => item.path)).toEqual([`/cell-meetings/${meeting.id}/attendance/confirm`]);
    await page.getByText("Meu histórico de reuniões", { exact: true }).click();
    await expect(page.getByText("Histórico de exemplo", { exact: true })).toBeVisible();
    expectCleanBrowser(safety);
  });

  test(`líder salva presença e envia apenas o relatório da reunião escolhida em ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    const fixture = await fixtures(page);
    fixture.controls.leader = true;
    await page.goto("/#minha-celula");
    await page.reload();
    await page.getByLabel("Reunião do relatório", { exact: true }).selectOption("ops-meeting-B");
    await expect(page.locator(".mc-report-head")).toContainText("Tema de exemplo B");
    const attendance = page.getByRole("checkbox", { name: `Presença de ${members[0]!.nome}`, exact: true });
    const attendanceLabel = attendance.locator("..");
    await attendanceLabel.scrollIntoViewIfNeeded();
    const target = await attendanceLabel.evaluate((label) => {
      const bounds = label.getBoundingClientRect();
      const center = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
      const footer = document.querySelector('nav[aria-label="Navegação rápida"]')?.getBoundingClientRect();
      return {
        width: bounds.width,
        height: bounds.height,
        unobstructed: center !== null && label.contains(center),
        aboveFooter: !footer || footer.width === 0 || bounds.bottom <= footer.top,
      };
    });
    expect(target.width, "alvo de presença com largura mínima de 44px").toBeGreaterThanOrEqual(44);
    expect(target.height, "alvo de presença com altura mínima de 44px").toBeGreaterThanOrEqual(44);
    expect(target.unobstructed, "rodapé não deve bloquear o label de presença").toBe(true);
    expect(target.aboveFooter, "alvo inteiro de presença deve ficar acima do rodapé").toBe(true);
    if (width === 390) await attendanceLabel.click();
    else {
      await attendance.focus();
      await page.keyboard.press("Space");
    }
    await expect(attendance).toBeChecked();
    await page.getByRole("button", { name: "Salvar presença", exact: true }).click();
    await expect(page.getByText("Presença salva.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /^Fechamento e envio/ }).click();
    await page.getByRole("button", { name: "Enviar relatório", exact: true }).click();
    await expect(page.getByText("Relatório enviado e bloqueado para edição.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar relatório", exact: true })).toHaveCount(0);
    expect(fixture.writes).toEqual([
      { path: "/cell-meetings/ops-meeting-B/attendance", body: { presencas: [{ pessoa_id: members[0]!.pessoa_id, compareceu: true }] } },
      { path: "/cell-meetings/ops-meeting-B/report/submit", body: null },
    ]);
    expectCleanBrowser(safety);
  });

  test(`agenda distingue detalhe e confirmação sem notificar em ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    const fixture = await fixtures(page);
    await page.goto("/#calendario");
    await page.getByRole("tab", { name: /A confirmar/ }).click();
    const row = page.locator(".agenda-confirm-list .list-row").first();
    await row.getByRole("button", { name: new RegExp(initialEvent.titulo) }).click();
    await expect(page.getByRole("dialog", { name: initialEvent.titulo, exact: true })).toBeVisible();
    await expect(page.getByText("Importado do Google", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    const confirm = row.getByRole("button", { name: "Confirmar", exact: true });
    await confirm.click();
    const dialog = page.getByRole("dialog", { name: "Confirmar evento", exact: true });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: /^Confirmar/ }).click();
    await expect(page.getByText("Nenhum evento aguardando confirmação.", { exact: true })).toBeVisible();
    expect(fixture.writes).toEqual([{ path: `/events/${initialEvent.id}/confirm`, body: null }]);
    await page.screenshot({ path: testInfo.outputPath(`agenda-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });

  test(`relatórios anunciam período e mostram pendência sem números inventados em ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    await loginThroughUi(page);
    const fixture = await fixtures(page);
    await page.goto("/#relatorios");
    await page.locator(".reports-pending").getByRole("button", { name: /^Ver relatório/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Relatório ainda não enviado.", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Presentes", { exact: true })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Histórico", exact: true }).click();
    await expect(page.getByRole("button", { name: "Histórico", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Histórico das reuniões da semana anterior. Datas no horário de São Paulo.", { exact: true })).toBeVisible();
    await expect.poll(() => fixture.reportQueries.some((query) => /semana=\d{4}-W\d{2}/.test(query))).toBeTruthy();
    expectCleanBrowser(safety);
  });
}

for (const width of [768, 1024, 1440]) test(`agenda mensal mantém leitura, seleção do dia e detalhe por teclado em ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 });
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  const fixture = await fixtures(page);
  await page.goto("/#calendario");
  await page.getByRole("tab", { name: "Mês", exact: true }).click();
  const compact = width < 1440;
  await expect(page.locator(compact ? ".cal" : ".cal-m")).toBeHidden();
  await expect(page.locator(compact ? ".cal-m" : ".cal")).toBeVisible();
  if (compact) {
    const emptyDay = page.locator(".cal-m-cell:not(.off)").filter({ hasNot: page.locator(".cal-m-count") }).first();
    await emptyDay.click();
    await expect(emptyDay).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Nenhum evento neste dia.", { exact: true })).toBeVisible();
    const day = page.locator(".cal-m-cell").filter({ has: page.locator(".cal-m-count") });
    await expect(day).toBeVisible();
    await day.focus();
    await page.keyboard.press("Enter");
    await expect(day).toHaveAttribute("aria-pressed", "true");
    const dayBounds = await day.boundingBox();
    expect(dayBounds!.width).toBeGreaterThanOrEqual(44);
    expect(dayBounds!.height).toBeGreaterThanOrEqual(44);
  }
  const event = page.locator(compact ? ".cal-m-event" : ".cal .cal-ev").filter({ hasText: initialEvent.titulo });
  await expect(event).toBeVisible();
  const bounds = await event.boundingBox();
  expect(bounds!.width).toBeGreaterThanOrEqual(44);
  expect(bounds!.height).toBeGreaterThanOrEqual(44);
  const title = event.locator(compact ? ".nm" : ".cal-ev-title");
  expect(await title.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
  await expect(event.locator(compact ? ".sub" : ".cal-ev-time")).toHaveText(initialEvent.hora!);
  await expect(title).toHaveText(initialEvent.titulo);
  await page.evaluate(() => document.fonts.ready);
  const words = await title.evaluate((el) => {
    const text = el.firstChild;
    if (!(text instanceof Text)) throw new Error("Título do evento sem texto visível.");
    const bounds = el.getBoundingClientRect();
    return [...(text.textContent ?? "").matchAll(/\S+/g)].map((word) => {
      const range = document.createRange();
      range.setStart(text, word.index!);
      range.setEnd(text, word.index! + word[0].length);
      const lines = [...range.getClientRects()];
      return { text: word[0], lines: lines.length, contained: lines.every((line) => line.left >= bounds.left - 1 && line.right <= bounds.right + 1) };
    });
  });
  for (const word of words) {
    expect(word.lines, `palavra inteira no título: ${word.text}`).toBe(1);
    expect(word.contained, `palavra dentro do evento: ${word.text}`).toBe(true);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await event.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: initialEvent.titulo, exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(event).toBeFocused();
  expect(fixture.writes).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath(`agenda-mes-${width}.png`), fullPage: true });
  expectCleanBrowser(safety);
});

test("Central identifica a célula alvo e Enviar conserva panorama somente leitura", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  const fixture = await fixtures(page);
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/#central-celula");
    await page.getByRole("tab", { name: "Gerenciar células", exact: true }).click();
    await page.getByRole("searchbox", { name: "Buscar célula", exact: true }).fill("nome longo");
    await page.locator(".cc-cell-row").filter({ hasText: cell.nome }).click();
    await expect(page.getByText(`Célula selecionada: ${cell.nome}. As ações abaixo se aplicam a ela.`, { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Editar célula", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Editar célula", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await page.goto("/#enviar");
    await expect(page.getByText("Nova célula de exemplo", { exact: true })).toBeVisible();
    await expect(page.getByText("Aguardando", { exact: true })).toBeVisible();
    await expect(page.getByText("Nenhuma multiplicação registrada ainda.", { exact: true })).toBeVisible();
  }
  expect(fixture.writes).toEqual([]);
  expectCleanBrowser(safety);
});

test("falha de leitura não vira conclusão de ausência de relatório ou multiplicação", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  await loginThroughUi(page);
  const fixture = await fixtures(page);
  fixture.controls.failReports = true;
  fixture.controls.failEnviar = true;
  await page.goto("/#relatorios");
  await expect(page.locator(".ops-v2 [role='alert']")).toContainText("Não foi possível carregar os relatórios");
  await expect(page.getByText("Nenhuma reunião de célula nesta semana.", { exact: true })).toHaveCount(0);
  fixture.controls.failReports = false;
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.locator(".reports-pending")).toBeVisible();
  await page.goto("/#enviar");
  await expect(page.locator(".ops-v2 [role='alert']")).toContainText("Falha fictícia ao carregar multiplicações");
  await expect(page.getByText("Nenhuma multiplicação aguardando decisão.", { exact: true })).toHaveCount(0);
  fixture.controls.failEnviar = false;
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.getByText("Nova célula de exemplo", { exact: true })).toBeVisible();
  expect(safety.externalRequests).toEqual([]);
  expect(safety.pageErrors).toEqual([]);
  expect(safety.consoleErrors.filter((message) => !/^Failed to load resource: the server responded with a status of 500/.test(message))).toEqual([]);
});
