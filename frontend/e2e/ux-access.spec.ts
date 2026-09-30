import { expect, test, type Page, type Route } from "@playwright/test";

import {
  API_URL,
  APP_URL,
  E2E_USER,
  armBrowserSafety,
  attachJson,
  resetHarness,
  type BrowserSafety,
} from "./support/helpers";

const PASSWORD = "Senha-ficticia-2026";
const INVITE = {
  nome: "Pessoa de exemplo",
  email: "pessoa@example.test",
  igreja: "Igreja Laboratório",
  precisaCadastro: false,
};
const cors = {
  "Access-Control-Allow-Origin": APP_URL,
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

async function json(route: Route, status: number, body: unknown) {
  await route.fulfill({ status, headers: cors, contentType: "application/json", body: JSON.stringify(body) });
}

// A interceptação só alcança a origem loopback já validada pelo harness.
// Rotas não substituídas continuam no mock local, nunca em um provedor.
async function interceptPublicApi(page: Page, handler: (route: Route, pathname: string) => Promise<boolean>) {
  await page.route(`${API_URL}/**`, async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    if (!(await handler(route, new URL(route.request().url()).pathname))) await route.fallback();
  });
}

function expectHandledBrowser(safety: BrowserSafety, statuses: number[] = [], network = false) {
  expect(safety.externalRequests, "origens externas bloqueadas").toEqual([]);
  expect(safety.pageErrors, "exceções JavaScript").toEqual([]);
  const allowed = new RegExp(`^Failed to load resource: (?:the server responded with a status of (?:${statuses.join("|") || "none"})\\b.*${network ? "|net::ERR_FAILED.*" : ""})$`);
  expect(safety.consoleErrors.filter((message) => !allowed.test(message)), "console fora das falhas de transporte simuladas").toEqual([]);
}

async function expectNoSession(page: Page) {
  const session = await page.evaluate(() => ({
    church: localStorage.getItem("pastorai:token"),
    admin: localStorage.getItem("pastorai:admin-token"),
    cookie: document.cookie.includes("pastorai_token="),
  }));
  expect(session).toEqual({ church: null, admin: null, cookie: false });
}

test.beforeEach(async ({ request }) => {
  await resetHarness(request);
});

test("login mantém valores e destino na recusa e abre conversas após tentar novamente", async ({ page, request }) => {
  const safety = await armBrowserSafety(page);
  const fixture = await request.post(`${API_URL}/__e2e/ux-inbox`, { data: { enabled: true } });
  expect(fixture.ok()).toBeTruthy();
  let attempts = 0;
  await interceptPublicApi(page, async (route, pathname) => {
    if (pathname !== "/auth/login") return false;
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual(E2E_USER);
    attempts += 1;
    if (attempts === 1) await json(route, 401, { detail: "Credenciais inválidas." });
    else await route.fallback();
    return true;
  });
  await page.goto("/#login");
  await expect(page.getByRole("heading", { name: "Entre na sua igreja", exact: true })).toBeVisible();
  await page.evaluate(() => localStorage.setItem("pastorai:returnTo", "inbox"));
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByLabel("E-mail", { exact: true })).toBeFocused();
  expect(attempts, "validação local não consulta o backend").toBe(0);
  await page.getByLabel("E-mail", { exact: true }).fill(E2E_USER.email);
  const password = page.getByLabel("Senha", { exact: true });
  await password.fill(E2E_USER.password);
  await page.getByRole("button", { name: "Mostrar senha", exact: true }).click();
  await expect(password).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Ocultar senha", exact: true }).click();
  await expect(password).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.locator(".login-card").getByRole("alert")).toContainText("Verifique suas credenciais");
  await expect(page.getByLabel("E-mail", { exact: true })).toHaveValue(E2E_USER.email);
  await expect(password).toHaveValue(E2E_USER.password);
  await expectNoSession(page);
  expect(await page.evaluate(() => localStorage.getItem("pastorai:returnTo"))).toBe("inbox");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Conversas", level: 1, exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("pastorai:returnTo"))).toBeNull();
  expect(attempts).toBe(2);
  expectHandledBrowser(safety, [401]);
});

