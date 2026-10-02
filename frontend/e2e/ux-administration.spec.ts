import { expect, test, type Page, type Route } from "@playwright/test";
import type { MeResult } from "../src/lib/api";
import type { AgentConfigStatus } from "../src/lib/agent-api";
import type {
  AdminAgente, AdminAuditEntry, AdminConsentGovernanceState, AdminIgreja,
  AdminIgrejaAdmin, AdminIgrejaDetail, AdminJevStatus, AdminMe, AdminMetrics,
  AdminOrquestrador, AdminPlano, ConsentGovernanceDecisionPayload,
  ConsentGovernancePurpose, CreateIgrejaInput, CreateIgrejaResult,
} from "../src/lib/admin-api";
import type { BroadcastCapabilities } from "../src/lib/broadcasts-api";
import type { ChurchBranding } from "../src/lib/branding-api";
import type { CalendarStatus } from "../src/lib/calendar-api";
import type { ChurchCadastro } from "../src/lib/church-cadastro-api";
import type { Contact, Page as ContactPage } from "../src/lib/contacts-api";
import type { TeamMember } from "../src/lib/dashboard-api";
import type { PermissionMatrix } from "../src/lib/permissions";
import type { SetupChecklist } from "../src/lib/setup-api";
import type { Subscription } from "../src/lib/subscription-api";
import type { ConnectionInfo } from "../src/lib/whatsapp-api";
import {
  API_URL, APP_URL, armBrowserSafety, expectCleanBrowser, loginThroughUi, resetHarness,
} from "./support/helpers";

// All identities, churches, messages and tokens below are synthetic and local.
const cors = {
  "Access-Control-Allow-Origin": APP_URL,
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
};
async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, headers: cors, contentType: "application/json", body: JSON.stringify(body) });
}
async function endpoint(page: Page, path: string, handler: (route: Route) => Promise<void>) {
  await page.route((url) => url.origin === API_URL && url.pathname === path, async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    await handler(route);
  });
}
async function readOnly(page: Page, path: string, body: unknown) {
  await endpoint(page, path, async (route) => {
    expect(route.request().method(), `read-only fixture ${path}`).toBe("GET");
    await json(route, body);
  });
}
async function expectReflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
}

const owner: MeResult = {
  appUserId: "00000000-0000-4000-8000-000000000001",
  churchId: "00000000-0000-4000-8000-000000000002",
  email: "admin.e2e@example.test", nome: "Admin E2E", chatNome: "Admin",
  roles: ["admin", "pastor"], isOwner: true,
  igrejaNome: "Igreja Laboratório", igrejaLogoUrl: null,
};
const checklist: SetupChecklist = {
  items: [
    { id: "identidade", screen: "identidade", done: false },
    { id: "equipe", screen: "equipe", done: true },
    { id: "celulas", screen: "celulas", done: false },
    { id: "whatsapp", screen: "whatsapp", done: false },
    { id: "agente", screen: "agente", done: true },
    { id: "assinatura", screen: "assinatura", done: true },
  ], pendingCount: 3,
};
const inactiveAgent: AgentConfigStatus = {
  configured: true, nome: "Assistente Laboratório", tom: "acolhedor",
  comportamento: "Atender somente no laboratório sintético.", publicoAlvo: ["visitantes"],
  acessos: ["agenda"], ativo: false,
};
const offline: ConnectionInfo = { numero: null, status: "offline", ultimaSync: null };
const calendar: CalendarStatus = {
  connected: false, calendarId: null, googleAccountEmail: null, connectionVersion: null,
};
const subscription: Subscription = {
  plano: "laboratorio", status: "ativa", pessoas: 12, limite: 100,
  proximaCobranca: "2026-11-01", setupPago: true, setupFeeContracted: 150,
  invoiceUrl: null, setupInvoiceUrl: null, invoiceReversal: null, recoveryInvoiceUrl: null,
  recoveryRequired: false, setupRecoveryRequired: false,
  hasTrackedSubscription: true, checkoutRequired: false,
};

test.beforeEach(async ({ request }) => { await resetHarness(request); });

