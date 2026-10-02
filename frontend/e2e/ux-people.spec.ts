import { expect, test, type Page, type Route } from "@playwright/test";

import type { Contact, CreateContactInput } from "@/lib/contacts-api";
import type { Page as ApiPage } from "@/lib/dashboard-api";
import {
  API_URL, APP_URL, armBrowserSafety, attachJson, loginThroughUi,
  resetHarness, type BrowserSafety,
} from "./support/helpers";

const CELL_ID = "00000000-0000-4000-8000-000000000020";
const ACTOR_ID = "00000000-0000-4000-8000-000000000001";
const CONSOLIDATION_ID = "00000000-0000-4000-8000-000000000090";
const cors = {
  "Access-Control-Allow-Origin": APP_URL,
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, OPTIONS",
};

function person(index: number): Contact {
  return {
    id: `ux-person-${index}`, nome: `Pessoa Laboratório ${index}`,
    telefone: `55000000${String(index).padStart(4, "0")}`, email: null,
    genero: null, tipo: "membro", etapa: "discipular", subetapa: null,
    acompanhamento: null, semInteresse: false, semInteresseMotivo: null,
    presencasCelula: 0, aceitouJesus: false, celulaId: null, liderId: null,
    aptoLider: false, liderDeCelula: false, arquivada: false,
  };
}

async function json(route: Route, status: number, body: unknown) {
  await route.fulfill({ status, headers: cors, contentType: "application/json", body: JSON.stringify(body) });
}