for (const response of ["200", "500", "network"] as const) {
  test(`recuperação mantém confirmação neutra com resposta ${response}`, async ({ page }) => {
    const safety = await armBrowserSafety(page);
    let attempts = 0;
    await interceptPublicApi(page, async (route, pathname) => {
      if (pathname !== "/auth/forgot-password") return false;
      expect(route.request().method()).toBe("POST");
      expect(route.request().postDataJSON()).toEqual({ email: "recuperar@example.test" });
      attempts += 1;
      if (response === "network") await route.abort("failed");
      else await json(route, Number(response), { detail: "Resposta fictícia não identifica uma conta." });
      return true;
    });
    await page.goto("/#esqueci-senha");
    await expect(page.getByRole("heading", { name: "Recuperar acesso", exact: true })).toBeVisible();
    await page.getByLabel("E-mail", { exact: true }).fill("recuperar@example.test");
    await page.getByRole("button", { name: "Pedir novo link", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Confira seu e-mail", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Confira seu e-mail", exact: true })).toBeFocused();
    await expect(page.getByRole("status")).toContainText(/Se (?:existir|houver) uma conta/);
    await expect(page.locator(".login-card").getByRole("alert")).toHaveCount(0);
    expect(attempts).toBe(1);
    await expectNoSession(page);
    await page.getByRole("link", { name: "Voltar ao login", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Entre na sua igreja", exact: true })).toBeVisible();
    expectHandledBrowser(safety, response === "500" ? [500] : [], response === "network");
  });
}

test("redefinição ignora sucesso do token anterior e preserva a senha após link expirado", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  let releaseFirst!: () => void;
  const firstPending = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const submitted: string[] = [];
  await interceptPublicApi(page, async (route, pathname) => {
    if (pathname !== "/auth/reset-password") return false;
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON() as { token: string; password: string };
    expect(body.password).toBe(PASSWORD);
    submitted.push(body.token);
    if (body.token === "token-ficticio-A") {
      await firstPending;
      await json(route, 200, {});
    } else if (submitted.length === 2) {
      await json(route, 400, { detail: "Link inválido ou expirado. Peça um novo." });
    } else await json(route, 200, {});
    return true;
  });
  await page.goto("/#redefinir-senha/token-ficticio-A");
  await expect(page.getByRole("heading", { name: "Criar nova senha", exact: true })).toBeVisible();
  await page.getByLabel("Nova senha", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirmar nova senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Redefinir senha", exact: true }).click();
  await expect.poll(() => submitted.length).toBe(1);
  await page.evaluate(() => { window.location.hash = "redefinir-senha/token-ficticio-B"; });
  await expect(page.getByLabel("Nova senha", { exact: true })).toBeEnabled();
  await expect(page.getByLabel("Nova senha", { exact: true })).toHaveValue("");
  const firstResponse = page.waitForResponse((res) => res.url() === `${API_URL}/auth/reset-password` && res.request().postDataJSON().token === "token-ficticio-A");
  releaseFirst();
  await firstResponse;
  await expect(page.getByRole("heading", { name: "Criar nova senha", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Senha atualizada", exact: true })).toHaveCount(0);
  await page.getByLabel("Nova senha", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirmar nova senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Redefinir senha", exact: true }).click();
  await expect(page.locator(".login-card").getByRole("alert")).toContainText("Link inválido ou expirado");
  await expect(page.getByLabel("Nova senha", { exact: true })).toHaveValue(PASSWORD);
  await expect(page.getByLabel("Confirmar nova senha", { exact: true })).toHaveValue(PASSWORD);
  await expect(page.getByRole("heading", { name: "Senha atualizada", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Redefinir senha", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Senha atualizada", exact: true })).toBeVisible();
  expect(submitted).toEqual(["token-ficticio-A", "token-ficticio-B", "token-ficticio-B"]);
  await expectNoSession(page);
  expectHandledBrowser(safety, [400]);
});

test("convite validado controla telefone, recusa link expirado e mantém valores na falha", async ({ page }) => {
  const safety = await armBrowserSafety(page);
  let attempts = 0;
  await interceptPublicApi(page, async (route, pathname) => {
    if (pathname.startsWith("/auth/invite/")) {
      expect(route.request().method()).toBe("GET");
      if (pathname.endsWith("expirado")) await json(route, 410, { detail: "Convite inválido ou expirado. Peça um novo." });
      else await json(route, 200, { ...INVITE, precisaCadastro: pathname.endsWith("cadastro") });
      return true;
    }
    if (pathname !== "/auth/activate") return false;
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ token: "convite-cadastro", password: PASSWORD, telefone: "5500000000000" });
    attempts += 1;
    await json(route, attempts === 1 ? 500 : 200, attempts === 1 ? { detail: "Não foi possível ativar. Tente novamente." } : {});
    return true;
  });
  await page.goto("/#ativar/convite-completo");
  await expect(page.getByRole("heading", { name: "Ativar acesso", exact: true })).toBeVisible();
  await expect(page.getByText(INVITE.nome, { exact: true })).toBeVisible();
  await expect(page.getByLabel("Telefone / WhatsApp", { exact: true })).toHaveCount(0);
  await page.evaluate(() => { window.location.hash = "ativar/convite-expirado"; });
  await expect(page.locator(".login-card").getByRole("alert")).toContainText("Convite inválido ou expirado");
  await expect(page.getByLabel("Senha", { exact: true })).toHaveCount(0);
  await page.evaluate(() => { window.location.hash = "ativar/convite-cadastro"; });
  const phone = page.getByLabel("Telefone / WhatsApp", { exact: true });
  await expect(phone).toBeVisible();
  await page.getByLabel("Senha", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirmar senha", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Ativar e criar senha", exact: true }).click();
  await expect(page.locator(".login-card").getByRole("alert")).toContainText("Informe seu telefone/WhatsApp");
  expect(attempts).toBe(0);
  await phone.fill("5500000000000");
  await page.getByRole("button", { name: "Ativar e criar senha", exact: true }).click();
  await expect(page.locator(".login-card").getByRole("alert")).toContainText("Não foi possível ativar");
  await expect(phone).toHaveValue("5500000000000");
  await expect(page.getByLabel("Senha", { exact: true })).toHaveValue(PASSWORD);
  await expect(page.getByLabel("Confirmar senha", { exact: true })).toHaveValue(PASSWORD);
  await page.getByRole("button", { name: "Ativar e criar senha", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Acesso ativado", exact: true })).toBeVisible();
  expect(attempts).toBe(2);
  await expectNoSession(page);
  expectHandledBrowser(safety, [410, 500]);
});

for (const refusal of ["login", "perfil"] as const) {
  test(`console recusa ${refusal} sem persistir sessão de igreja ou plataforma`, async ({ page }) => {
    const safety = await armBrowserSafety(page);
    const called: string[] = [];
    await interceptPublicApi(page, async (route, pathname) => {
      if (pathname === "/admin/login") {
        called.push(pathname);
        expect(route.request().method()).toBe("POST");
        expect(route.request().postDataJSON()).toEqual({ email: "restrito@example.test", password: PASSWORD });
        await json(route, refusal === "login" ? 403 : 200, refusal === "login" ? { detail: "Acesso recusado." } : { token: "console-ficticio-sem-permissao" });
        return true;
      }
      if (pathname === "/admin/me") {
        called.push(pathname);
        expect(route.request().headers().authorization).toBe("Bearer console-ficticio-sem-permissao");
        await json(route, 403, { detail: "Esta conta não tem acesso à administração da plataforma." });
        return true;
      }
      return false;
    });
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Console da Plataforma", exact: true })).toBeVisible();
    await page.getByLabel("E-mail", { exact: true }).fill("restrito@example.test");
    await page.getByLabel("Senha", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Entrar", exact: true }).click();
    await expect(page.locator(".login-card").getByRole("alert")).toContainText("Esta conta não tem acesso à administração da plataforma");
    await expect(page.getByLabel("E-mail", { exact: true })).toHaveValue("restrito@example.test");
    await expect(page.getByLabel("Senha", { exact: true })).toHaveValue(PASSWORD);
    expect(called).toEqual(refusal === "login" ? ["/admin/login"] : ["/admin/login", "/admin/me"]);
    await expectNoSession(page);
    expectHandledBrowser(safety, [403]);
  });
}

test("acesso conserva contraste, foco e campos legíveis nas quatro larguras", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const safety = await armBrowserSafety(page);
  await interceptPublicApi(page, async (route, pathname) => {
    if (pathname !== "/auth/invite/convite-visual") return false;
    await json(route, 200, { ...INVITE, precisaCadastro: true });
    return true;
  });
  const measurements = [];
  const surfaces = [
    { id: "login", url: "/#login", heading: "Entre na sua igreja" },
    { id: "recuperar", url: "/#esqueci-senha", heading: "Recuperar acesso" },
    { id: "redefinir", url: "/#redefinir-senha/token-visual", heading: "Criar nova senha" },
    { id: "ativar", url: "/#ativar/convite-visual", heading: "Ativar acesso" },
    { id: "console", url: "/admin", heading: "Console da Plataforma" },
  ];
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const surface of surfaces) {
      await page.goto(surface.url);
      await expect(page.getByRole("heading", { name: surface.heading, exact: true })).toBeVisible();
      const inputs = page.locator(".login-card input:visible");
      await expect(inputs.first()).toBeVisible();
      if (surface.id === "ativar") await expect(inputs).toHaveCount(3);
      const fields = await inputs.evaluateAll((elements) => elements.map((element) => ({
        fontSize: parseFloat(getComputedStyle(element).fontSize),
        height: element.getBoundingClientRect().height,
        width: element.getBoundingClientRect().width,
      })));
      for (const field of fields) {
        expect(field.fontSize).toBeGreaterThanOrEqual(16);
        expect(field.height).toBeGreaterThanOrEqual(44);
        expect(field.width).toBeGreaterThanOrEqual(44);
      }
      await inputs.first().focus();
      await page.keyboard.press("Tab");
      await page.keyboard.press("Shift+Tab");
      await expect(inputs.first()).toBeFocused();
      const focus = await inputs.first().evaluate((el) => ({
        visible: el.matches(":focus-visible"),
        width: getComputedStyle(el).outlineWidth,
        style: getComputedStyle(el).outlineStyle,
      }));
      expect(focus).toEqual({ visible: true, width: "2px", style: "solid" });
      const contrast = await page.locator(".login-card").evaluate((card) => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 1;
        const ctx = canvas.getContext("2d")!;
        const luminance = (color: string) => {
          ctx.fillStyle = "white";
          ctx.fillRect(0, 0, 1, 1);
          ctx.fillStyle = color;
          ctx.fillRect(0, 0, 1, 1);
          const rgb = ctx.getImageData(0, 0, 1, 1).data;
          const linear = (index: number) => {
            const value = rgb[index]! / 255;
            return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
          };
          return linear(0) * 0.2126 + linear(1) * 0.7152 + linear(2) * 0.0722;
        };
        const ratio = (foreground: string, background: string) => {
          const first = luminance(foreground);
          const second = luminance(background);
          return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
        };
        const bg = getComputedStyle(card).backgroundColor;
        const label = card.querySelector("label")!;
        const copy = card.querySelector(".sub")!;
        const action = card.querySelector('button[type="submit"]')!;
        const input = card.querySelector("input")!;
        return {
          label: ratio(getComputedStyle(label).color, bg),
          support: ratio(getComputedStyle(copy).color, bg),
          action: ratio(getComputedStyle(action).color, getComputedStyle(action).backgroundColor),
          focus: ratio(getComputedStyle(input).outlineColor, getComputedStyle(input).backgroundColor),
        };
      });
      expect(contrast.label).toBeGreaterThanOrEqual(4.5);
      expect(contrast.support).toBeGreaterThanOrEqual(4.5);
      expect(contrast.action).toBeGreaterThanOrEqual(4.5);
      expect(contrast.focus).toBeGreaterThanOrEqual(3);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
      await page.screenshot({ path: testInfo.outputPath(`acesso-${surface.id}-${width}.png`), fullPage: true });
      measurements.push({ surface: surface.id, width, fields, focus, contrast });
    }
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  const reducedMotion = await page.locator(".login-card input").first().evaluate((input) => ({
    requested: matchMedia("(prefers-reduced-motion: reduce)").matches,
    transition: getComputedStyle(input).transitionDuration.split(",").map((duration) => parseFloat(duration)),
    animation: getComputedStyle(input).animationDuration.split(",").map((duration) => parseFloat(duration)),
  }));
  expect(reducedMotion.requested).toBeTruthy();
  expect(Math.max(...reducedMotion.transition)).toBeLessThanOrEqual(0.001);
  expect(Math.max(...reducedMotion.animation)).toBeLessThanOrEqual(0.001);
  await attachJson(testInfo, "ux-access-rendered", { measurements, reducedMotion });
  expectHandledBrowser(safety);
});