for (const width of [390, 1440]) {
  test(`configuração e cadastro preservam tarefa, estado e valores em ${width}px`, async ({ page }, testInfo) => {
    const safety = await armBrowserSafety(page);
    await page.setViewportSize({ width, height: 960 });
    await readOnly(page, "/setup/checklist", checklist);
    const branding: ChurchBranding = { nome: owner.igrejaNome!, logoUrl: null };
    await readOnly(page, "/igreja/branding", branding);
    let logoWrites = 0;
    await endpoint(page, "/igreja/logo", async (route) => {
      logoWrites += 1;
      await json(route, branding);
    });
    await readOnly(page, "/igreja/cadastro/capabilities", { version: 1 });
    let facts: ChurchCadastro = { enderecoInstitucional: null, horariosCulto: null };
    const writes: ChurchCadastro[] = [];
    await endpoint(page, "/igreja/cadastro", async (route) => {
      if (route.request().method() === "GET") { await json(route, facts); return; }
      expect(route.request().method()).toBe("PUT");
      writes.push(route.request().postDataJSON() as ChurchCadastro);
      // A malformed success body exercises the client's validation without a real backend.
      if (writes.length === 1) { await json(route, { enderecoInstitucional: 123 }); return; }
      facts = writes.at(-1)!;
      await json(route, facts);
    });
    await loginThroughUi(page);
    await page.goto("/gestao/#setup");
    const tasks = page.getByRole("list", { name: "Tarefas de configuração" });
    await expect(tasks.getByRole("listitem")).toHaveCount(6);
    await expect(tasks.getByRole("listitem").filter({ hasText: "Identidade da igreja" })).toContainText("Opcional");
    await expect(tasks.getByRole("listitem").filter({ hasText: "Credencial do assistente" })).toContainText("Configurado");
    await expect(page.getByText(/Configurar credencial ou conectar o WhatsApp não ativa/)).toBeVisible();
    await page.goto("/gestao/#identidade");
    await expect(page.getByRole("heading", { name: "Identidade da igreja", exact: true, level: 2 })).toBeVisible();
    await expect(page.locator(".identity-screen input[type=text]")).toHaveValue(branding.nome);
    await page.locator('.identity-screen input[type="file"]').setInputFiles({
      name: "logo-sintetica.svg", mimeType: "image/svg+xml", buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'),
    });
    await expect(page.locator(".identity-screen").getByRole("alert")).toContainText("SVG não é aceito");
    await expect(page.getByRole("button", { name: "Enviar logo", exact: true })).toHaveCount(0);
    expect(logoWrites).toBe(0);
    await page.goto("/gestao/#cadastro-igreja");
    const address = page.getByRole("textbox", { name: "Endereço institucional" });
    const times = page.getByRole("textbox", { name: "Horários dos cultos" });
    await address.fill("Endereço institucional do laboratório");
    await times.fill("Domingo às 10h\nQuarta às 19h");
    await page.getByRole("button", { name: "Salvar cadastro", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toContainText("Não foi possível salvar o cadastro da igreja.");
    await expect(address).toHaveValue("Endereço institucional do laboratório");
    await expect(times).toHaveValue("Domingo às 10h\nQuarta às 19h");
    expect(writes).toHaveLength(1);
    await page.getByRole("button", { name: "Salvar cadastro", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Cadastro salvo." })).toBeVisible();
    expect(writes).toEqual([facts, facts]);
    expect(Object.keys(facts).sort()).toEqual(["enderecoInstitucional", "horariosCulto"]);
    await expectReflow(page);
    await page.screenshot({ path: testInfo.outputPath(`cadastro-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });

  test(`matriz preserva rascunho, confirma saída e salva o delta em ${width}px`, async ({ page }, testInfo) => {
    const safety = await armBrowserSafety(page);
    // O histórico funciona em Safari/mobile sem depender da Navigation API.
    await page.addInitScript(() => {
      Object.defineProperty(window, "navigation", { configurable: true, value: undefined });
    });
    await page.setViewportSize({ width, height: 960 });
    await readOnly(page, "/setup/checklist", checklist);
    let matrix: PermissionMatrix = {
      pastor: ["dashboard", "inbox", "central-celula"], lider_g12: ["dashboard"],
      lider_consol: ["dashboard"], lider_celula: ["dashboard"], lider_mult: ["dashboard"],
      operador: ["dashboard"], membro: ["dashboard"],
    };
    const writes: PermissionMatrix[] = [];
    await endpoint(page, "/roles/permissions", async (route) => {
      if (route.request().method() === "PUT") {
        matrix = (route.request().postDataJSON() as { matriz: PermissionMatrix }).matriz;
        writes.push(matrix);
      } else { expect(route.request().method()).toBe("GET"); }
      await json(route, { matriz: matrix });
    });
    await loginThroughUi(page);
    await page.goto("/gestao/#permissoes");
    if (width < 760) {
      await page.getByRole("combobox", { name: "Responsabilidade" }).selectOption("membro");
      await expect(page.getByText("Restrito a pastor/admin", { exact: true })).toBeVisible();
      await expect(page.getByRole("checkbox", { name: "Membro vê Central Célula", exact: true })).toHaveCount(0);
      await page.getByRole("combobox", { name: "Responsabilidade" }).selectOption("pastor");
    }
    const inbox = page.getByRole("checkbox", { name: "Pastor vê Conversas", exact: true });
    await expect(inbox).toBeChecked();
    await inbox.uncheck();
    await expect(page.getByRole("status").filter({ hasText: "1 alteração não salva" })).toBeVisible();
    await page.getByText("Revisar alterações de acesso", { exact: true }).click();
    await expect(page.getByText("Pastor: remover Conversas", { exact: true })).toBeVisible();
    const exit = () => page.evaluate(() => { location.hash = "setup"; });
    page.once("dialog", (dialog) => { void dialog.dismiss(); });
    await exit();
    await expect(page).toHaveURL(/#permissoes$/);
    await expect(inbox).not.toBeChecked();
    expect(writes).toHaveLength(0);
    await page.getByRole("button", { name: "Descartar", exact: true }).click();
    await expect(inbox).toBeChecked();
    await inbox.uncheck();
    await page.getByRole("button", { name: "Salvar permissões", exact: true }).click();
    await expect(page.getByRole("button", { name: "Salvar permissões", exact: true })).toBeDisabled();
    expect(writes).toHaveLength(1);
    expect(writes[0]?.pastor).not.toContain("inbox");
    expect(writes[0]?.membro).toEqual(["dashboard"]);
    await inbox.check();
    page.once("dialog", (dialog) => { void dialog.accept(); });
    await exit();
    await expect(page.getByRole("heading", { name: "Primeiros passos", exact: true, level: 2 })).toBeVisible();
    expect(writes).toHaveLength(1);
    await page.evaluate(() => { location.hash = "permissoes"; });
    await expect(inbox).not.toBeChecked();
    await inbox.check();
    page.once("dialog", (dialog) => { void dialog.dismiss(); });
    await page.goBack();
    await expect(page).toHaveURL(/#permissoes$/);
    await expect(inbox).toBeChecked();
    expect(writes).toHaveLength(1);
    await page.getByRole("button", { name: "Descartar", exact: true }).click();
    await expect(inbox).not.toBeChecked();

    // Um cancelamento não pode substituir a entrada anterior. A travessia
    // seguinte deve encontrar o mesmo destino, e Forward deve voltar aqui.
    await page.evaluate(() => { history.back(); });
    await expect(page).toHaveURL(/#setup$/);
    await expect(page.getByRole("heading", { name: "Primeiros passos", exact: true, level: 2 })).toBeVisible();
    await page.evaluate(() => { history.forward(); });
    await expect(page).toHaveURL(/#permissoes$/);
    await expect(inbox).not.toBeChecked();

    // Cria uma entrada futura real, volta, edita e cancela Forward. O cursor,
    // rascunho e destino futuro devem sobreviver sem salvar automaticamente.
    await exit();
    await expect(page).toHaveURL(/#setup$/);
    await page.evaluate(() => { history.back(); });
    await expect(page).toHaveURL(/#permissoes$/);
    await inbox.check();
    const historyLength = await page.evaluate(() => history.length);
    page.once("dialog", (dialog) => { void dialog.dismiss(); });
    await page.evaluate(() => { history.forward(); });
    await expect(page).toHaveURL(/#permissoes$/);
    await expect(inbox).toBeChecked();
    expect(await page.evaluate(() => history.length)).toBe(historyLength);
    expect(writes).toHaveLength(1);
    await page.getByRole("button", { name: "Descartar", exact: true }).click();
    await page.evaluate(() => { history.forward(); });
    await expect(page).toHaveURL(/#setup$/);
    await expect(page.getByRole("heading", { name: "Primeiros passos", exact: true, level: 2 })).toBeVisible();
    await page.evaluate(() => { history.back(); });
    await expect(page).toHaveURL(/#permissoes$/);
    await expect(inbox).not.toBeChecked();
    await expectReflow(page);
    await page.screenshot({ path: testInfo.outputPath(`permissoes-retorno-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });

  test(`assistente, canais e perfil mantêm estados distintos em ${width}px`, async ({ page }, testInfo) => {
    const safety = await armBrowserSafety(page);
    await page.setViewportSize({ width, height: 960 });
    await readOnly(page, "/agent/config", inactiveAgent);
    await readOnly(page, "/whatsapp/connection", offline);
    await readOnly(page, "/calendar/status", calendar);
    await readOnly(page, "/calendar/recipients", { recipients: [] });
    const modelWrites: unknown[] = [];
    await endpoint(page, "/agent/model", async (route) => {
      expect(route.request().method()).toBe("PUT");
      const body = route.request().postDataJSON() as { modelo: string };
      modelWrites.push(body);
      await json(route, { modelo: body.modelo, validado: true });
    });
    await loginThroughUi(page);
    await page.goto("/gestao/#agente");
    await expect(page.getByText("Assistente desativado", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Credencial LLM", exact: true }).click();
    await page.getByRole("combobox", { name: "Modelo", exact: true }).selectOption("gpt-5.6-terra");
    await page.getByRole("button", { name: "Validar e salvar modelo", exact: true }).click();
    await expect(page.getByRole("button", { name: "Revalidar credencial", exact: true })).toBeVisible();
    await expect(page.getByText("Assistente desativado", { exact: true })).toBeVisible();
    await expect(page.locator("#agKey")).toHaveValue("");
    expect(modelWrites).toEqual([{ modelo: "gpt-5.6-terra" }]);
    await page.goto("/gestao/#whatsapp");
    await expect(page.getByRole("heading", { name: "Número oficial do WhatsApp", exact: true })).toBeVisible();
    await page.getByText("Conectar com código numérico", { exact: true }).click();
    await expect(page.getByRole("button", { name: "Gerar código", exact: true })).toBeDisabled();
    await page.locator("#wa-numero").fill("5500000000000");
    await expect(page.getByRole("button", { name: "Gerar código", exact: true })).toBeEnabled();
    await page.goto("/gestao/#integracoes");
    await expect(page.getByRole("heading", { name: "Conta e importação", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Quem recebe os alertas", exact: true })).toBeVisible();
    await expect(page.getByText(/Eventos importados precisam de confirmação/)).toBeVisible();
    await page.goto("/gestao/#perfil");
    await expect(page.getByRole("heading", { name: "Seu nome na conta", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Segurança da conta", exact: true })).toBeVisible();
    await expect(page.getByLabel("Senha atual", { exact: true })).toHaveAttribute("type", "password");
    await expectReflow(page);
    await page.screenshot({ path: testInfo.outputPath(`perfil-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });

  test(`pessoas com acesso e comunicação respeitam os gates em ${width}px`, async ({ page }, testInfo) => {
    const safety = await armBrowserSafety(page);
    await page.setViewportSize({ width, height: 960 });
    const team: TeamMember[] = [
      { usuarioId: owner.appUserId, pessoaId: null, nome: owner.nome, email: owner.email,
        status: "ativo", papeis: ["admin", "pastor"] },
      { usuarioId: "acesso-sintetico-2", pessoaId: "pessoa-sintetica-2", nome: "Líder Laboratório",
        email: "lider@example.test", status: "ativo", papeis: ["lider_celula"] },
    ];
    await readOnly(page, "/team", { items: team, total: team.length, page: 1, pageSize: 50 });
    const contacts: ContactPage<Contact> = { items: [], total: 0, page: 1, pageSize: 200 };
    await readOnly(page, "/contacts", contacts);
    await readOnly(page, "/broadcasts", { items: [], total: 0, page: 1, pageSize: 50 });
    const capabilities: BroadcastCapabilities = {
      agendamentoDisponivel: false, motivo: "envios_externos_desabilitados",
    };
    await readOnly(page, "/broadcasts/capabilities", capabilities);
    await readOnly(page, "/whatsapp/connection", offline);
    await loginThroughUi(page);
    await page.goto("/gestao/#equipe");
    await expect(page.getByRole("heading", { name: "Pessoas com acesso", exact: true })).toBeVisible();
    await expect(page.getByText("Líder Laboratório", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Dar acesso ao painel", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Convidar pessoa cadastrada", exact: true })).toBeVisible();
    await page.goto("/gestao/#comunicados");
    await expect(page.getByRole("status").filter({ hasText: /Envios temporariamente desativados/ })).toBeVisible();
    await page.getByRole("textbox", { name: "Título interno", exact: true }).fill("Aviso sintético");
    await page.getByRole("textbox", { name: "Mensagem", exact: true }).fill("Mensagem do laboratório.\nSem destinatários reais.");
    await page.getByRole("button", { name: "Avançar", exact: true }).click();
    await expect(page.getByRole("button", { name: "Revisar", exact: true })).toBeDisabled();
    await expect(page.getByRole("list", { name: "Etapas do comunicado" }).locator('[aria-current="step"]')).toContainText("Segmentos");
    await expectReflow(page);
    await page.screenshot({ path: testInfo.outputPath(`comunicacao-bloqueada-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });
}

for (const isOwner of [true, false]) {
  test(`assinatura mantém autorização do dono: isOwner=${isOwner}`, async ({ page }) => {
    const safety = await armBrowserSafety(page);
    await readOnly(page, "/auth/me", { ...owner, isOwner });
    await readOnly(page, "/setup/checklist", { ...checklist,
      items: checklist.items.filter((item) => isOwner || item.id !== "assinatura") });
    let billingReads = 0;
    await endpoint(page, "/subscription", async (route) => {
      expect(route.request().method()).toBe("GET");
      billingReads += 1;
      await json(route, subscription);
    });
    await readOnly(page, "/subscription/planos", { setupFee: 150,
      planos: [{ codigo: "laboratorio", nome: "Plano Laboratório", limitePessoas: 100, precoMensal: 50 }] });
    await loginThroughUi(page);
    await page.goto("/gestao/#assinatura");
    if (isOwner) {
      await expect(page.getByRole("heading", { name: "Assinatura da igreja", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Plano Plano Laboratório", exact: true })).toBeVisible();
      expect(billingReads).toBe(1);
    } else {
      await expect(page).toHaveURL(/\/gestao\/?#setup$/);
      await expect(page.getByRole("link", { name: "Minha Assinatura", exact: true })).toHaveCount(0);
      expect(billingReads).toBe(0);
    }
    expectCleanBrowser(safety);
  });
}

const master: AdminMe = { appUserId: "master-sintetico", email: "master@example.test", nome: "Master Laboratório" };
const masterToken = "master-local-synthetic-token";
const churches: AdminIgreja[] = [
  { id: "igreja-alfa", nome: "Igreja Alfa Laboratório com nome longo", status: "ativa", plano: "laboratorio",
    setupFeeOverride: null, membros: 12, pessoas: 18, createdAt: "2026-09-30T12:00:00Z" },
  { id: "igreja-beta", nome: "Igreja Beta Laboratório", status: "aguardando_aprovacao", plano: "laboratorio",
    setupFeeOverride: null, membros: 0, pessoas: 1, createdAt: "2026-09-30T13:00:00Z" },
];
const plans: AdminPlano[] = [
  { id: "plano-laboratorio", codigo: "laboratorio", nome: "Plano Laboratório", limitePessoas: 100,
    precoMensal: 50, ativo: true, ordem: 1, emUso: 2 },
];
const metrics: AdminMetrics = {
  totalIgrejas: 2, porStatus: { ativa: 1, aguardando_aprovacao: 1 }, porPlano: { laboratorio: 2 },
  mrr: 50, totalMembros: 12, totalPessoas: 19, custoIaTotal: 0.04,
};
const purposeLabels: Record<ConsentGovernancePurpose, string> = {
  atendimento_solicitado: "Atendimento solicitado", cuidado_pastoral: "Cuidado pastoral",
  tarefas_operacionais: "Tarefas operacionais", comunicados: "Comunicados",
};
function draftState(): AdminConsentGovernanceState {
  const decisionPayload: ConsentGovernanceDecisionPayload = {
    realProcessingAgents: null, operationsAndMinimumData: null, dataSensitivityAssessment: null,
    operationalNeed: null, systemsAndRecipients: null, retentionAndDisposalInventory: null,
    operatorInstructions: null, openQuestions: null,
  };
  return { enabled: true, initialized: true, schemaVersion: "d2b2b3a/governance-draft/v1", revision: 1,
    purposes: (Object.keys(purposeLabels) as ConsentGovernancePurpose[]).map((purpose) => ({
      purpose, purposeLabel: purposeLabels[purpose], revision: 1, purposeStatus: "DRAFT_NOT_APPROVED",
      decisionPayload: { ...decisionPayload }, controllerApproved: false, humanPacketComplete: false,
      catalogReady: false, writerEligible: false,
    })) };
}
async function mockConsole(page: Page) {
  const calls: Array<{ path: string; method: string }> = [];
  const draftWrites: Array<{ path: string; decisionPayload: ConsentGovernanceDecisionPayload }> = [];
  const creations: CreateIgrejaInput[] = [];
  let governance = draftState();
  await page.route((url) => url.origin === API_URL && url.pathname.startsWith("/admin/"), async (route) => {
    const { pathname: path } = new URL(route.request().url());
    const method = route.request().method();
    if (method === "OPTIONS") { await route.fulfill({ status: 204, headers: cors }); return; }
    calls.push({ path, method });
    if (path === "/admin/login" && method === "POST") { await json(route, { token: masterToken }); return; }
    expect(route.request().headers().authorization).toBe(`Bearer ${masterToken}`);
    if (path === "/admin/me" && method === "GET") { await json(route, master); return; }
    if (path === "/admin/igrejas" && method === "GET") { await json(route, churches); return; }
    if (path === "/admin/igrejas" && method === "POST") {
      creations.push(route.request().postDataJSON() as CreateIgrejaInput);
      const result: CreateIgrejaResult = { igrejaId: "igreja-criada-sintetica", adminUsuarioId: "admin-criado-sintetico", emailEnviado: false };
      await json(route, result); return;
    }
    if (path === "/admin/metrics" && method === "GET") { await json(route, metrics); return; }
    if (path === "/admin/planos" && method === "GET") { await json(route, plans); return; }
    if (path === "/admin/billing/settings" && method === "GET") { await json(route, { setupFeePadrao: 150 }); return; }
    if (path === "/admin/orquestrador" && method === "GET") {
      const template: AdminOrquestrador = { nome: "Modelo Laboratório", tom: "acolhedor", comportamento: "Comportamento base sintético." };
      await json(route, template); return;
    }
    if (path === "/admin/audit" && method === "GET") {
      const entries: AdminAuditEntry[] = [{ id: "audit-sintetico", actorEmail: master.email, acao: "igreja_atualizada",
        alvoTipo: "igreja", alvoId: churches[0]!.id, alvoNome: churches[0]!.nome, detalhe: null, createdAt: "2026-09-30T12:00:00Z" }];
      await json(route, entries); return;
    }
    if (path === "/admin/jev" && method === "GET") {
      const status: AdminJevStatus = { configurado: false, chaveOrigem: null, chaveIlegivel: false,
        chaveAtualizadaEm: null, dpaAssinadoEm: null, integradoAoAgente: false, enviosExternosPermitidos: false,
        modelo: "modelo-sintetico", timeoutSegundos: 10, igrejas: [], idsInvalidos: 0 };
      await json(route, status); return;
    }
    const target = churches.find((church) => path.startsWith(`/admin/igrejas/${church.id}`));
    if (target && path === `/admin/igrejas/${target.id}` && method === "GET") {
      const detail: AdminIgrejaDetail = { ...target, mensalidade: 50, setupFeeAplicavel: 150,
        celulas: 2, custoIa: 0.04, tokensIa: 100, assinatura: { plano: "laboratorio", status: "ativa",
          pessoas: 12, limite: 100, proximaCobranca: "2026-11-01", setupPago: true } };
      await json(route, detail); return;
    }
    if (target && path === `/admin/igrejas/${target.id}/admins` && method === "GET") {
      const admins: AdminIgrejaAdmin[] = [{ id: "admin-alfa-sintetico", nome: "Administrador Laboratório",
        email: "admin-alfa@example.test", status: "ativo", isDono: true }];
      await json(route, admins); return;
    }
    if (target && path === `/admin/igrejas/${target.id}/agente` && method === "GET") {
      const agent: AdminAgente = { configured: true, nome: "Assistente Laboratório", tom: "acolhedor",
        comportamento: "Comportamento específico da igreja sintética.", ativo: false, credencialStatus: "active" };
      await json(route, agent); return;
    }
    if (target && path === `/admin/igrejas/${target.id}/agente/requests` && method === "GET") { await json(route, []); return; }
    if (target && path === `/admin/igrejas/${target.id}/consent-governance` && method === "GET") { await json(route, governance); return; }
    if (target && path.startsWith(`/admin/igrejas/${target.id}/consent-governance/purposes/`) && method === "PUT") {
      const purpose = path.split("/").at(-1) as ConsentGovernancePurpose;
      const body = route.request().postDataJSON() as { expectedRevision: number; decisionPayload: ConsentGovernanceDecisionPayload };
      expect(body.expectedRevision).toBe(governance.purposes.find((draft) => draft.purpose === purpose)?.revision);
      draftWrites.push({ path, decisionPayload: body.decisionPayload });
      governance = { ...governance, revision: governance.revision + 1, purposes: governance.purposes.map((draft) =>
        draft.purpose === purpose ? { ...draft, revision: draft.revision + 1, decisionPayload: body.decisionPayload } : draft) };
      await json(route, governance); return;
    }
    throw new Error(`Unexpected synthetic console request: ${method} ${path}`);
  });
  return { calls, draftWrites, creations, getGovernance: () => governance };
}
async function loginMaster(page: Page) {
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Console da Plataforma", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "E-mail", exact: true }).fill(master.email);
  await page.getByLabel("Senha", { exact: true }).fill("synthetic-local-only");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByRole("button", { name: `Abrir igreja: ${churches[0]!.nome}`, exact: true })).toBeVisible();
}

for (const width of [390, 1440]) {
  test(`console mantém igreja alvo, teclado, diálogo e rascunho em ${width}px`, async ({ page }, testInfo) => {
    const safety = await armBrowserSafety(page);
    await page.setViewportSize({ width, height: 960 });
    const fixture = await mockConsole(page);
    await loginThroughUi(page);
    await loginMaster(page);
    const open = page.getByRole("button", { name: `Abrir igreja: ${churches[0]!.nome}`, exact: true });
    await open.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: churches[0]!.nome, exact: true, level: 1 })).toBeVisible();
    await expect(page.getByText("Igreja selecionada · Console da Plataforma", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Editar dados", exact: true }).click();
    const edit = page.getByRole("dialog", { name: churches[0]!.nome, exact: true });
    await expect(edit).toContainText(`Igreja alvo: ${churches[0]!.nome}`);
    await expect(edit.getByLabel("Nome da igreja", { exact: true })).toHaveValue(churches[0]!.nome);
    await expect(edit.getByRole("button", { name: "Excluir igreja", exact: true })).toBeHidden();
    await edit.getByText("Exclusão da igreja", { exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(edit.getByRole("button", { name: "Excluir igreja", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(edit).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Editar dados", exact: true })).toBeFocused();
    const agentTab = page.getByRole("tab", { name: "Agente", exact: true });
    await agentTab.click();
    await expect(page.getByRole("textbox", { name: "Comportamento e instruções", exact: true })).toHaveValue("Comportamento específico da igreja sintética.");
    await expect(page.getByRole("checkbox", { name: /Agente ativo/ })).not.toBeChecked();
    await page.getByRole("tab", { name: "Admins", exact: true }).click();
    await expect(page.getByRole("tabpanel", { name: "Admins", exact: true })).toContainText("Administrador Laboratório");
    await page.getByRole("tab", { name: "Governança", exact: true }).click();
    await expect(page.getByTestId("draft-only-banner")).toContainText("Rascunho, não aprovado");
    await page.getByRole("article", { name: "Atendimento solicitado", exact: true })
      .getByRole("button", { name: "Editar rascunho", exact: true }).click();
    await page.getByRole("textbox", { name: "Quem participa do processamento", exact: true }).fill("Equipe institucional do laboratório, sem dados pessoais.");
    await page.getByRole("button", { name: "Salvar rascunho", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Rascunho operacional salvo." })).toBeVisible();
    expect(fixture.draftWrites).toHaveLength(1);
    expect(fixture.draftWrites[0]?.path).toBe("/admin/igrejas/igreja-alfa/consent-governance/purposes/atendimento_solicitado");
    expect(fixture.getGovernance().purposes.every((draft) => draft.purposeStatus === "DRAFT_NOT_APPROVED" &&
      !draft.controllerApproved && !draft.humanPacketComplete && !draft.catalogReady && !draft.writerEligible)).toBeTruthy();
    await expect(page.getByTestId("draft-only-banner")).toContainText("não libera o agente");
    expect(fixture.calls.filter(({ method }) => method !== "GET" && method !== "POST"))
      .toEqual([{ path: fixture.draftWrites[0]!.path, method: "PUT" }]);
    await expectReflow(page);
    await page.screenshot({ path: testInfo.outputPath(`console-governanca-${width}.png`), fullPage: true });
    expectCleanBrowser(safety);
  });

  test(`console separa criação, convite e ferramentas em ${width}px`, async ({ page }, testInfo) => {
    const safety = await armBrowserSafety(page);
    await page.setViewportSize({ width, height: 960 });
    const fixture = await mockConsole(page);
    await loginMaster(page);
    const finance = page.locator("details").filter({ has: page.getByText("Financeiro da plataforma", { exact: true }) });
    await expect(finance.getByText("MRR", { exact: true })).toBeHidden();
    await finance.getByText("Financeiro da plataforma", { exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(finance.getByText("MRR", { exact: true })).toBeVisible();
    await expect(finance.getByText(/^R\$\s*50,00$/)).toBeVisible();
    await expect(finance.getByText(/^US\$\s*0,04$/)).toBeVisible();
    await page.getByRole("button", { name: "Provisionar igreja", exact: true }).click();
    const create = page.getByRole("dialog", { name: "Provisionar nova igreja", exact: true });
    await create.getByLabel("Nome da igreja", { exact: true }).fill("Igreja Criação Laboratório");
    await create.getByLabel("Administrador — nome", { exact: true }).fill("Administrador Sintético");
    await create.getByLabel("Administrador — e-mail", { exact: true }).fill("criacao@example.test");
    await create.getByText("Conferir dados de criação", { exact: true }).click();
    await expect(create.getByRole("definition").filter({ hasText: "Igreja Criação Laboratório" })).toBeVisible();
    await create.getByRole("button", { name: "Provisionar igreja", exact: true }).click();
    await expect(create).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: /convite.*falhou/i })).toBeVisible();
    expect(fixture.creations).toHaveLength(1);
    expect(fixture.creations[0]?.nome).toBe("Igreja Criação Laboratório");
    const tools = page.getByRole("navigation", { name: "Operações da plataforma", exact: true });
    await tools.getByRole("button", { name: "Planos", exact: true }).click();
    const planDialog = page.getByRole("dialog", { name: "Planos", exact: true });
    const usedPlan = planDialog.getByRole("row", { name: /Plano Laboratório/ });
    await expect(usedPlan).toBeVisible();
    await expect(usedPlan.getByRole("button", { name: "Excluir", exact: true })).toBeDisabled();
    await expectReflow(page);
    await page.screenshot({ path: testInfo.outputPath(`console-planos-${width}.png`), fullPage: true });
    await page.keyboard.press("Escape");
    await expect(tools.getByRole("button", { name: "Planos", exact: true })).toBeFocused();
    await tools.getByRole("button", { name: "Orquestrador", exact: true }).click();
    const template = page.getByRole("dialog", { name: "Orquestrador padrão", exact: true });
    await expect(template.getByRole("textbox", { name: "Comportamento e instruções", exact: true })).toHaveValue("Comportamento base sintético.");
    await page.keyboard.press("Escape");
    await tools.getByRole("button", { name: "Jev", exact: true }).click();
    const jev = page.getByRole("dialog", { name: "Triagem Jev", exact: true });
    await expect(jev.getByText(/Não integrada: nenhum turno chama/)).toBeVisible();
    await expect(jev.getByRole("button", { name: "Testar conexão", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await tools.getByRole("button", { name: "Auditoria", exact: true }).click();
    const audit = page.getByRole("dialog", { name: "Auditoria", exact: true });
    await expect(audit.getByText(churches[0]!.nome, { exact: true })).toBeVisible();
    await expectReflow(page);
    expect(fixture.calls.filter(({ path, method }) => method !== "GET" && path !== "/admin/login"))
      .toEqual([{ path: "/admin/igrejas", method: "POST" }]);
    expectCleanBrowser(safety);
  });
}