async function peopleFixture(page: Page) {
  const people = Array.from({ length: 52 }, (_, i) => person(i + 1));
  people[0] = { ...people[0]!, nome: "Marina Laboratório", email: "marina@example.test", tipo: "visitante", etapa: "ganhar", subetapa: "novo_contato" };
  people[1] = { ...people[1]!, nome: "João Laboratório", tipo: "visitante", etapa: "ganhar", subetapa: "visitante", presencasCelula: 3, celulaId: CELL_ID };
  people[50] = { ...people[50]!, nome: "Rafael Laboratório", etapa: "consolidar", celulaId: CELL_ID, aceitouJesus: true };
  const archived = { ...person(99), nome: "Pessoa Arquivada Laboratório", arquivada: true };
  const reads: Array<{ page: number; pageSize: number; view: string }> = [];
  const writes: Array<{ path: string; body: unknown }> = [];
  let createAttempts = 0;
  let decisionAttempts = 0;
  let stageAttempts = 0;
  const paged = (items: Contact[], pageNumber: number, pageSize: number): ApiPage<Contact> => ({
    items: items.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
    page: pageNumber, pageSize, total: items.length,
  });
  await page.route(`${API_URL}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (method === "OPTIONS") { await route.fulfill({ status: 204, headers: cors }); return; }
    if (path === "/contacts" && method === "GET") {
      const pageNumber = Number(url.searchParams.get("page") ?? 1);
      const pageSize = Number(url.searchParams.get("pageSize") ?? 200);
      const view = url.searchParams.get("view") ?? "all";
      reads.push({ page: pageNumber, pageSize, view });
      const filtered = view === "arquivadas" ? [archived] : view === "visitante" ? people.filter((p) => p.tipo === "visitante") : people;
      await json(route, 200, paged(filtered, pageNumber, pageSize)); return;
    }
    if (path === "/cells" && method === "GET") {
      await json(route, 200, {
        items: [
          { id: CELL_ID, nome: "Célula Laboratório", liderId: ACTOR_ID, ativo: true, coberturaEspiritual: "Laboratório", diaReuniao: null, horario: null },
          { id: "ux-inactive-cell", nome: "Célula Inativa Laboratório", liderId: ACTOR_ID, ativo: false, coberturaEspiritual: "Laboratório", diaReuniao: null, horario: null },
        ], page: 1, pageSize: 200, total: 2,
      }); return;
    }
    if (path === "/pipeline" && method === "GET") {
      const items = people.filter((p) => p.etapa === url.searchParams.get("etapa"));
      await json(route, 200, paged(items, 1, 200)); return;
    }
    if (method !== "GET" && (path.startsWith("/contacts") || path.startsWith("/pipeline") || path === "/consolidacao/decisao")) {
      writes.push({ path, body: request.postDataJSON() });
    }
    if (path === "/contacts" && method === "POST") {
      const input = request.postDataJSON() as CreateContactInput;
      createAttempts++;
      if (createAttempts === 1) { await json(route, 409, { detail: "Conflito fictício. Revise o telefone e tente novamente." }); return; }
      const created = { ...person(100), ...input, tipo: input.tipo ?? "contato", nome: input.nome, telefone: input.telefone };
      people.push(created);
      await json(route, 200, { contact: created, deduped: false }); return;
    }
    if (/^\/contacts\/ux-person-\d+\/cell$/.test(path) && method === "POST") {
      const id = path.split("/")[2];
      const index = people.findIndex((p) => p.id === id);
      people[index] = { ...people[index]!, celulaId: request.postDataJSON().celulaId };
      await json(route, 200, people[index]); return;
    }
    if (/^\/contacts\/ux-person-\d+$/.test(path) && method === "GET") {
      await json(route, 200, people.find((p) => p.id === path.split("/")[2])); return;
    }
    if (path === "/pipeline" && method === "PUT") {
      const input = request.postDataJSON() as { pessoaId: string; etapa: string };
      const index = people.findIndex((p) => p.id === input.pessoaId);
      if (index >= 0) people[index] = { ...people[index]!, etapa: input.etapa };
      await json(route, 200, { status: "synthetic-only" }); return;
    }
    if (path === "/consolidacao/decisao" && method === "POST") {
      decisionAttempts++;
      if (decisionAttempts === 1) { await json(route, 409, { detail: "Decisão fictícia recusada. Revise e tente novamente." }); return; }
      await json(route, 200, { status: "synthetic-only", consolidacaoId: CONSOLIDATION_ID, etapa: "consolidar", prazoConexao: null, responsavel: ACTOR_ID }); return;
    }
    if (path === "/pipeline/advance-stage" && method === "POST") {
      const input = request.postDataJSON() as { consolidacaoId: string; etapa: string | null; concluir: boolean };
      stageAttempts++;
      if (stageAttempts === 1) { await json(route, 409, { detail: { message: "Etapa fictícia recusada. O registro foi preservado.", etapasPendentes: ["fonovisita"] } }); return; }
      if (input.concluir) people[50] = { ...people[50]!, acompanhamento: "consolidado", subetapa: "consolidado" };
      await json(route, 200, { status: "synthetic-only", consolidacaoId: CONSOLIDATION_ID, progresso: 100, concluida: input.concluir, etapasPendentes: [] }); return;
    }
    await route.fallback();
  });
  return { reads, writes };
}

function expectSafety(safety: BrowserSafety, expected409 = false) {
  expect(safety.externalRequests).toEqual([]);
  expect(safety.pageErrors).toEqual([]);
  const expected = /^Failed to load resource: the server responded with a status of 409\b/;
  expect(safety.consoleErrors.filter((error) => !(expected409 && expected.test(error)))).toEqual([]);
}

async function expectFits(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const screen = page.locator(".people-ux");
  expect(await screen.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBeTruthy();
}

test.beforeEach(async ({ request }) => { await resetHarness(request); });

for (const width of [390, 768, 1024, 1440]) {
  test(`Pessoas mantém filtro e página ao voltar do detalhe em ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    const fixture = await peopleFixture(page);
    await loginThroughUi(page);
    await page.goto("/gestao#contatos");
    await expect(page.getByRole("heading", { name: "Pessoas", level: 2, exact: true })).toBeVisible();
    const filter = page.getByLabel("Filtrar pessoas");
    await filter.selectOption("visitante");
    await expect(page.getByRole("status").filter({ hasText: "2 pessoas neste filtro" })).toBeVisible();
    const open = page.getByRole("button", { name: "Abrir pessoa: Marina Laboratório", exact: true });
    await open.focus();
    await page.keyboard.press("Enter");
    const detail = page.getByRole("region", { name: "Detalhes de Marina Laboratório" });
    await expect(detail).toBeVisible();
    await expect(detail).toBeFocused();
    await expect(detail.getByText("Nenhuma célula vinculada", { exact: true })).toBeVisible();
    await expect(detail.getByText("550000000001", { exact: true })).toBeVisible();
    const contactAndJourney = detail.locator("details").filter({ hasText: "Contato e percurso" });
    await contactAndJourney.locator("summary").click();
    await expect(contactAndJourney.getByText("marina@example.test", { exact: true })).toBeVisible();
    await expect(contactAndJourney.locator("dl > div").filter({ has: page.locator("dt").filter({ hasText: /^Presenças em célula$/ }) }).locator("dd")).toHaveText("0");
    await expect(contactAndJourney.locator("dl > div").filter({ has: page.locator("dt").filter({ hasText: /^Decisão por Jesus$/ }) }).locator("dd")).toHaveText("Não");
    await page.screenshot({ path: testInfo.outputPath(`pessoa-detalhe-${width}.png`), fullPage: true });
    await detail.getByRole("button", { name: "Voltar à lista de pessoas" }).click();
    await expect(filter).toHaveValue("visitante");
    await expect(open).toBeFocused();
    await filter.selectOption("all");
    await page.getByRole("button", { name: "Próxima", exact: true }).click();
    await expect(page.getByText("Página 2 de 2", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "Abrir pessoa: Rafael Laboratório", exact: true }).click();
    await page.getByRole("button", { name: "Voltar à lista de pessoas" }).click();
    await expect(page.getByText("Página 2 de 2", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "Abrir pessoa: Rafael Laboratório", exact: true })).toBeFocused();
    expect(fixture.reads.at(-1)).toEqual({ page: 2, pageSize: 50, view: "all" });
    await expectFits(page);
    await page.screenshot({ path: testInfo.outputPath(`pessoas-${width}.png`), fullPage: true });

    await page.getByRole("button", { name: "Cadastrar pessoa", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Novo contato", exact: true });
    await dialog.getByLabel("Nome", { exact: true }).fill("Pessoa Nova Laboratório");
    await dialog.getByLabel("Telefone", { exact: true }).fill("5500000000100");
    await page.keyboard.press("Escape");
    await expect(dialog.getByRole("alert")).toContainText("Descartar alterações não salvas?");
    await expect(dialog.getByRole("button", { name: "Salvar contato", exact: true, includeHidden: true })).toBeDisabled();
    await dialog.getByLabel("Nome", { exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(dialog.getByRole("alert")).toContainText("Descartar alterações não salvas?");
    expect(fixture.writes).toEqual([]);
    await dialog.getByRole("button", { name: "Continuar editando" }).click();
    await expect(dialog.getByLabel("Nome", { exact: true })).toHaveValue("Pessoa Nova Laboratório");
    await dialog.getByRole("button", { name: "Salvar contato", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("Conflito fictício");
    await expect(dialog.getByLabel("Telefone", { exact: true })).toHaveValue("5500000000100");
    await page.screenshot({ path: testInfo.outputPath(`pessoa-cadastro-erro-${width}.png`), fullPage: true });
    await dialog.getByRole("button", { name: "Salvar contato", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("region", { name: "Detalhes de Pessoa Nova Laboratório" })).toBeVisible();
    expect(fixture.writes.filter((item) => item.path === "/contacts").map((item) => item.body)).toEqual([
      { nome: "Pessoa Nova Laboratório", telefone: "5500000000100", email: null, genero: null, tipo: "contato" },
      { nome: "Pessoa Nova Laboratório", telefone: "5500000000100", email: null, genero: null, tipo: "contato" },
    ]);
    await attachJson(testInfo, "people-contracts", fixture);
    expectSafety(safety, true);
  });
}

for (const width of [390, 1440]) {
  test(`Ganhar explicita vínculo e avanço autorizado em ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    const fixture = await peopleFixture(page);
    await loginThroughUi(page);
    await page.goto("/#ganhar");
    const marina = page.locator(".people-table tbody tr").filter({ hasText: "Marina Laboratório" });
    await marina.getByRole("button", { name: "Vincular célula", exact: true }).click();
    const picker = page.getByRole("dialog", { name: "Conectar à célula", exact: true });
    await expect(picker.getByRole("button", { name: /Célula Inativa Laboratório/ })).toBeDisabled();
    await picker.getByRole("button", { name: /^Célula Laboratório/ }).click();
    await expect(picker).toBeHidden();
    await expect(marina.getByText("Em acompanhamento", { exact: true })).toBeVisible();
    expect(fixture.writes.find((item) => item.path.endsWith("/cell"))?.body).toEqual({ celulaId: CELL_ID });
    await page.getByRole("button", { name: /^Visitantes/ }).click();
    const joao = page.locator(".people-table tbody tr").filter({ hasText: "João Laboratório" });
    await expect(joao.getByText("Critério para Consolidar atendido", { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`ganhar-${width}.png`), fullPage: true });
    await joao.getByRole("button", { name: "Avançar para Consolidar", exact: true }).click();
    await expect(joao).toHaveCount(0);
    expect(fixture.writes.find((item) => item.path === "/pipeline")?.body).toEqual({ pessoaId: "ux-person-2", etapa: "consolidar", subetapa: null });
    await expectFits(page);
    expectSafety(safety);
  });

  test(`Consolidação preserva decisão e etapa recusadas em ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const safety = await armBrowserSafety(page);
    const fixture = await peopleFixture(page);
    await loginThroughUi(page);
    await page.goto("/#consolidar");
    await expect(page.getByText("Próxima etapa: Fonovisita", { exact: true })).toBeVisible();
    await expectFits(page);
    await page.screenshot({ path: testInfo.outputPath(`consolidar-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "Ver progresso de Rafael Laboratório", exact: true }).click();
    let track = page.getByRole("dialog", { name: "Trilha de consolidação", exact: true });
    await expect(track.getByRole("button", { name: "Confirmar: Fonovisita", exact: true })).toBeDisabled();
    expect(fixture.writes).toEqual([]);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Lançar decisão", exact: true }).click();
    const decision = page.getByRole("dialog", { name: "Lançar decisão por Jesus", exact: true });
    await decision.getByLabel("Pessoa", { exact: true }).selectOption("ux-person-51");
    await decision.getByLabel("Célula que participa", { exact: true }).selectOption(CELL_ID);
    await decision.getByRole("button", { name: "Lançar decisão", exact: true }).click();
    await expect(decision.getByRole("alert")).toContainText("Decisão fictícia recusada");
    await expect(decision.getByLabel("Pessoa", { exact: true })).toHaveValue("ux-person-51");
    await expect(decision.getByLabel("Célula que participa", { exact: true })).toHaveValue(CELL_ID);
    await decision.getByRole("button", { name: "Lançar decisão", exact: true }).click();
    await expect(decision).toBeHidden();
    await page.evaluate(() => { window.location.hash = "consol-individual"; });
    await expect(page.getByRole("heading", { name: "Consolidação individual", exact: true })).toBeVisible();
    await expectFits(page);
    await page.screenshot({ path: testInfo.outputPath(`consolidacao-individual-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "Abrir trilha de Rafael Laboratório", exact: true }).click();
    track = page.getByRole("dialog", { name: "Trilha de consolidação", exact: true });
    const confirm = track.getByRole("button", { name: "Confirmar: Fonovisita", exact: true });
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(track.getByRole("alert")).toContainText("Etapa fictícia recusada");
    await expect(track.getByText("2 / 3", { exact: true })).toBeVisible();
    await expect(track.getByRole("button", { name: "Concluir consolidação", exact: true })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath(`consolidacao-etapa-erro-${width}.png`), fullPage: true });
    await confirm.click();
    await expect(track.getByRole("button", { name: "Concluir consolidação", exact: true })).toBeEnabled();
    await expect(track.getByText("3 / 3", { exact: true })).toBeVisible();
    await track.getByRole("button", { name: "Concluir consolidação", exact: true }).click();
    await expect(track.getByText("Consolidação concluída no registro. A gestão de turmas da Universidade da Vida ainda está indisponível.", { exact: true })).toBeVisible();
    await expect(track.getByRole("button", { name: "Concluir consolidação", exact: true })).toBeDisabled();
    await expect(track.getByRole("alert")).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath(`consolidacao-concluida-${width}.png`), fullPage: true });
    await page.keyboard.press("Escape");
    await expect(track).toBeHidden();
    const stages = fixture.writes.filter((item) => item.path === "/pipeline/advance-stage");
    expect(stages.map((item) => item.body)).toEqual([
      { consolidacaoId: CONSOLIDATION_ID, etapa: "fonovisita", concluir: false },
      { consolidacaoId: CONSOLIDATION_ID, etapa: "fonovisita", concluir: false },
      { consolidacaoId: CONSOLIDATION_ID, etapa: null, concluir: true },
    ]);
    await attachJson(testInfo, "consolidation-contracts", fixture);
    expectSafety(safety, true);
  });
}
